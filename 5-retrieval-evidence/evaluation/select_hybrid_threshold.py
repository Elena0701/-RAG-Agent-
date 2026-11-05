"""Select the hybrid dense-admission threshold on CUAD train only.

This script deliberately never reads the test split.  After selecting a value,
run ``evaluate_rag_tool.py --cuad .../test.json`` once for the final report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from evaluate_rag_tool import DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_REVISION, evaluate
except ModuleNotFoundError:  # ``python -m evaluation.select_hybrid_threshold``
    from .evaluate_rag_tool import DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_REVISION, evaluate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAIN = ROOT.parent / "data" / "cuad" / "source" / "train_separate_questions.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=DEFAULT_TRAIN)
    parser.add_argument("--thresholds", type=float, nargs="+",
                        default=[0.45, 0.55, 0.65, 0.75])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--embedding-revision", default=DEFAULT_EMBEDDING_REVISION)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results/hybrid_threshold_train.json")
    args = parser.parse_args(argv)
    if not args.train.is_file():
        parser.error(f"train split not found: {args.train}")
    if not args.thresholds:
        parser.error("at least one threshold is required")

    candidates = []
    for value in args.thresholds:
        summary = evaluate(
            args.limit, args.top_k, 0.8, "as-agent", strategy="clause",
            retrieval_mode="embedding", embedding_model=args.embedding_model,
            embedding_revision=args.embedding_revision, hybrid_enabled=True,
            hybrid_dense_admission_threshold=value, cuad_path=args.train,
            ranking_policy='protected',
        )
        candidates.append({"threshold": value, "summary": summary})
        print(f"threshold={value:.2f} R@5={summary['micro']['recall@5']:.4f} "
              f"exact@5={summary['micro']['exact@5']:.4f} "
              f"macro_R@5={summary['macro']['recall@5']:.4f}")

    # The selection rule is declared before looking at test: prioritize span
    # recall, then exact recall, then macro recall.  On a tie prefer the higher
    # (more conservative) admission threshold.
    selected = max(
        candidates,
        key=lambda item: (
            item["summary"]["micro"]["recall@5"],
            item["summary"]["micro"]["exact@5"],
            item["summary"]["macro"]["recall@5"],
            item["threshold"],
        ),
    )
    output = {
        "selection_split": "train_separate_questions",
        "selection_rule": "max micro recall@5, then exact@5, macro recall@5, higher threshold",
        "selected_threshold": selected["threshold"],
        "candidates": candidates,
        "test_split_used_for_selection": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"selected={selected['threshold']:.2f}; written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
