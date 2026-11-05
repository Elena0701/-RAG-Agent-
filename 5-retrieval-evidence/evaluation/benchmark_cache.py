"""Measure cold versus warm document-vector preparation on one CUAD contract."""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

try:
    from evaluate_rag_tool import DEFAULT_CUAD
except ModuleNotFoundError:  # ``python -m evaluation.benchmark_cache``
    from .evaluate_rag_tool import DEFAULT_CUAD

from tools.rag_tool import RAGTool

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cuad", type=Path, default=DEFAULT_CUAD)
    parser.add_argument("--out", type=Path, default=ROOT / "results/cache_benchmark.json")
    args = parser.parse_args(argv)
    payload = json.loads(args.cuad.read_text(encoding="utf-8"))
    document = payload["data"][0]
    context = document["paragraphs"][0]["context"]

    with tempfile.TemporaryDirectory() as cache_dir:
        tool = RAGTool({"semantic": False, "embedding_local_files_only": True,
                        "embedding_cache_dir": cache_dir})
        load_start = time.perf_counter()
        tool._embedding_backend()
        model_load_seconds = time.perf_counter() - load_start
        started = time.perf_counter()
        cold = tool.prepare_text("CACHE-COLD", context)
        cold_seconds = time.perf_counter() - started
        started = time.perf_counter()
        warm = tool.prepare_text("CACHE-WARM", context)
        warm_seconds = time.perf_counter() - started

    result = {
        "contract": document["title"],
        "chars": len(context),
        "chunks": cold.get("chunk_count"),
        "model_load_seconds": round(model_load_seconds, 4),
        "cold_seconds": round(cold_seconds, 4),
        "warm_seconds": round(warm_seconds, 4),
        "speedup": round(cold_seconds / warm_seconds, 2) if warm_seconds else None,
        "cold_cache_hit": cold.get("embedding_cache_hit"),
        "warm_cache_hit": warm.get("embedding_cache_hit"),
        "note": "Same process and model instance; only document-vector cache state changes.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
