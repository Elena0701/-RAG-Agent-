import json
import unittest
from unittest.mock import Mock

from agents.contract_review_agent import ContractReviewAgent
from tools.rag_tool import CATEGORY_NAMES, RAGTool, TEMPLATE_QUESTIONS
from tools.rag_tool.rag_core.coverage import ANCHORS
from tools.rag_tool.rag_core.semantic_review import CATEGORY_CRITERIA


class InstalledRAGTests(unittest.TestCase):
    def test_zero_anchors_requires_full_context_semantic_approval(self):
        tool = RAGTool({"retrieval_mode": "bm25", "semantic": False})
        text = "This fictional agreement specifies ordinary payment obligations."
        tool.prepare_text("zero", text)
        for verdict, expected in [("SUPPORTED", "PASSED"), ("UNSUPPORTED", "FAILED"),
                                  ("INSUFFICIENT", "UNCERTAIN")]:
            model = Mock(return_value={
                "evidence_checks": [], "overall_support": {
                    "status": verdict, "reason": "fixture", "evidence_indices": []},
            })
            tool.model_call = model
            result = tool.verify("zero", "Rofr/Rofo/Rofn", "No", [])
            self.assertEqual(result["verification_status"], expected)
            payload = json.loads(model.call_args.args[0][-1]["content"])
            self.assertEqual(payload["context"], text)
            if expected == "PASSED":
                self.assertEqual(result["coverage_status"], "SUFFICIENT")
                self.assertEqual(result["coverage_detail"]["basis"], "FULL_CONTEXT_SEMANTIC_REVIEW")
                self.assertEqual(result["coverage_detail"]["reviewed_chars"], len(text))
            else:
                self.assertEqual(result["coverage_status"], "INSUFFICIENT")
        tool.model_call = Mock(side_effect=RuntimeError("fixture"))
        self.assertEqual(tool.verify("zero", "Rofr/Rofo/Rofn", "No", [])["verification_status"], "UNCERTAIN")
        tool.model_call = None
        self.assertEqual(tool.verify("zero", "Rofr/Rofo/Rofn", "No", [])["model_calls"], 0)

    def test_zero_anchor_fallback_respects_parse_warnings_and_context_budget(self):
        tool = RAGTool({"retrieval_mode": "bm25", "semantic": False})
        tool.prepare_text("zero", "Ordinary payment obligations.", warnings=["partial parse"])
        tool.model_call = Mock()
        result = tool.verify("zero", "Rofr/Rofo/Rofn", "No", [])
        self.assertEqual(result["coverage_status"], "INSUFFICIENT")
        tool.model_call.assert_not_called()
        tool.prepare_text("zero", "Ordinary payment obligations.")
        tool.config["semantic_context_max_chars"] = 5
        result = tool.verify("zero", "Rofr/Rofo/Rofn", "No", [])
        self.assertIn("SEMANTIC_CONTEXT_TOO_LARGE", result["diagnostic_codes"])
        tool.model_call.assert_not_called()

    def test_uncovered_existing_anchors_still_block_uncited_no(self):
        tool = RAGTool({"retrieval_mode": "bm25", "semantic": False})
        tool.prepare_text("anchor", "A first refusal provision exists.")
        tool.model_call = Mock()
        self.assertEqual(tool.verify("anchor", "Rofr/Rofo/Rofn", "No", [])["coverage_status"], "INSUFFICIENT")
        tool.model_call.assert_not_called()

    def test_all_categories_reach_retrieval_and_verification(self):
        seen = []

        def review(messages):
            payload = json.loads(messages[-1]["content"])
            seen.append(payload["category"])
            return {"evidence_checks": [
                {"answer_index": 0, "support_status": "SUPPORTED", "reason": "fixture"}],
                "overall_support": {"status": "SUPPORTED", "reason": "fixture", "evidence_indices": [0]}}

        expected = {category for _, category, _ in ContractReviewAgent.CATEGORIES}
        self.assertEqual(len(expected), 41)
        for actual in (set(CATEGORY_NAMES), set(TEMPLATE_QUESTIONS), set(CATEGORY_CRITERIA), set(ANCHORS)):
            self.assertEqual(actual, expected)
        tool = RAGTool({"retrieval_mode": "bm25", "model_call": review})
        text = "This fictional agreement records contractual rights and obligations."
        self.assertEqual(tool.prepare_text("test", text)["status"], "SUCCESS")
        for qid, category, query in ContractReviewAgent.CATEGORIES:
            with self.subTest(qid=qid):
                found = tool.retrieve("test", query, category=category)
                self.assertEqual(found["resolved_category"], category)
                for chunk in found["text"]:
                    self.assertEqual(text[chunk["start"]:chunk["end"]], chunk["text"])
                answer = "Yes" if category in ContractReviewAgent.BOOLEAN_CATEGORIES else "fixture"
                checked = tool.verify("test", category, answer, [{"text": text, "answer_start": 0}])
                self.assertEqual(checked["verification_status"], "PASSED")
        self.assertEqual(set(seen), expected)

    def test_full_context_negative_and_irrelevant_quote_regressions(self):
        tool = RAGTool({"retrieval_mode": "bm25", "semantic": False})
        tool.prepare_text("test", "Insurance is not required. Unrelated sentence.")
        found = tool.retrieve("test", "insurance", category="Insurance", top_k=10)
        history = [{"retrieved_chunk_ids": [c["chunk_id"] for c in found["text"]]}]
        tool.model_call = lambda _: {
            "evidence_checks": [],
            "overall_support": {"status": "SUPPORTED", "reason": "fixture", "evidence_indices": []},
        }
        result = tool.verify("test", "Insurance", "No", [], retrieval_history=history)
        self.assertEqual(result["verification_status"], "PASSED")
        self.assertEqual(result["verification_basis"], "FULL_CONTEXT_ABSENCE")
        tool.model_call = lambda _: {
            "evidence_checks": [
                {"answer_index": 0, "support_status": "SUPPORTED", "reason": "fixture"},
                {"answer_index": 1, "support_status": "UNSUPPORTED", "reason": "unrelated"},
            ],
            "overall_support": {"status": "SUPPORTED", "reason": "fixture", "evidence_indices": [0]},
        }
        quotes = [{"text": "Insurance is not required.", "answer_start": 0},
                  {"text": "Unrelated sentence.", "answer_start": 27}]
        self.assertEqual(tool.verify("test", "Insurance", "No", quotes,
                                     retrieval_history=history)["verification_status"], "PASSED")
        quotes[0]["answer_start"] = 1
        self.assertEqual(tool.verify("test", "Insurance", "No", quotes,
                                     retrieval_history=history)["diagnostic_codes"], ["POSITION_MISMATCH"])


if __name__ == "__main__":
    unittest.main()
