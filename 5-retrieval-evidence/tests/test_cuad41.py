"""Regression checks for category coverage and the public retrieve/verify path."""
import json
import unittest

from rag_core.coverage import ANCHORS
from rag_core.semantic_review import CATEGORY_CRITERIA
from tools.rag_tool import CATEGORY_NAMES, TEMPLATE_QUESTIONS, RAGTool
from tests.test_rag_tool import model_supported


class CompleteCatalogTest(unittest.TestCase):
    def test_each_template_reaches_retrieval_and_semantic_review(self):
        seen = {}

        def capture(messages):
            payload = json.loads(messages[-1]["content"])
            seen[payload["category"]] = payload["category_criteria"]
            return model_supported(messages)

        tool = RAGTool({"retrieval_mode": "bm25", "model_call": capture})
        # The stub checks dispatch and the schema, not the quality of a real model.
        contract = "This agreement records the obligations of each party."
        tool.prepare_text("routing", contract)
        expected = set(CATEGORY_NAMES)
        self.assertEqual(len(expected), 41)
        for mapping in (TEMPLATE_QUESTIONS, CATEGORY_CRITERIA, ANCHORS):
            self.assertEqual(set(mapping), expected)
        for category, question in TEMPLATE_QUESTIONS.items():
            with self.subTest(category=category):
                found = tool.retrieve("routing", question)
                self.assertEqual(found["query_source"], "template")
                self.assertEqual(found["resolved_category"], category)
                self.assertTrue(found["expanded"])
                reviewed = tool.verify("routing", category, "example",
                                       [{"text": contract, "answer_start": 0}])
                self.assertEqual(seen[category], CATEGORY_CRITERIA[category])
                self.assertEqual(reviewed["verification_status"], "PASSED")

    def test_escrow_evidence_is_located_and_empty_no_stays_uncertain(self):
        tool = RAGTool({"retrieval_mode": "bm25", "model_call": model_supported,
                        "chunk_size": 100, "chunk_overlap": 10})
        provision = "The supplier shall deposit the source code with an escrow agent."
        contract = ("1. Fees. Invoices shall be paid within thirty days.\n\n"
                    "2. Escrow. " + provision)
        tool.prepare_text("escrow", contract)
        found = tool.retrieve("escrow", "What is held by a third party?", 1,
                              category="Source Code Escrow")
        hit, = found["text"]
        self.assertIn(provision, hit["text"])
        self.assertEqual(hit["text"], contract[hit["start"]:hit["end"]])
        history = [{"retrieved_chunk_ids": [hit["chunk_id"]]}]
        checked = tool.verify("escrow", "Source Code Escrow", "Yes",
                              [{"text": provision, "answer_start": contract.index(provision)}])
        self.assertTrue(checked["evidence_checks"][0]["position_valid"])
        self.assertEqual(checked["verification_status"], "PASSED")
        no = tool.verify("escrow", "Source Code Escrow", "no", [], retrieval_history=history)
        self.assertEqual(no["category_answer"], "No")
        self.assertEqual(no["coverage_status"], "SUFFICIENT")
        self.assertEqual(no["verification_status"], "UNCERTAIN")

    def test_generic_contract_mention_does_not_cover_new_topic(self):
        tool = RAGTool({"retrieval_mode": "bm25", "semantic": False})
        tool.prepare_text("generic", "Agreement between two parties.")
        hit, = tool.retrieve("generic", "agreement")["text"]
        reviewed = tool.verify("generic", "Cap On Liability", "No", [],
                               retrieval_history=[{"retrieved_chunk_ids": [hit["chunk_id"]]}])
        self.assertEqual(reviewed["coverage_status"], "INSUFFICIENT")
        self.assertEqual(reviewed["coverage_detail"]["basis"], "NO_LEXICAL_ANCHOR")
        self.assertEqual(reviewed["verification_status"], "UNCERTAIN")
