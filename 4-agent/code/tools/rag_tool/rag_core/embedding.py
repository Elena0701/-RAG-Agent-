"""Dense embedding backend and exact cosine search for contract-local RAG.

The production backend uses Sentence Transformers, but the index accepts any
object that implements ``encode_documents`` and ``encode_query``.  This keeps
the Agent interface stable and lets tests inject a small deterministic model.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from .ranking import select_candidates

import numpy as np

__all__ = [
    "EmbeddingBackendError",
    "SentenceTransformerEmbedder",
    "EmbeddingIndex",
    "EmbeddingCache",
    "HybridIndex",
]


class EmbeddingBackendError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _normalise_matrix(values: Any, rows: int) -> np.ndarray:
    try:
        matrix = np.asarray(values, dtype=np.float32)
    except (TypeError, ValueError):
        raise EmbeddingBackendError("EMBEDDING_INVALID_OUTPUT",
                                    "Embedding 模型返回了无法转换的向量。") from None
    if matrix.ndim == 1 and rows == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[0] != rows or matrix.shape[1] == 0:
        raise EmbeddingBackendError("EMBEDDING_INVALID_OUTPUT",
                                    "Embedding 向量数量或维度与输入不一致。")
    if not np.isfinite(matrix).all():
        raise EmbeddingBackendError("EMBEDDING_INVALID_OUTPUT", "Embedding 向量包含非有限值。")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise EmbeddingBackendError("EMBEDDING_ZERO_VECTOR", "Embedding 模型返回了零向量。")
    return matrix / norms


class SentenceTransformerEmbedder:
    """Lazy local Sentence Transformers encoder with query/document methods."""

    def __init__(self, model_name: str, *, device: str = "cpu", batch_size: int = 32,
                 revision: str | None = None, local_files_only: bool = False):
        if not isinstance(model_name, str) or not model_name.strip():
            raise EmbeddingBackendError("EMBEDDING_INVALID_CONFIG", "embedding_model 必须是模型名。")
        if not isinstance(device, str) or not device.strip():
            raise EmbeddingBackendError("EMBEDDING_INVALID_CONFIG", "embedding_device 必须是设备名。")
        if type(batch_size) is not int or batch_size <= 0:
            raise EmbeddingBackendError("EMBEDDING_INVALID_CONFIG", "embedding_batch_size 必须是正整数。")
        try:
            from sentence_transformers import SentenceTransformer
        except (ModuleNotFoundError, ImportError) as exc:
            raise EmbeddingBackendError(
                "EMBEDDING_DEPENDENCY_MISSING",
                "缺少 sentence-transformers；请执行 pip install -r requirements.txt。",
            ) from exc
        try:
            self._model = SentenceTransformer(
                model_name,
                device=device,
                revision=revision,
                local_files_only=local_files_only,
            )
        except Exception as exc:
            raise EmbeddingBackendError(
                "EMBEDDING_MODEL_LOAD_FAILED",
                f"无法加载 Embedding 模型（{type(exc).__name__}）。",
            ) from exc
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.revision = revision
        self.local_files_only = local_files_only
        self._query_cache: dict[str, np.ndarray] = {}

    def _encode(self, method: str, texts: list[str]) -> np.ndarray:
        encoder = getattr(self._model, method, None) or self._model.encode
        try:
            values = encoder(texts, batch_size=self.batch_size, show_progress_bar=False,
                             convert_to_numpy=True, normalize_embeddings=True)
        except Exception as exc:
            raise EmbeddingBackendError(
                "EMBEDDING_INFERENCE_FAILED",
                f"Embedding 推理失败（{type(exc).__name__}）。",
            ) from exc
        return _normalise_matrix(values, len(texts))

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode("encode_document", texts)

    def encode_query(self, text: str) -> np.ndarray:
        cached = self._query_cache.get(text)
        if cached is None:
            cached = self._encode("encode_query", [text])[0]
            self._query_cache[text] = cached
            if len(self._query_cache) > 512:
                self._query_cache.pop(next(iter(self._query_cache)))
        return cached

    def metadata(self) -> dict:
        dimension = None
        try:
            getter = (getattr(self._model, "get_embedding_dimension", None)
                      or getattr(self._model, "get_sentence_embedding_dimension"))
            dimension = int(getter())
        except (AttributeError, TypeError, ValueError):
            pass
        return {"backend": "sentence-transformers", "model": self.model_name,
                "revision": self.revision, "device": self.device,
                "dimension": dimension, "local_files_only": self.local_files_only}


class EmbeddingIndex:
    """Exact cosine search over the chunks of one contract."""

    def __init__(self, chunks: list[dict], embedder: Any, *, vectors: Any | None = None):
        self.chunks = chunks
        self.embedder = embedder
        self.cache_hit = vectors is not None
        if not chunks:
            self._vectors = np.empty((0, 0), dtype=np.float32)
            return
        if not hasattr(embedder, "encode_documents") or not hasattr(embedder, "encode_query"):
            raise EmbeddingBackendError(
                "EMBEDDING_INVALID_BACKEND",
                "embedder 必须实现 encode_documents 和 encode_query。",
            )
        self._vectors = _normalise_matrix(
            vectors if vectors is not None
            else embedder.encode_documents([chunk["text"] for chunk in chunks]),
            len(chunks),
        )

    @property
    def vectors(self) -> np.ndarray:
        return self._vectors

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or not self.chunks:
            return []
        query_vector = _normalise_matrix([self.embedder.encode_query(query)], 1)[0]
        if query_vector.shape[0] != self._vectors.shape[1]:
            raise EmbeddingBackendError("EMBEDDING_DIMENSION_MISMATCH",
                                        "查询向量与合同向量维度不一致。")
        scores = self._vectors @ query_vector
        order = np.argsort(-scores, kind="stable")[:top_k]
        return [{"score": round(float(scores[index]), 8), **self.chunks[int(index)]}
                for index in order]


class EmbeddingCache:
    """Small, non-authoritative on-disk cache for document vectors.

    Cache corruption or an unwritable cache directory never breaks retrieval;
    the caller simply recomputes embeddings. Files contain numeric arrays only
    (``allow_pickle=False``), so no contract text or API credentials are stored.
    """

    def __init__(self, directory: str | Path | None, *, max_files: int = 512):
        if type(max_files) is not int or max_files <= 0:
            raise ValueError("max_files must be a positive integer")
        self.directory = Path(directory) if directory else None
        self.max_files = max_files

    def load(self, key: str, rows: int) -> np.ndarray | None:
        if self.directory is None:
            return None
        path = self.directory / f"{key}.npy"
        try:
            values = np.load(path, allow_pickle=False)
            return _normalise_matrix(values, rows)
        except (OSError, ValueError, EmbeddingBackendError):
            return None

    def save(self, key: str, values: np.ndarray) -> bool:
        if self.directory is None:
            return False
        path = self.directory / f"{key}.npy"
        temporary: Path | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            try:
                self.directory.chmod(0o700)
            except OSError:
                pass
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{key}.", suffix=".tmp",
                dir=self.directory, delete=False,
            ) as handle:
                temporary = Path(handle.name)
                np.save(handle, values, allow_pickle=False)
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            os.replace(temporary, path)
            try:
                path.chmod(0o600)
            except OSError:
                pass
            self._prune()
            return True
        except OSError:
            try:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _prune(self) -> None:
        """Best-effort LRU-style cleanup; cache failures never break retrieval."""
        if self.directory is None:
            return
        try:
            files = sorted(
                self.directory.glob("*.npy"),
                key=lambda item: item.stat().st_mtime_ns,
                reverse=True,
            )
            for stale in files[self.max_files:]:
                stale.unlink(missing_ok=True)
        except OSError:
            pass


class HybridIndex:
    """Fuse dense and BM25 rankings with weighted reciprocal-rank fusion."""

    def __init__(self, chunks: list[dict], dense_index: EmbeddingIndex, sparse_index: Any,
                 *, rrf_k: int = 60, dense_weight: float = 1.0,
                 sparse_weight: float = 1.2, candidate_multiplier: int = 4,
                 sparse_quota_ratio: float = 1.0,
                 dense_admission_threshold: float = 0.75,
                 ranking_policy: str = "protected"):
        if type(rrf_k) is not int or rrf_k <= 0:
            raise ValueError("rrf_k must be a positive integer")
        if dense_weight <= 0 or sparse_weight <= 0:
            raise ValueError("hybrid weights must be positive")
        if type(candidate_multiplier) is not int or candidate_multiplier <= 0:
            raise ValueError("candidate_multiplier must be a positive integer")
        if not 0 <= sparse_quota_ratio <= 1:
            raise ValueError("sparse_quota_ratio must be in [0, 1]")
        if not -1 <= dense_admission_threshold <= 1:
            raise ValueError("dense_admission_threshold must be in [-1, 1]")
        self.chunks = chunks
        self.dense_index = dense_index
        self.sparse_index = sparse_index
        self.rrf_k = rrf_k
        self.dense_weight = float(dense_weight)
        self.sparse_weight = float(sparse_weight)
        self.candidate_multiplier = candidate_multiplier
        self.sparse_quota_ratio = float(sparse_quota_ratio)
        self.dense_admission_threshold = float(dense_admission_threshold)
        self.cache_hit = dense_index.cache_hit
        self.ranking_policy = ranking_policy

    @staticmethod
    def _key(hit: dict) -> tuple[int, int, int | None]:
        return hit["start"], hit["end"], hit.get("parent")

    def search(self, dense_query: str, top_k: int = 5, *, lexical_query: str | None = None,
               category: str | None = None) -> list[dict]:
        candidate_k = max(top_k, min(len(self.chunks), top_k * self.candidate_multiplier))
        dense_hits = self.dense_index.search(dense_query, top_k=candidate_k)
        sparse_hits = self.sparse_index.search(lexical_query or dense_query, top_k=candidate_k)
        if self.ranking_policy != "protected":
            return select_candidates(
                dense_hits, sparse_hits, self.chunks, category, top_k,
                policy=self.ranking_policy, rrf_k=self.rrf_k,
                dense_weight=self.dense_weight, sparse_weight=self.sparse_weight,
                admission_threshold=self.dense_admission_threshold,
            )
        fused: dict[tuple[int, int, int | None], dict] = {}

        for source, weight, hits in (
            ("embedding", self.dense_weight, dense_hits),
            ("bm25", self.sparse_weight, sparse_hits),
        ):
            for rank, hit in enumerate(hits, start=1):
                key = self._key(hit)
                item = fused.setdefault(key, {
                    **hit,
                    "fusion_score": 0.0,
                    "dense_score": None,
                    "bm25_score": None,
                    "dense_rank": None,
                    "bm25_rank": None,
                    "retrieval_sources": [],
                })
                item["fusion_score"] += weight / (self.rrf_k + rank)
                item["retrieval_sources"].append(source)
                if source == "embedding":
                    item["dense_score"], item["dense_rank"] = hit["score"], rank
                else:
                    item["bm25_score"], item["bm25_rank"] = hit["score"], rank

        all_ranked = sorted(
            fused.values(),
            key=lambda item: (-item["fusion_score"], item["start"]),
        )
        # Contract terms, dates and party names often favour exact lexical
        # matching. By default retain the BM25 top-k set; only replace its
        # last item when a genuinely new dense candidate clears a conservative
        # cosine threshold. Lower sparse_quota_ratio values expose ordinary RRF
        # for ablation experiments.
        sparse_quota = min(top_k, int(round(top_k * self.sparse_quota_ratio)))
        required_sparse = list(sparse_hits[:sparse_quota])
        admitted_dense = None
        if sparse_quota == top_k and top_k > 0:
            sparse_top_keys = {self._key(hit) for hit in sparse_hits[:top_k]}
            admitted_dense = next(
                (hit for hit in dense_hits
                 if self._key(hit) not in sparse_top_keys
                 and float(hit["score"]) >= self.dense_admission_threshold),
                None,
            )
            if admitted_dense is not None and required_sparse:
                required_sparse = required_sparse[:-1]
        required_keys = [self._key(hit) for hit in required_sparse]
        if admitted_dense is not None:
            required_keys.append(self._key(admitted_dense))
        selected_keys = set(required_keys)
        for item in all_ranked:
            if len(selected_keys) >= top_k:
                break
            selected_keys.add(self._key(item))
        ranked = [item for item in all_ranked if self._key(item) in selected_keys][:top_k]
        if sparse_quota == top_k:
            ranked.sort(key=lambda item: (
                item.get("bm25_rank") is None,
                item.get("bm25_rank") if item.get("bm25_rank") is not None else 10**9,
                -item["fusion_score"],
            ))
        for item in ranked:
            item["fusion_score"] = round(item["fusion_score"], 8)
            item["score"] = item["fusion_score"]
        return ranked
