"""Opt-in integration test using the real pinned embedding model.

Run with ``RUN_MODEL_TESTS=1 HF_HUB_OFFLINE=1`` after the model is cached.
It is skipped during fast unit-test runs and never calls DeepSeek.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.rag_tool import RAGTool  # noqa: E402


@unittest.skipUnless(os.getenv("RUN_MODEL_TESTS") == "1", "set RUN_MODEL_TESTS=1")
class RealEmbeddingIntegrationTest(unittest.TestCase):
    def test_pinned_model_retrieves_a_paraphrased_termination_clause(self):
        contract = (
            "1. Fees. Customer shall pay each invoice within thirty days.\n\n"
            "2. Exit Right. Either party may end this arrangement at its sole discretion "
            "upon sixty days written notice.\n\n"
            "3. Insurance. Supplier shall maintain general liability coverage.\n"
        )
        tool = RAGTool({
            "semantic": False,
            "embedding_local_files_only": True,
            "embedding_cache_enabled": False,
            "hybrid_enabled": False,
            "chunk_strategy": "clause",
            "chunk_size": 160,
            "chunk_overlap": 20,
        })
        prepared = tool.prepare_text("MODEL-1", contract)
        self.assertEqual(prepared["status"], "SUCCESS", msg=prepared.get("reason"))
        result = tool.retrieve(
            "MODEL-1", "Can either side cancel even when nobody breached?", top_k=1,
            category="Termination For Convenience",
        )
        self.assertEqual(result["status"], "OK")
        self.assertIn("sole discretion", result["text"][0]["text"])
        hit = result["text"][0]
        self.assertEqual(tool.context("MODEL-1")[hit["start"]:hit["end"]], hit["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
