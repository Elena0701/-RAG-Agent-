import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_full_coverage_agent import make_agent, TEXT
from tools.clause_definitions import CATEGORY_CRITERIA
from tools.rag_tool import RAGTool
from tools.rag_tool.rag_core.semantic_review import build_review_messages


class ReviewResilienceTests(unittest.TestCase):
    def test_extraction_and_verification_share_all_definitions(self):
        agent = make_agent(".")
        self.assertEqual(set(CATEGORY_CRITERIA), {c for _, c, _ in agent.CATEGORIES})
        original = agent.llm_client.chat.completions.create
        captured = []

        def capture(**kwargs):
            captured.append(json.loads(kwargs["messages"][1]["content"]))
            return original(**kwargs)

        agent.llm_client.chat.completions.create = capture
        for task in agent.create_tasks({"document_id": "doc"}):
            agent.extract(task, [{"chunk_id": "C0", "text": TEXT, "start": 0}], {})
            payload = json.loads(build_review_messages({
                "category": task["category"], "category_answer": "Yes",
                "context": TEXT, "predicted_answers": [],
            })[1]["content"])
            self.assertEqual(captured[-1]["category_criteria"], payload["category_criteria"])
        self.assertIn("General restrictions", CATEGORY_CRITERIA["Non-Transferable License"])

    def test_rule_exception_preserves_success_and_retries_only_rules(self):
        agent = make_agent(".")
        agent.max_retries = 1
        task = agent.create_tasks({"document_id": "doc"}, ["Q1"])[0]
        with patch.object(agent, "extract", wraps=agent.extract) as extract, \
                patch.object(agent, "verify", wraps=agent.verify) as verify, \
                patch.object(agent, "review_rules", side_effect=[RuntimeError("offline"), {}]):
            result = agent.review_task(task, {})
        self.assertEqual(result["next_action"], "ACCEPT")
        self.assertEqual(extract.call_count, 1)
        self.assertEqual(verify.call_count, 1)
        failed = result["attempt_history"][0]
        self.assertEqual(failed["processing_status"], "COMPLETED")
        self.assertEqual(failed["verification_status"], "PASSED")
        self.assertEqual(failed["category_answer"], "Fixture")
        self.assertEqual(failed["stage_error"]["stage"], "rules")

    def test_verifier_exception_preserves_extraction(self):
        agent = make_agent(".")
        task = agent.create_tasks({"document_id": "doc"}, ["Q1"])[0]
        with patch.object(agent, "verify", side_effect=RuntimeError("offline")):
            result = agent.review_task(task, {})
        self.assertEqual(result["category_answer"], "Fixture")
        self.assertTrue(result["predicted_answers"])
        self.assertEqual(result["processing_status"], "COMPLETED")
        self.assertEqual(result["next_action"], "ESCALATE")
        self.assertEqual(result["stage_error"]["stage"], "verification")

    def test_semantic_rejection_is_not_replaced_by_coverage_uncertainty(self):
        agent = make_agent(".")
        extraction = {"document_id": "doc", "category": "Insurance",
                      "category_answer": "No", "predicted_answers": []}
        for incoming, expected in [("FAILED", "FAILED"), ("PASSED", "UNCERTAIN")]:
            agent.rag_tool.verify = Mock(return_value={
                "verification_status": incoming, "coverage_status": "INSUFFICIENT",
                "evidence_checks": [], "reason": "fixture",
            })
            self.assertEqual(agent.verify(extraction, [])["verification_status"], expected)

    def test_targeted_chunks_are_real_and_count_towards_coverage(self):
        rag = RAGTool({"retrieval_mode": "bm25", "semantic": False})
        text = "Ordinary payment obligations. " * 120 + "A first refusal provision exists."
        rag.prepare_text("doc", text)
        before = rag._coverage("doc", rag._contexts["doc"], "Rofr/Rofo/Rofn", [])
        self.assertEqual(before["status"], "INSUFFICIENT")
        chunks = rag.retrieve_spans("doc", before["uncovered"])
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertEqual(text[chunk["start"]:chunk["end"]], chunk["text"])
        history = [{"retrieved_chunk_ids": [c["chunk_id"] for c in chunks]}]
        after = rag._coverage("doc", rag._contexts["doc"], "Rofr/Rofo/Rofn", history)
        self.assertEqual(after["status"], "SUFFICIENT")
        agent = make_agent(".")
        agent.rag_tool = rag
        task = agent.create_tasks({"document_id": "doc"}, ["Q17"])[0]
        task = agent.rewrite_query(task, {"coverage_detail": before})
        result = agent.retrieve(task)
        self.assertTrue(any("coverage_target" in c.get("retrieval_sources", []) for c in result["text"]))

    def test_resume_skips_completed_tasks_and_rejects_changed_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "contract.txt"
            path.write_text(TEXT, encoding="utf-8")
            agent = make_agent(folder)
            review = agent.review_task

            def interrupt(task, document):
                if task["question_id"] == "Q2":
                    raise KeyboardInterrupt()
                return review(task, document)

            with patch.object(agent, "review_task", side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    agent.run(path, question_ids=["Q1", "Q2"])
            checkpoint = agent.checkpoint_path
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["checks"]), 1)
            resumed = make_agent(folder)
            with patch.object(resumed, "review_task", wraps=resumed.review_task) as calls:
                report = resumed.run(path, question_ids=["Q1", "Q2"], resume=checkpoint)
            self.assertEqual([c.args[0]["question_id"] for c in calls.call_args_list], ["Q2"])
            self.assertEqual(report["document_id"], saved["document"]["document_id"])
            self.assertEqual(len(report["checks"]), 2)
            again = make_agent(folder)
            with patch.object(again, "review_task") as calls:
                again.run(path, question_ids=["Q1", "Q2"], resume=checkpoint)
                calls.assert_not_called()
            for changed in ("model", "policy", "tasks", "file"):
                other = make_agent(folder)
                ids = ["Q1", "Q2"]
                if changed == "model":
                    other.model = "different-model"
                elif changed == "policy":
                    other.rule_tool.config["policies"]["Insurance"]["applicable"] = True
                elif changed == "tasks":
                    ids = ["Q1"]
                else:
                    path.write_text(TEXT + " amended", encoding="utf-8")
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    other.run(path, question_ids=ids, resume=checkpoint)
