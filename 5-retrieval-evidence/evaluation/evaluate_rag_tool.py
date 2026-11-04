"""离线评测：用最终版 RAGTool 在 CUAD 全量上算 Recall@K。

只在本脚本里读取 CUAD 人工标注；RAGTool 的检索与核验不接触标注。

两种查询方式都测：
* ``query-only``  —— 完全按 4 号 Agent 的调用方式：retrieve(document_id, question, top_k)
* ``query+category`` —— 额外传 category，让 RAGTool 附加类别词表（可选扩展）

口径：
* span Recall@K = top-K 块并集覆盖 gold span ≥80% 字符
* exact@K      = gold 原文逐字出现在 top-K 块内
* contract@K   = 该类至少一个 gold span 被覆盖的合同比例
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.rag_tool import RAGTool  # noqa: E402
from rag_core.index import covered_chars  # noqa: E402

DEFAULT_CUAD = ROOT.parent / "data" / "cuad" / "source" / "CUADv1.json"

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
        if not qa["id"].endswith("__" + category):
            continue
        for answer in qa.get("answers", []):
            text, start = answer.get("text") or "", answer.get("answer_start")
            if not isinstance(start, int) or not text:
                continue
            if context[start:start + len(text)] != text or start in seen:
                continue
            seen.add(start)
            spans.append((start, start + len(text), text))
    return spans


def evaluate(limit: int, top_k: int, threshold: float, mode: str, strategy: str = "char",
             search_unit: str = "chunk", b: float = 0.75,
             cuad_path: Path = DEFAULT_CUAD):
    """mode: as-agent / with-category / reworded"""
    raw = json.loads(cuad_path.read_text(encoding="utf-8"))
    documents = raw["data"][:limit] if limit else raw["data"]
    tool = RAGTool({"chunk_size": 800, "chunk_overlap": 120, "semantic": False,
                    "chunk_strategy": strategy, "search_unit": search_unit, "b": b})
    if mode == "question-only":
        tool._match_template_question = lambda query: None  # 消融：不做类别扩展
    stats = defaultdict(lambda: {"contracts": 0, "spans": 0,
                                 "hit": {1: 0, 3: 0, 5: 0, 10: 0},
                                 "exact": {1: 0, 3: 0, 5: 0, 10: 0},
                                 "contract_hit": 0})
    started = time.time()
    for doc in documents:
        title = doc["title"]
        context = doc["paragraphs"][0]["context"]
        qas = doc["paragraphs"][0].get("qas", [])
        prepared = tool.prepare_text(title, context)
        if prepared["status"] != "SUCCESS":
            continue
        # 冻结文本可能因归一化变化，gold 偏移以冻结文本为准重新校验
        frozen = tool.context(title)
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
            any_hit = False
            for k in (1, 3, 5, 10):
                top = chunks[:k]
                intervals = [(c["start"], c["end"]) for c in top]
                union = "\n".join(c["text"] for c in top)
                for start, end, text in frozen_spans:
                    if covered_chars(start, end, intervals) / (end - start) >= threshold:
                        entry["hit"][k] += 1
                        any_hit = True
                    if text in union:
                        entry["exact"][k] += 1
            entry["contract_hit"] += int(any_hit)
    elapsed = time.time() - started

    rows = []
    for category, entry in sorted(stats.items()):
        n = entry["spans"]
        rows.append({
            "category": category,
            "contracts": entry["contracts"],
            "gold_spans": n,
            "recall@1": round(entry["hit"][1] / n, 4) if n else None,
            "recall@3": round(entry["hit"][3] / n, 4) if n else None,
            "recall@5": round(entry["hit"][5] / n, 4) if n else None,
            "exact@5": round(entry["exact"][5] / n, 4) if n else None,
            "recall@10": round(entry["hit"][10] / n, 4) if n else None,
            "contract@5": round(entry["contract_hit"] / entry["contracts"], 4) if entry["contracts"] else None,
        })
    total_spans = sum(r["gold_spans"] for r in rows)
    micro = {
        "recall@1": round(sum(r["recall@1"] * r["gold_spans"] for r in rows) / total_spans, 4),
        "recall@3": round(sum(r["recall@3"] * r["gold_spans"] for r in rows) / total_spans, 4),
        "recall@5": round(sum(r["recall@5"] * r["gold_spans"] for r in rows) / total_spans, 4),
        "exact@5": round(sum(r["exact@5"] * r["gold_spans"] for r in rows) / total_spans, 4),
        "recall@10": round(sum(r["recall@10"] * r["gold_spans"] for r in rows) / total_spans, 4),
    }
    macro = {
        "recall@5": round(sum(r["recall@5"] for r in rows) / len(rows), 4),
        "exact@5": round(sum(r["exact@5"] for r in rows) / len(rows), 4),
    }
    summary = {
        "config": {"chunk_size": 800, "chunk_overlap": 120, "top_k": top_k,
                   "threshold": threshold, "query_mode": mode, "chunk_strategy": strategy,
                   "search_unit": search_unit},
        "contracts": len(documents),
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
    parser.add_argument("--cuad", type=Path, default=DEFAULT_CUAD,
                        help="CUADv1.json 路径；默认读取仓库 data/cuad/source/CUADv1.json")
    parser.add_argument("--out", type=Path, default=ROOT / "results/rag_tool_eval.json")
    args = parser.parse_args(argv)
    if not args.cuad.is_file():
        parser.error(f"找不到 CUAD 数据文件：{args.cuad}；请用 --cuad 指定 CUADv1.json")

    results = {}
    for mode in ("as-agent", "with-category", "question-only", "vocab-only", "reworded"):
        summary = evaluate(args.limit, args.top_k, args.threshold, mode,
                           args.chunk_strategy, args.search_unit, args.b, args.cuad)
        label = summary["config"]["query_mode"]
        results[label] = summary
        print(f"{label:16s} span R@1={summary['micro']['recall@1']:.3f} "
              f"R@5={summary['micro']['recall@5']:.3f} exact@5={summary['micro']['exact@5']:.3f} "
              f"macro R@5={summary['macro']['recall@5']:.3f} ({summary['elapsed_seconds']}s)")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    best = results["with-category"]
    print(f"\n{'category':38s} {'spans':>6s} {'R@1':>6s} {'R@5':>6s} {'exact@5':>8s}")
    for row in best["categories"]:
        print(f"{row['category']:38s} {row['gold_spans']:6d} {row['recall@1']:6.3f} "
              f"{row['recall@5']:6.3f} {row['exact@5']:8.3f}")
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
