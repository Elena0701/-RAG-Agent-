"""离线评测：用最终版 RAGTool 在指定 CUAD 拆分上算 Recall@K。

只在本脚本里读取 CUAD 人工标注；RAGTool 的检索与核验不接触标注。

两种查询方式都测：
* ``query-only``  —— 完全按 4 号 Agent 的调用方式：retrieve(document_id, question, top_k)
* ``query+category`` —— 额外传 category，让 RAGTool 附加类别词表（可选扩展）

口径：
* span Recall@K = top-K 块并集覆盖 gold span ≥80% 字符
* exact@K      = gold 标注的具体位置区间完整包含于一个 top-K 块内
* contract@K   = 该类至少一个 gold span 被覆盖的合同比例
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.rag_tool import RAGTool  # noqa: E402
from rag_core.index import covered_chars  # noqa: E402

DEFAULT_CUAD = ROOT.parent / "data" / "cuad" / "source" / "test.json"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
DEFAULT_EMBEDDING_REVISION = "b207367332321f8e44f96e224ef15bc607f4dbf0"
DEFAULT_RERANKER_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
QUERY_MODES = ("as-agent", "with-category", "question-only", "vocab-only", "reworded")

QUESTIONS = {
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


def gold_spans(qas, category, context):
    spans, seen = [], set()
    for qa in qas:
        # test/CUADv1 use ``__Category``; train_separate_questions stores
        # one answer per QA as ``__Category_0``, ``__Category_1``, ...
        qa_category = str(qa.get("id", "")).rsplit("__", 1)[-1]
        if qa_category != category and not re.fullmatch(
            re.escape(category) + r"_\d+", qa_category
        ):
            continue
        for answer in qa.get("answers", []):
            text, start = answer.get("text") or "", answer.get("answer_start")
            if not isinstance(start, int) or not text:
                continue
            if context[start:start + len(text)] != text or (start, text) in seen:
                continue
            seen.add((start, text))
            spans.append((start, start + len(text), text))
    return spans


def evaluate(limit: int, top_k: int, threshold: float, mode: str, strategy: str = "char",
             search_unit: str = "chunk", b: float = 0.75,
             retrieval_mode: str = "embedding",
             embedding_model: str = DEFAULT_EMBEDDING_MODEL,
             embedding_revision: str | None = DEFAULT_EMBEDDING_REVISION,
             hybrid_enabled: bool = True,
             hybrid_dense_weight: float = 1.0,
             hybrid_bm25_weight: float = 1.2,
             hybrid_rrf_k: int = 60,
             hybrid_sparse_quota_ratio: float = 1.0,
             hybrid_dense_admission_threshold: float = 0.75,
             semantic_query_expansion: bool | None = None,
             reranker_enabled: bool = False,
             reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
             reranker_revision: str | None = DEFAULT_RERANKER_REVISION,
             ranking_policy: str = "structured_protected",
             cuad_path: Path = DEFAULT_CUAD):
    """mode: as-agent / with-category / reworded"""
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    raw_bytes = cuad_path.read_bytes()
    raw = json.loads(raw_bytes.decode("utf-8"))
    documents = raw["data"][:limit] if limit else raw["data"]
    active_ks = tuple(sorted({top_k, *(k for k in (1, 3, 5, 10) if k <= top_k)}))
    primary_k = 5 if 5 in active_ks else max(active_ks)
    tool = RAGTool({"chunk_size": 800, "chunk_overlap": 120, "semantic": False,
                    "chunk_strategy": strategy, "search_unit": search_unit, "b": b,
                    "retrieval_mode": retrieval_mode, "embedding_model": embedding_model,
                    "embedding_revision": embedding_revision,
                    "hybrid_enabled": hybrid_enabled,
                    "ranking_policy": ranking_policy,
                    "hybrid_dense_weight": hybrid_dense_weight,
                    "hybrid_bm25_weight": hybrid_bm25_weight,
                    "hybrid_rrf_k": hybrid_rrf_k,
                    "hybrid_sparse_quota_ratio": hybrid_sparse_quota_ratio,
                    "hybrid_dense_admission_threshold": hybrid_dense_admission_threshold,
                    "semantic_query_expansion": (
                        "auto" if semantic_query_expansion is None else semantic_query_expansion
                    ),
                    "reranker_enabled": reranker_enabled,
                    "reranker_model": reranker_model,
                    "reranker_revision": reranker_revision})
    if mode == "question-only":
        tool._match_template_question = lambda query: None  # 消融：不做类别扩展
    stats = defaultdict(lambda: {"contracts": 0, "spans": 0,
                                 "hit": {k: 0 for k in active_ks},
                                 "exact": {k: 0 for k in active_ks},
                                 "contract_hit": {k: 0 for k in active_ks}})
    started = time.time()
    failures = []
    for doc in documents:
        title = doc["title"]
        context = doc["paragraphs"][0]["context"]
        qas = doc["paragraphs"][0].get("qas", [])
        prepared = tool.prepare_text(title, context)
        if prepared["status"] != "SUCCESS":
            failures.append({"document": title, "reason": prepared["reason"]})
        # 冻结文本可能因归一化变化，gold 偏移以冻结文本为准重新校验
        frozen = tool.context(title) or context
        for category, question in QUESTIONS.items():
            spans = gold_spans(qas, category, context)
            if not spans:
                continue
            frozen_spans = []
            for start, end, text in spans:
                if frozen[start:start + len(text)] == text:
                    frozen_spans.append((start, end, text))
            if not frozen_spans:
                continue
            entry = stats[category]
            entry["contracts"] += 1
            entry["spans"] += len(frozen_spans)
            if mode == "with-category":
                result = tool.retrieve(title, question, top_k=top_k, category=category)
            elif mode == "question-only":
                result = tool.retrieve(title, question, top_k=top_k)
            elif mode == "vocab-only":
                result = tool.retrieve(title, tool._category_vocabulary(category), top_k=top_k)
            elif mode == "reworded":
                result = tool.retrieve(title, question + " Please cite the relevant clause.", top_k=top_k)
            else:
                result = tool.retrieve(title, question, top_k=top_k)
            chunks = result["text"]
            contract_hits = {k: False for k in active_ks}
            for k in active_ks:
                top = chunks[:k]
                intervals = [(c["start"], c["end"]) for c in top]
                for start, end, text in frozen_spans:
                    if covered_chars(start, end, intervals) / (end - start) >= threshold:
                        entry["hit"][k] += 1
                        contract_hits[k] = True
                    if any(c['start'] <= start and end <= c['end'] for c in top):
                        entry["exact"][k] += 1
            for k in active_ks:
                entry["contract_hit"][k] += int(contract_hits[k])
    elapsed = time.time() - started

    rows = []
    for category, entry in sorted(stats.items()):
        n = entry["spans"]
        row = {
            "category": category,
            "contracts": entry["contracts"],
            "gold_spans": n,
        }
        for k in active_ks:
            row[f"recall@{k}"] = round(entry["hit"][k] / n, 4) if n else None
            row[f"exact@{k}"] = round(entry["exact"][k] / n, 4) if n else None
            row[f"contract@{k}"] = (
                round(entry["contract_hit"][k] / entry["contracts"], 4)
                if entry["contracts"] else None
            )
        rows.append(row)
    total_spans = sum(r["gold_spans"] for r in rows)
    if not rows or not total_spans:
        raise ValueError(
            "No gold spans were recognised for the 11 configured categories; "
            "check the CUAD split schema and category IDs."
        )
    micro, macro = {}, {}
    for k in active_ks:
        for metric in ("recall", "exact"):
            key = f"{metric}@{k}"
            counter = 'hit' if metric == 'recall' else 'exact'
            micro[key] = round(sum(entry[counter][k] for entry in stats.values()) / total_spans, 4)
            macro[key] = (round(sum(r[key] for r in rows) / len(rows), 4)
                          if rows else None)
    summary = {
        "dataset": {"path": str(cuad_path), "file": cuad_path.name,
                    "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "split": cuad_path.stem, "documents_evaluated": len(documents)},
        "config": {"chunk_size": 800, "chunk_overlap": 120, "top_k": top_k,
                   "threshold": threshold, "query_mode": mode, "chunk_strategy": strategy,
                   "search_unit": search_unit, "retrieval_mode": retrieval_mode,
                   "embedding_model": embedding_model if retrieval_mode == "embedding" else None,
                   "embedding_revision": embedding_revision if retrieval_mode == "embedding" else None,
                   "hybrid_enabled": hybrid_enabled if retrieval_mode == "embedding" else False,
                   "ranking_policy": ranking_policy,
                   "hybrid_dense_weight": hybrid_dense_weight,
                   "hybrid_bm25_weight": hybrid_bm25_weight,
                   "hybrid_rrf_k": hybrid_rrf_k,
                   "hybrid_sparse_quota_ratio": hybrid_sparse_quota_ratio,
                   "hybrid_dense_admission_threshold": hybrid_dense_admission_threshold,
                   "semantic_query_expansion": (
                       "auto" if semantic_query_expansion is None else semantic_query_expansion
                   ),
                   "reranker_enabled": reranker_enabled,
                   "reranker_model": reranker_model if reranker_enabled else None,
                   "reranker_revision": reranker_revision if reranker_enabled else None,
                   "reported_k": list(active_ks), "primary_k": primary_k},
        "contracts": len(documents),
        "prepare_failures": failures,
        "exact_definition": "gold occurrence fully contained in one returned chunk at its annotated position",
        "gold_spans": total_spans,
        "micro": micro, "macro": macro,
        "elapsed_seconds": round(elapsed, 1),
        "categories": rows,
    }
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--chunk-strategy", choices=["char", "clause"], default="clause",
                        help="与 RAGTool 默认值保持一致；对照时显式传 char")
    parser.add_argument("--search-unit", choices=["chunk", "sentence"], default="chunk")
    parser.add_argument("--b", type=float, default=0.75)
    parser.add_argument("--retrieval-mode", choices=["embedding", "bm25"], default="embedding")
    parser.add_argument("--embedding-model",
                        default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--embedding-revision", default=DEFAULT_EMBEDDING_REVISION)
    parser.add_argument("--dense-only", action="store_true",
                        help="关闭 BM25 融合，只评测纯 Embedding 消融")
    parser.add_argument("--hybrid-dense-weight", type=float, default=1.0)
    parser.add_argument("--hybrid-bm25-weight", type=float, default=1.2)
    parser.add_argument("--hybrid-rrf-k", type=int, default=60)
    parser.add_argument("--hybrid-sparse-quota-ratio", type=float, default=1.0)
    parser.add_argument("--hybrid-dense-admission-threshold", type=float, default=0.75)
    parser.add_argument("--ranking-policy", choices=['protected','rrf','structured_protected','structured_rrf'],
                        default='structured_protected')
    parser.add_argument("--semantic-query-expansion", action=argparse.BooleanOptionalAction,
                        default=None,
                        help="是否追加类别自然语言定义；默认 auto（混合开、纯向量关）")
    parser.add_argument("--reranker-enabled", action="store_true")
    parser.add_argument("--reranker-model", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    parser.add_argument("--reranker-revision", default=DEFAULT_RERANKER_REVISION)
    parser.add_argument("--modes", nargs="+", choices=QUERY_MODES, default=list(QUERY_MODES),
                        help="只评测指定问法；默认运行全部五种问法")
    parser.add_argument("--cuad", type=Path, default=DEFAULT_CUAD,
                        help="CUAD JSON 路径；默认读取独立 test.json")
    parser.add_argument("--out", type=Path, default=ROOT / "results/rag_tool_eval.json")
    args = parser.parse_args(argv)
    if not args.cuad.is_file():
        parser.error(f"找不到 CUAD 数据文件：{args.cuad}；请用 --cuad 指定 JSON 拆分")

    results = {}
    for mode in args.modes:
        summary = evaluate(
            args.limit, args.top_k, args.threshold, mode,
            strategy=args.chunk_strategy, search_unit=args.search_unit, b=args.b,
            retrieval_mode=args.retrieval_mode, embedding_model=args.embedding_model,
            embedding_revision=args.embedding_revision,
            hybrid_enabled=not args.dense_only,
            hybrid_dense_weight=args.hybrid_dense_weight,
            hybrid_bm25_weight=args.hybrid_bm25_weight,
            hybrid_rrf_k=args.hybrid_rrf_k,
            hybrid_sparse_quota_ratio=args.hybrid_sparse_quota_ratio,
            hybrid_dense_admission_threshold=args.hybrid_dense_admission_threshold,
            ranking_policy=args.ranking_policy,
            semantic_query_expansion=args.semantic_query_expansion,
            reranker_enabled=args.reranker_enabled,
            reranker_model=args.reranker_model,
            reranker_revision=args.reranker_revision,
            cuad_path=args.cuad,
        )
        label = summary["config"]["query_mode"]
        results[label] = summary
        primary_k = summary["config"]["primary_k"]
        print(f"{label:16s} span R@1={summary['micro']['recall@1']:.3f} "
              f"R@{primary_k}={summary['micro'][f'recall@{primary_k}']:.3f} "
              f"exact@{primary_k}={summary['micro'][f'exact@{primary_k}']:.3f} "
              f"macro R@{primary_k}={summary['macro'][f'recall@{primary_k}']:.3f} "
              f"({summary['elapsed_seconds']}s)")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    best = results.get("with-category") or next(iter(results.values()))
    primary_k = best["config"]["primary_k"]
    print(f"\n{'category':38s} {'spans':>6s} {'R@1':>6s} "
          f"{'R@' + str(primary_k):>6s} {'exact@' + str(primary_k):>8s}")
    for row in best["categories"]:
        print(f"{row['category']:38s} {row['gold_spans']:6d} {row['recall@1']:6.3f} "
              f"{row[f'recall@{primary_k}']:6.3f} {row[f'exact@{primary_k}']:8.3f}")
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
