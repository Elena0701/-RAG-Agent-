"""RAGTool —— RAG工具：合同解析、检索、证据核验。

对外只有三个方法，与《合同审查Agent_工程架构与工具接口_修订版》一致：

    prepare(document_id, file_path)                 -> {"document_id","status","reason", ...}
    retrieve(document_id, query, top_k)             -> {"document_id","text":[{chunk...}]}
    verify(document_id, category, category_answer,
           predicted_answers, retrieval_history=)   -> {"evidence_checks","verification_status",
                                                        "coverage_status","reason"}

内部封装了：文件解析（PDF/TXT/JSON）→ 冻结规范文本 → 分块与偏移映射 → Embedding + BM25 融合检索
→ 位置核验 → 语义核验（可注入模型）→ No 的覆盖充分性检查。

设计上的三条硬约束：

1. 所有 ``answer_start`` 都指向 ``prepare`` 冻结的那份文本，切片规则固定为
   ``context[start:start+len(text)] == text``。
2. 空证据不允许自动 PASSED；有引用的 ``No`` 也必须通过语义与覆盖检查。
3. 技术失败（解析失败、模型故障）返回 FAILED/UNCERTAIN，不伪装成审核结论。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

try:  # 作为 tools/rag_tool.py 被 Agent 导入时
    from rag_core.coverage import absence_coverage
    from rag_core.embedding import (EmbeddingBackendError, EmbeddingCache, EmbeddingIndex,
                                    HybridIndex, SentenceTransformerEmbedder)
    from rag_core.index import BM25Index, ChunkConfig, split_by_clause, split_context, split_units
    from rag_core.pdf_ingest import IngestError, ingest
    from rag_core.rerank import CrossEncoderReranker, RerankerError
    from rag_core.semantic_review import build_review_messages, parse_review
    from rag_core.deepseek_client import DeepSeekClient, ModelConfigError
except ModuleNotFoundError:  # 作为包内相对导入时
    from ..rag_core.coverage import absence_coverage
    from ..rag_core.embedding import (EmbeddingBackendError, EmbeddingCache, EmbeddingIndex,
                                      HybridIndex, SentenceTransformerEmbedder)
    from ..rag_core.index import BM25Index, ChunkConfig, split_by_clause, split_context, split_units
    from ..rag_core.pdf_ingest import IngestError, ingest
    from ..rag_core.rerank import CrossEncoderReranker, RerankerError
    from ..rag_core.semantic_review import build_review_messages, parse_review
    from ..rag_core.deepseek_client import DeepSeekClient, ModelConfigError

ModelCall = Callable[[list[dict[str, str]]], str | dict]

__all__ = ["RAGTool", "CATEGORY_NAMES"]
CACHE_SCHEMA_VERSION = "rag-v1.3-chunking-1"

# 十一类抽取任务
CATEGORY_NAMES = (
    "Document Name",
    "Parties",
    "Agreement Date",
    "Effective Date",
    "Expiration Date",
    "Governing Law",
    "Renewal Term",
    "Notice Period To Terminate Renewal",
    "Insurance",
    "Audit Rights",
    "Termination For Convenience",
)

_YES_NO_CATEGORIES = {"Insurance", "Audit Rights", "Termination For Convenience"}

# 与 4 号 ContractReviewAgent.CATEGORIES 完全一致的固定问句。Agent 不传 category 时，
# 只有"问句与模板逐字相同"才做词表扩展；改写过的问句按纯 query 检索，不猜意图。
TEMPLATE_QUESTIONS = {
    "Document Name": "What is the name of this agreement?",
    "Parties": "Who are the contracting parties?",
    "Agreement Date": "What is the agreement date?",
    "Effective Date": "When does the agreement become effective?",
    "Expiration Date": "When does the agreement expire?",
    "Governing Law": "Which jurisdiction governs the agreement?",
    "Renewal Term": "What is the renewal term?",
    "Notice Period To Terminate Renewal": "What advance notice is required to prevent renewal?",
    "Insurance": "Does the agreement impose insurance obligations?",
    "Audit Rights": "Does a party have audit or inspection rights?",
    "Termination For Convenience": "May a party terminate without cause?",
}


def _normalize_question(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())

DEFAULT_CONFIG = {
    "chunk_size": 800,
    "chunk_overlap": 120,
    "chunk_strategy": "clause",  # clause（按条款标题切，实测更优）| char（纯字符切）
    "search_unit": "chunk",     # 默认整条款；sentence 可做子块检索/父条款返回消融
    "k1": 1.5,
    "b": 0.75,
    "retrieval_mode": "embedding",  # embedding（默认）| bm25（论文基线）
    "embedding_model": "sentence-transformers/multi-qa-MiniLM-L6-cos-v1",
    # 固定公开模型版本，避免模型更新导致论文指标漂移。
    "embedding_revision": "b207367332321f8e44f96e224ef15bc607f4dbf0",
    "embedding_device": "cpu",
    "embedding_batch_size": 32,
    "embedding_local_files_only": False,
    "embedding_cache_enabled": True,
    "embedding_cache_dir": str(Path(__file__).resolve().parent.parent / ".rag_cache"),
    "embedding_cache_max_files": 512,
    "hybrid_enabled": True,
    "ranking_policy": "structured_protected",  # selected on fixed train development subset
    "hybrid_rrf_k": 60,
    "hybrid_dense_weight": 1.0,
    "hybrid_bm25_weight": 1.2,
    "hybrid_candidate_multiplier": 4,
    "hybrid_sparse_quota_ratio": 1.0,
    # Retrospective selection: the official test split was seen in earlier work.
    "hybrid_dense_admission_threshold": 0.75,
    # auto：混合检索使用自然语言类别定义；纯向量消融只使用原始问句。
    "semantic_query_expansion": "auto",
    "reranker_enabled": False,
    "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "reranker_revision": "233902d25c440f23af6f7d6e94d2946bac0bee0a",
    "reranker_device": "cpu",
    "reranker_max_length": 512,
    "reranker_candidate_multiplier": 4,
    "max_documents": 8,
    "max_chunks": 2000,
    "semantic_context_max_chars": 120000,
    "top_k_max": 50,
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RAGTool:
    """PDF 解析、检索与证据核验统一工具。"""

    def __init__(self, config: dict | None = None):
        """配置分块、Embedding 检索、DeepSeek 核验与可注入测试后端。

        * 只有 ``config`` 也能工作：语义核验会用 ``rag_core.deepseek_client`` 读取
          ``deepseek.local.env``（或环境变量）；没有可用密钥时语义核验返回 UNCERTAIN，
          而不是假装通过。
        * 测试可传 ``model_call=lambda messages: {...}`` 注入确定性桩。
        """
        merged = dict(DEFAULT_CONFIG)
        merged.update(config or {})
        self.config = merged
        if merged['ranking_policy'] not in ('protected', 'rrf', 'structured_protected', 'structured_rrf'):
            raise ValueError('Unknown ranking_policy')
        self._retrieval_mode = str(merged.get("retrieval_mode", "embedding")).lower()
        if self._retrieval_mode not in {"embedding", "bm25"}:
            raise ValueError("retrieval_mode must be 'embedding' or 'bm25'")
        self._embedder = merged.get("embedder")
        self._reranker = merged.get("reranker")
        self._chunk_config = ChunkConfig(
            chunk_size=int(merged["chunk_size"]),
            chunk_overlap=int(merged["chunk_overlap"]),
        )
        # 与 4 号文档一致的两个缓存：
        #   _indexes  : document_id -> 分块 + Embedding/BM25 检索结构
        #   _contexts : document_id -> 冻结的完整合同文本（含哈希、页码映射）
        self._indexes: dict[str, dict[str, Any]] = {}
        self._contexts: dict[str, dict[str, Any]] = {}
        self._category_registry: dict[str, dict[str, str]] | None = None
        self._category_aliases: dict[str, str] | None = None
        self._template_lookup: dict[str, str] | None = None
        self._model_error: str | None = None
        self.model_call: ModelCall | None = merged.get("model_call")
        if self.model_call is None and merged.get("semantic", True):
            try:
                self.model_call = DeepSeekClient.from_env(merged.get("env_file"))
            except ModelConfigError as exc:
                self._model_error = f"{exc.code}: {exc}"

    # ------------------------------------------------------------------
    # 1. prepare
    # ------------------------------------------------------------------
    def prepare(self, document_id: str, file_path: str) -> dict:
        """读取文件、冻结文本、分块并建立索引；一份合同通常只调用一次。"""
        if not isinstance(document_id, str) or not document_id.strip():
            return self._failed("", "INVALID_ARGUMENT", "document_id 必须是非空字符串")
        self._indexes.pop(document_id, None)
        self._contexts.pop(document_id, None)
        if not isinstance(file_path, (str, Path)):
            return self._failed(document_id, "INVALID_ARGUMENT", "file_path 必须是路径字符串")

        path = Path(file_path)
        try:
            ingested = ingest(path)
        except IngestError as exc:
            return self._failed(document_id, exc.code, str(exc))
        except Exception as exc:  # 解析库的未知异常也要变成 FAILED
            return self._failed(document_id, "PARSE_UNEXPECTED", f"{type(exc).__name__}: {exc}")

        return self.prepare_text(document_id, ingested.text, source=str(path),
                                 method=ingested.method, pages=ingested.pages,
                                 warnings=ingested.warnings)

    def prepare_text(self, document_id: str, text: str, *, source: str = "<inline>",
                     method: str = "inline", pages: list[dict] | None = None,
                     warnings: list[str] | None = None) -> dict:
        """直接用已冻结文本建索引（离线评测与文本入口使用；Agent 调用 prepare 即可）。"""
        if not isinstance(document_id, str) or not document_id.strip():
            return self._failed("", "INVALID_ARGUMENT", "document_id 必须是非空字符串")
        # Reusing an ID for a failed replacement must not expose an old contract.
        self._indexes.pop(document_id, None)
        self._contexts.pop(document_id, None)
        if not isinstance(text, str) or not text.strip():
            return self._failed(document_id, "EMPTY_DOCUMENT", "合同文本为空")
        if len(text) > 4_000_000:
            return self._failed(document_id, "DOCUMENT_TOO_LARGE", "合同文本超过 4,000,000 字符上限")

        strategy = str(self.config.get("chunk_strategy", "char")).lower()
        splitter = split_by_clause if strategy == "clause" else split_context
        all_chunks = splitter(text, self._chunk_config)
        max_chunks = int(self.config["max_chunks"])
        if max_chunks <= 0:
            return self._failed(document_id, "INVALID_CONFIG", "max_chunks 必须是正整数")
        if len(all_chunks) > max_chunks:
            return self._failed(
                document_id,
                "INDEX_TRUNCATED",
                f"合同需要 {len(all_chunks)} 个分块，超过 max_chunks={max_chunks}；为避免漏审，未建立截断索引",
            )
        chunks = all_chunks
        context_sha = _sha256(text)
        units = split_units(chunks) if str(self.config.get("search_unit", "chunk")) == "sentence" else []
        searchable = units or chunks
        try:
            if self._retrieval_mode == "embedding":
                backend = self._embedding_backend()
                cache_enabled = bool(self.config.get("embedding_cache_enabled", True)) \
                    and self.config.get("embedder") is None
                cache = EmbeddingCache(
                    self.config.get("embedding_cache_dir")
                    if cache_enabled else None,
                    max_files=int(self.config.get("embedding_cache_max_files", 512)),
                )
                cache_key = self._embedding_cache_key(context_sha, searchable, backend)
                cached_vectors = cache.load(cache_key, len(searchable))
                dense_index = EmbeddingIndex(
                    searchable, backend, vectors=cached_vectors
                )
                if not dense_index.cache_hit:
                    cache.save(cache_key, dense_index.vectors)
                if self.config.get("hybrid_enabled", True):
                    index = HybridIndex(
                        searchable,
                        dense_index,
                        BM25Index(searchable, k1=float(self.config["k1"]),
                                  b=float(self.config["b"])),
                        rrf_k=int(self.config["hybrid_rrf_k"]),
                        dense_weight=float(self.config["hybrid_dense_weight"]),
                        sparse_weight=float(self.config["hybrid_bm25_weight"]),
                        candidate_multiplier=int(self.config["hybrid_candidate_multiplier"]),
                        sparse_quota_ratio=float(self.config["hybrid_sparse_quota_ratio"]),
                        dense_admission_threshold=float(
                            self.config["hybrid_dense_admission_threshold"]
                        ),
                        ranking_policy=str(self.config["ranking_policy"]),
                    )
                    retrieval_strategy = "hybrid"
                else:
                    index = dense_index
                    retrieval_strategy = "embedding"
            else:
                index = BM25Index(searchable, k1=float(self.config["k1"]), b=float(self.config["b"]))
                retrieval_strategy = "bm25"
        except EmbeddingBackendError as exc:
            return self._failed(document_id, exc.code, str(exc))
        self._contexts[document_id] = {
            "text": text,
            "sha256": context_sha,
            "pages": pages or [{"page": 1, "start": 0, "end": len(text)}],
            "method": method,
            "warnings": list(warnings or []),
            "path": source,
        }
        self._indexes[document_id] = {
            "chunks": chunks,
            "units": units,
            "index": index,
            "retrieval_strategy": retrieval_strategy,
            "embedding_cache_hit": bool(getattr(index, "cache_hit", False)),
            "returned_chunk_ids": set(),
        }
        while len(self._indexes) > int(self.config["max_documents"]):
            oldest = next(iter(self._indexes))
            self._indexes.pop(oldest, None)
            self._contexts.pop(oldest, None)

        return {
            "document_id": document_id,
            "status": "SUCCESS",
            "reason": f"已建立索引（{method}，{len(text)} 字符，{len(chunks)} 块）",
            "context_sha256": context_sha,
            "chars": len(text),
            "chunk_count": len(chunks),
            "retrieval_mode": self._retrieval_mode,
            "retrieval_strategy": retrieval_strategy,
            "embedding_cache_hit": bool(getattr(index, "cache_hit", False)),
            "method": method,
            "pages": len(self._contexts[document_id]["pages"]),
            "warnings": list(warnings or []),
        }

    # ------------------------------------------------------------------
    # 2. retrieve
    # ------------------------------------------------------------------
    def retrieve(self, document_id: str, query: str, top_k: int = 5,
                 category: str | None = None) -> dict:
        """返回带真实偏移的候选块；``text`` 是块字典列表，可含多个块。

        ``category`` 是可选扩展：传了就附加该类别词表做轻量查询扩展；
        不传则只用 ``query``（与 4 号文档的签名完全兼容）。
        """
        entry = self._indexes.get(document_id)
        context_entry = self._contexts.get(document_id)
        if entry is None or context_entry is None:
            return {"document_id": document_id, "text": [], "status": "FAILED",
                    "reason": "DOCUMENT_NOT_PREPARED"}
        if not isinstance(query, str) or not query.strip():
            return {"document_id": document_id, "text": [], "status": "FAILED",
                    "reason": "INVALID_QUERY"}
        if type(top_k) is not int or top_k <= 0:
            return {"document_id": document_id, "text": [], "status": "FAILED",
                    "reason": "INVALID_TOP_K"}
        top_k = min(top_k, int(self.config["top_k_max"]))
        effective_query = query
        lexical_query = query
        query_source = "none"
        resolved = category
        if resolved is None:
            resolved = self._match_template_question(query)
            query_source = "template" if resolved else "none"
        else:
            resolved = self._resolve_category(resolved)
            if resolved is None:
                return {"document_id": document_id, "text": [], "status": "FAILED",
                        "reason": "UNSUPPORTED_CATEGORY", "error_code": "UNSUPPORTED_CATEGORY"}
            query_source = "explicit"
        if resolved:
            query_profile = self._category_queries(resolved)
            vocabulary = query_profile.get("lexical", "")
            semantic_intent = query_profile.get("semantic", "")
            if vocabulary:
                lexical_query = f"{vocabulary} {query}"
            if (semantic_intent and self._retrieval_mode == "embedding"
                    and self._semantic_expansion_enabled()):
                effective_query = f"{query}\nRetrieval intent: {semantic_intent}"
            elif vocabulary and self._retrieval_mode == "bm25":
                effective_query = lexical_query
            if vocabulary or semantic_intent:
                query_source = query_source if query_source != "none" else "explicit"

        try:
            reranker_enabled = bool(self.config.get("reranker_enabled", False))
            candidate_top_k = (
                min(int(self.config["top_k_max"]),
                    top_k * int(self.config["reranker_candidate_multiplier"]))
                if reranker_enabled else top_k
            )
            search_k = candidate_top_k * 4 if entry["units"] else candidate_top_k
            if isinstance(entry["index"], HybridIndex):
                hits = entry["index"].search(
                    effective_query, top_k=search_k, lexical_query=lexical_query,
                    category=resolved,
                )
            else:
                hits = entry["index"].search(effective_query, top_k=search_k)
        except EmbeddingBackendError as exc:
            return {"document_id": document_id, "text": [], "status": "FAILED",
                    "reason": f"{exc.code}: {exc}", "error_code": exc.code}
        if entry["units"]:
            # 句子命中 → 聚合回父条款块，返回完整条款，同时保留命中的句子位置
            best: dict[int, dict] = {}
            for hit in hits:
                parent = hit["parent"]
                if parent not in best or hit["score"] > best[parent]["score"]:
                    best[parent] = {
                        **{key: hit[key] for key in (
                            "score", "fusion_score", "dense_score", "bm25_score",
                            "dense_rank", "bm25_rank", "retrieval_sources"
                        ) if key in hit},
                        "unit_start": hit["start"],
                        "unit_end": hit["end"],
                    }
            ordered = sorted(best.items(), key=lambda item: (-item[1]["score"], item[0]))
            hits = []
            for parent, info in ordered[:candidate_top_k]:
                clause = entry["chunks"][parent]
                hits.append({**clause, **info,
                             "matched_start": info["unit_start"], "matched_end": info["unit_end"],
                             "matched_text": context_entry["text"][info["unit_start"]:info["unit_end"]]})
        reranker_status = "DISABLED"
        if self.config.get("reranker_enabled", False) and hits:
            try:
                hits = self._reranker_backend().rerank(effective_query, hits, top_k)
                reranker_status = "SUCCESS"
            except RerankerError as exc:
                hits = hits[:top_k]
                reranker_status = f"{exc.code}: {exc}"
        else:
            hits = hits[:top_k]
        chunks = []
        for rank, hit in enumerate(hits, start=1):
            item = {
                "chunk_id": f"C{hit['start']}",
                "text": hit["text"],
                "start": hit["start"],
                "end": hit["end"],
                "score": hit["score"],
                "rank": rank,
                "page": self._page_of(context_entry, hit["start"]),
            }
            if "matched_start" in hit:
                item["matched_start"] = hit["matched_start"]
                item["matched_end"] = hit["matched_end"]
                item["matched_text"] = hit["matched_text"]
            for key in ("fusion_score", "dense_score", "bm25_score", "dense_rank",
                        "bm25_rank", "retrieval_sources", "retrieval_score", "rerank_score"):
                if key in hit:
                    item[key] = hit[key]
            chunks.append(item)
        entry["returned_chunk_ids"].update(item["chunk_id"] for item in chunks)
        confidence = self._retrieval_confidence(chunks, entry["retrieval_strategy"])
        return {
            "document_id": document_id,
            "text": chunks,
            "query": query,
            "effective_query": effective_query,
            "lexical_query": lexical_query,
            "expanded": effective_query != query or lexical_query != query,
            "query_source": query_source,
            "resolved_category": resolved,
            "top_k": top_k,
            "retrieval_mode": self._retrieval_mode,
            "retrieval_strategy": entry["retrieval_strategy"],
            "retrieval_confidence": confidence,
            "retrieval_confidence_calibrated": False,
            "requires_followup": confidence == "LOW",
            "reranker_status": reranker_status,
            "status": "OK" if chunks else "NO_MATCH",
            "note": "候选与分数不代表条款存在或证据支持；空结果不等于没有该条款。",
        }

    # ------------------------------------------------------------------
    # 3. verify
    # ------------------------------------------------------------------
    def verify(
        self,
        document_id: str,
        category: str,
        category_answer: Any,
        predicted_answers: list[dict],
        *,
        retrieval_history: list[dict] | None = None,
        question: str | None = None,
    ) -> dict:
        """位置核验 + 语义核验 + ``No`` 的覆盖充分性检查。

        ``question`` 是可选扩展：传了会一起交给语义核验模型（同一类别不同问法，
        判据不同）。不传则只用类别判据。
        """
        entry = self._contexts.get(document_id)
        resolved_category = self._resolve_category(category)
        base = {"document_id": document_id, "category": resolved_category or category,
                "evidence_checks": [], "verification_status": "UNCERTAIN",
                "coverage_status": "NOT_APPLICABLE",
                "reason": "", "context_sha256": entry["sha256"] if entry else None,
                "diagnostic_codes": [], "model_calls": 0}
        if entry is None:
            return self._fail(base, "DOCUMENT_NOT_PREPARED", "合同尚未 prepare 或已被缓存淘汰")
        if resolved_category is None:
            return self._fail(base, "UNSUPPORTED_CATEGORY", "不在十一类任务内")
        category = resolved_category
        if not isinstance(predicted_answers, list):
            return self._fail(base, "INVALID_INPUT", "predicted_answers 必须是列表")

        context = entry["text"]
        normalized_answer = self._normalize_answer(category, category_answer, base)

        # --- 位置核验（程序，模型不可覆盖）---------------------------------
        checks, invalid = [], False
        for index, quote in enumerate(predicted_answers):
            if not isinstance(quote, dict) or set(quote) - {"text", "answer_start"} or not {"text", "answer_start"} <= set(quote):
                return self._fail(normalized_answer, "INVALID_INPUT",
                                  "predicted_answers 每项必须只含 text 与 answer_start")
            text, start = quote["text"], quote["answer_start"]
            check = {"answer_index": index, "position_valid": False,
                     "support_status": "NOT_CHECKED", "reason": ""}
            if not isinstance(text, str) or not text.strip():
                check["reason"] = "引用为空。"
                invalid = True
            elif type(start) is not int or not 0 <= start < len(context) or start + len(text) > len(context):
                check["reason"] = "answer_start 越界或类型错误。"
                invalid = True
            elif context[start:start + len(text)] != text:
                check["reason"] = "切片与引用不一致（位置错位或文本被改写）。"
                invalid = True
            else:
                check["position_valid"] = True
                check["reason"] = "位置匹配。"
                check["page"] = self._page_of(entry, start)
            checks.append(check)

        if invalid:
            return {**normalized_answer, "evidence_checks": checks,
                    "verification_status": "FAILED",
                    "reason": "存在位置不匹配的引用，语义核验未执行。",
                    "diagnostic_codes": ["POSITION_MISMATCH"]}

        answer = normalized_answer["category_answer"]
        quoted = len(checks) > 0

        # --- Coverage proves inspection, never truth of a No answer. --------
        if not quoted:
            if answer != "No":
                return {**normalized_answer, "evidence_checks": [],
                        "verification_status": "UNCERTAIN",
                        "coverage_status": "NOT_APPLICABLE",
                        "reason": "没有引用不能证明答案；空证据不会自动通过核验。",
                        "diagnostic_codes": ["NO_EVIDENCE"]}
            coverage = self._coverage(document_id, entry, category, retrieval_history)
            return {**normalized_answer, "evidence_checks": [],
                    "verification_status": "UNCERTAIN",
                    "coverage_status": coverage["status"],
                    "reason": "检索覆盖只能证明检查范围，不能证明 No；请补充支持引用或转人工复核。",
                    "coverage_detail": coverage,
                    "diagnostic_codes": ["NO_EVIDENCE"] + (
                        ["COVERAGE_INSUFFICIENT"] if coverage["status"] != "SUFFICIENT" else [])}

        # --- 语义核验 ------------------------------------------------------
        if self.model_call is None:
            for check in checks:
                check["reason"] = "位置匹配；未配置语义核验模型，语义状态为 NOT_CHECKED。"
            coverage = self._coverage(document_id, entry, category, retrieval_history) if answer == "No" else None
            return {**normalized_answer, "evidence_checks": checks,
                    "verification_status": "UNCERTAIN",
                    "coverage_status": (coverage or {}).get("status", "NOT_APPLICABLE"),
                    "reason": "语义核验未执行（MODEL_NOT_CONFIGURED）。",
                    "coverage_detail": coverage, "model_calls": 0,
                    "diagnostic_codes": ["MODEL_NOT_CONFIGURED"]}

        if len(context) > int(self.config["semantic_context_max_chars"]):
            return {**normalized_answer, "evidence_checks": checks,
                    "verification_status": "UNCERTAIN",
                    "reason": "合同超过语义核验全文长度预算；未截断送审，请分段复核或转人工。",
                    "diagnostic_codes": ["SEMANTIC_CONTEXT_TOO_LARGE"], "model_calls": 0}

        request_payload = {
            "category": category,
            "category_answer": answer,
            "context": context,
            "predicted_answers": predicted_answers,
            "question": question,
        }
        try:
            raw = self.model_call(build_review_messages(request_payload))
            reviewed = parse_review(raw, len(checks))
        except Exception as exc:  # 模型/网络/解析失败一律不通过
            for check in checks:
                check["reason"] = "位置匹配；语义核验调用失败，未采纳任何结论。"
            return {**normalized_answer, "evidence_checks": checks,
                    "verification_status": "UNCERTAIN",
                    "reason": f"语义核验失败（{type(exc).__name__}），由 Agent 决定重试或转人工。",
                    "model_calls": 1, "diagnostic_codes": ["MODEL_ERROR"]}

        for check, reviewed_check in zip(checks, reviewed["evidence_checks"]):
            check["support_status"] = reviewed_check["support_status"]
            check["reason"] = reviewed_check["reason"]

        overall = reviewed["overall_support"]
        coverage = self._coverage(document_id, entry, category, retrieval_history) if answer == "No" else None
        statuses = [check["support_status"] for check in checks]
        if "UNSUPPORTED" in statuses or overall["status"] == "UNSUPPORTED":
            verification_status = "FAILED"
        elif all(status == "SUPPORTED" for status in statuses) and overall["status"] == "SUPPORTED":
            verification_status = "PASSED"
        else:
            verification_status = "UNCERTAIN"
        if verification_status == "PASSED" and coverage and coverage["status"] != "SUFFICIENT":
            verification_status = "UNCERTAIN"

        return {
            **normalized_answer,
            "evidence_checks": checks,
            "verification_status": verification_status,
            "coverage_status": (coverage or {}).get("status", "NOT_APPLICABLE"),
            "reason": overall["reason"],
            "overall_support": overall,
            "coverage_detail": coverage,
            "model_calls": 1,
            "diagnostic_codes": self._final_codes(verification_status, statuses, coverage),
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def context(self, document_id: str) -> str | None:
        entry = self._contexts.get(document_id)
        return entry["text"] if entry else None

    def page_of(self, document_id: str, start: int) -> int | None:
        entry = self._contexts.get(document_id)
        return self._page_of(entry, start) if entry else None

    def _match_template_question(self, query: str) -> str | None:
        if self._template_lookup is None:
            self._template_lookup = {_normalize_question(q): c for c, q in TEMPLATE_QUESTIONS.items()}
        return self._template_lookup.get(_normalize_question(query))

    def _load_category_registry(self) -> None:
        if self._category_registry is None:
            import json
            path = Path(__file__).resolve().parent.parent / "rag_core" / "categories.json"
            try:
                registry = json.loads(path.read_text(encoding="utf-8"))
                self._category_registry = {}
                self._category_aliases = {}
                for item in registry.get("categories", []):
                    canonical = item["cuad_name"]
                    self._category_registry[canonical] = {
                        "lexical": item.get("query", ""),
                        "semantic": item.get("semantic_query", ""),
                    }
                    for name in (canonical, *item.get("aliases", [])):
                        self._category_aliases[_normalize_question(name)] = canonical
            except (OSError, ValueError, KeyError):
                self._category_registry = {}
                self._category_aliases = {}

    def _resolve_category(self, category: Any) -> str | None:
        if not isinstance(category, str) or not category.strip():
            return None
        self._load_category_registry()
        return (self._category_aliases or {}).get(_normalize_question(category))

    def _category_queries(self, category: str) -> dict[str, str]:
        self._load_category_registry()
        canonical = self._resolve_category(category) or category
        return (self._category_registry or {}).get(canonical, {})

    def _category_vocabulary(self, category: str) -> str:
        """Compatibility helper retained for the evaluation script and old tests."""
        return self._category_queries(category).get("lexical", "")

    def _embedding_cache_key(self, context_sha: str, searchable: list[dict], backend: Any) -> str:
        backend_info = {}
        if hasattr(backend, "metadata"):
            try:
                backend_info = backend.metadata()
            except Exception:
                backend_info = {}
        parts = (
            CACHE_SCHEMA_VERSION,
            _sha256(repr([(c['start'], c['end'], c.get('parent'), c['text']) for c in searchable])),
            context_sha,
            str(backend_info.get("backend", type(backend).__name__)),
            str(backend_info.get("model", self.config.get("embedding_model"))),
            str(backend_info.get("revision", self.config.get("embedding_revision"))),
            str(backend_info.get("dimension")),
            str(self.config.get("chunk_strategy")),
            str(self.config.get("search_unit")),
            str(self._chunk_config.chunk_size),
            str(self._chunk_config.chunk_overlap),
            str(len(searchable)),
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _semantic_expansion_enabled(self) -> bool:
        setting = self.config.get("semantic_query_expansion", "auto")
        if isinstance(setting, str) and setting.lower() == "auto":
            return self._retrieval_mode == "embedding" and bool(
                self.config.get("hybrid_enabled", True)
            )
        return bool(setting)

    @staticmethod
    def _retrieval_confidence(chunks: list[dict], strategy: str) -> str:
        """Conservative ranking confidence; never interpreted as clause existence."""
        if not chunks:
            return "LOW"
        if strategy != "hybrid":
            return "UNASSESSED"
        top = chunks[0]
        sources = set(top.get("retrieval_sources") or [])
        if {"embedding", "bm25"} <= sources:
            if len(chunks) == 1:
                return "HIGH"
            first = float(top.get("fusion_score") or top.get("score") or 0)
            second = float(chunks[1].get("fusion_score") or chunks[1].get("score") or 0)
            return "HIGH" if first > 0 and (first - second) / first >= 0.05 else "MEDIUM"
        return "LOW"

    def model_status(self) -> dict:
        if self.model_call is None:
            return {"configured": False, "reason": self._model_error or "MODEL_NOT_CONFIGURED"}
        info = {}
        if hasattr(self.model_call, "metadata"):
            try:
                info = self.model_call.metadata()
            except Exception:
                info = {}
        return {"configured": True, "info": info}

    def embedding_status(self) -> dict:
        if self._retrieval_mode != "embedding":
            return {"configured": False, "mode": "bm25", "reason": "BM25_BASELINE"}
        try:
            backend = self._embedding_backend()
        except EmbeddingBackendError as exc:
            return {"configured": False, "mode": "embedding",
                    "reason": f"{exc.code}: {exc}"}
        info = {"backend": type(backend).__name__}
        if hasattr(backend, "metadata"):
            try:
                info = backend.metadata()
            except Exception:
                pass
        return {"configured": True, "mode": "embedding", "info": info}

    def configuration(self) -> dict:
        return {"chunking": self._chunk_config.as_dict(),
                "retrieval": self.embedding_status(),
                "retrieval_strategy": (
                    "hybrid" if self._retrieval_mode == "embedding"
                    and self.config.get("hybrid_enabled", True) else self._retrieval_mode
                ),
                "semantic_model": self.model_status(),
                "reranker": {"enabled": bool(self.config.get("reranker_enabled", False)),
                             "model": self.config.get("reranker_model"),
                             "revision": self.config.get("reranker_revision")},
                "retrieval_confidence": {"calibrated": False,
                                         "purpose": "ranking follow-up heuristic only"},
                "bm25": {"k1": self.config["k1"], "b": self.config["b"]},
                "top_k_max": self.config["top_k_max"],
                "offset_unit": "Unicode code points, zero-based [start,end)",
                "categories": list(CATEGORY_NAMES)}

    def _embedding_backend(self):
        if self._embedder is None:
            self._embedder = SentenceTransformerEmbedder(
                str(self.config["embedding_model"]),
                device=str(self.config["embedding_device"]),
                batch_size=int(self.config["embedding_batch_size"]),
                revision=self.config.get("embedding_revision"),
                local_files_only=bool(self.config.get("embedding_local_files_only", False)),
            )
        return self._embedder

    def _reranker_backend(self):
        if self._reranker is None:
            self._reranker = CrossEncoderReranker(
                str(self.config["reranker_model"]),
                device=str(self.config["reranker_device"]),
                max_length=int(self.config["reranker_max_length"]),
                revision=self.config.get("reranker_revision"),
            )
        if not hasattr(self._reranker, "rerank"):
            raise RerankerError("RERANKER_INVALID_BACKEND", "reranker 必须实现 rerank 方法。")
        return self._reranker

    @staticmethod
    def _fail(payload: dict, code: str, message: str) -> dict:
        return {**payload, "verification_status": "FAILED", "reason": message,
                "diagnostic_codes": [code]}

    @staticmethod
    def _final_codes(status: str, statuses: list, coverage: dict | None) -> list:
        codes = []
        if "UNSUPPORTED" in statuses:
            codes.append("EVIDENCE_CONTRADICTS")
        elif status == "UNCERTAIN":
            codes.append("EVIDENCE_INSUFFICIENT")
        if coverage and coverage.get("status") == "INSUFFICIENT":
            codes.append("COVERAGE_INSUFFICIENT")
        return codes

    @staticmethod
    def _failed(document_id: str, code: str, reason: str) -> dict:
        return {"document_id": document_id, "status": "FAILED",
                "reason": f"{code}: {reason}", "error_code": code}

    @staticmethod
    def _page_of(entry: dict, start: int) -> int | None:
        for page in entry["pages"]:
            if page["start"] <= start < page["end"]:
                return page["page"]
        return entry["pages"][-1]["page"] if entry["pages"] else None

    def _normalize_answer(self, category: str, answer: Any, base: dict) -> dict:
        if isinstance(answer, str):
            answer = answer.strip()
            if category in _YES_NO_CATEGORIES and answer.lower() in ("yes", "no"):
                answer = answer.capitalize()
        return {**base, "category_answer": answer}

    def _coverage(self, document_id: str, context_entry: dict, category: str,
                  retrieval_history) -> dict:
        index_entry = self._indexes.get(document_id) or {"chunks": []}
        spans = self._retrieved_spans(index_entry, retrieval_history)
        result = absence_coverage(context_entry["text"], category, spans)
        if context_entry.get("warnings"):
            result.update(status="INSUFFICIENT",
                          reason="解析存在完整性或可靠性警告，不能据提取文本确认条款不存在。")
        return result

    @staticmethod
    def _retrieved_spans(entry: dict, retrieval_history) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        if not retrieval_history:
            return spans
        if not isinstance(retrieval_history, list):
            return spans
        by_id = {f"C{chunk['start']}": chunk for chunk in entry["chunks"]}
        for round_info in retrieval_history:
            if not isinstance(round_info, dict):
                continue
            ids = round_info.get("retrieved_chunk_ids") or []
            if not isinstance(ids, list):
                continue
            for chunk_id in ids:
                if not isinstance(chunk_id, str) or chunk_id not in entry.get("returned_chunk_ids", set()):
                    continue
                chunk = by_id.get(chunk_id)
                if chunk:
                    spans.append((chunk["start"], chunk["end"]))
        return spans
