"""Optional second-stage CrossEncoder reranking for retrieved contract clauses."""
from __future__ import annotations

from typing import Any
import math

__all__ = ["RerankerError", "CrossEncoderReranker"]


class RerankerError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class CrossEncoderReranker:
    """Score query/clause pairs jointly after fast hybrid candidate retrieval."""

    def __init__(self, model_name: str, *, device: str = "cpu", max_length: int = 512,
                 revision: str | None = None, local_files_only: bool = False):
        try:
            from sentence_transformers import CrossEncoder
        except (ModuleNotFoundError, ImportError) as exc:
            raise RerankerError(
                "RERANKER_DEPENDENCY_MISSING",
                "缺少 sentence-transformers；请执行 pip install -r requirements.txt。",
            ) from exc
        try:
            self._model = CrossEncoder(model_name, device=device, max_length=max_length,
                                       revision=revision, local_files_only=local_files_only)
        except Exception as exc:
            raise RerankerError(
                "RERANKER_MODEL_LOAD_FAILED",
                f"无法加载 Reranker 模型（{type(exc).__name__}）。",
            ) from exc
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self.revision = revision

    def rerank(self, query: str, hits: list[dict], top_k: int) -> list[dict]:
        if not hits:
            return []
        try:
            scores: Any = self._model.predict(
                [(query, hit["text"]) for hit in hits],
                show_progress_bar=False,
            )
            values = [float(score) for score in scores]
        except Exception as exc:
            raise RerankerError(
                "RERANKER_INFERENCE_FAILED",
                f"Reranker 推理失败（{type(exc).__name__}）。",
            ) from exc
        if len(values) != len(hits) or not all(math.isfinite(value) for value in values):
            raise RerankerError("RERANKER_INVALID_OUTPUT", "Reranker 分数数量与候选数量不一致。")
        ranked = []
        for hit, score in zip(hits, values):
            ranked.append({**hit, "retrieval_score": hit.get("score"),
                           "rerank_score": round(score, 8), "score": round(score, 8)})
        ranked.sort(key=lambda item: (-item["rerank_score"], item["start"]))
        return ranked[:top_k]

    def metadata(self) -> dict:
        return {"backend": "sentence-transformers-cross-encoder",
                "model": self.model_name, "device": self.device,
                "revision": self.revision, "max_length": self.max_length}
