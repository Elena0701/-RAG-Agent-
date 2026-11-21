import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from agents.contract_review_agent import ContractReviewAgent
from agents.terminal_report import ICONS, MODE_LABELS, format_terminal_report
from tools.rules import RuleTool


TEXT = "A fictional agreement. Test evidence. This agreement renews unless 30 days notice is given."


class StubRAG:
    def __init__(self):
        self.categories = []

    def prepare(self, **kwargs):
        return {"status": "SUCCESS"}

    def retrieve(self, *, document_id, query, top_k, category):
        self.categories.append(category)
        return {"text": [{"chunk_id": "C0", "text": TEXT, "start": 0, "end": len(TEXT)}]}

    def verify(self, *, predicted_answers, **kwargs):
        return {
            "verification_status": "PASSED",
            "coverage_status": "SUFFICIENT" if kwargs["category_answer"] == "No" else "NOT_APPLICABLE",
            "evidence_checks": [
                {"answer_index": i, "position_valid": True,
                 "support_status": "UNSUPPORTED" if i == 0 else "SUPPORTED", "reason": "fixture"}
                for i in range(len(predicted_answers))
            ],
            "overall_support": {"status": "SUPPORTED", "reason": "fixture"},
        }


def make_agent(folder, *, negative=False):
    def complete(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        category = payload["category"]
        kind = payload["answer_type"]
        value = {"Renewal Term": "12 months", "Notice Period To Terminate Renewal": "30 days",
                 "Governing Law": "California", "Agreement Date": "01/01/20",
                 "Effective Date": "01/01/20", "Expiration Date": "01/01/21"}.get(category, "Fixture")
        if kind == "BOOLEAN":
            value = "No" if negative else "Yes"
        evidence = [] if value == "No" else [
            {"chunk_id": "C0", "quote": "A fictional agreement."},
            {"chunk_id": "C0", "quote": "This agreement renews unless 30 days notice is given."
             if category == "Notice Period To Terminate Renewal" else "Test evidence."},
        ]
        content = json.dumps({"category_answer": value, "evidence": evidence, "uncertain": False})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    return ContractReviewAgent(StubRAG(), RuleTool(), client, model="offline",
                               max_retries=0, output_dir=folder)


class FullCoverageTests(unittest.TestCase):
    def test_registry_and_order(self):
        agent = make_agent(".")
        self.assertEqual(len(agent.CATEGORIES), 41)
        self.assertEqual(len(agent.RULE_CATEGORIES), 36)
        self.assertEqual(len(agent.BOOLEAN_CATEGORIES), 33)
        self.assertEqual([name for _, name, _ in agent.CATEGORIES][9:13], [
            "Competitive Restriction Exception", "Non-Compete", "Exclusivity", "No-Solicit Of Customers",
        ])
        for qid, name, _ in agent.CATEGORIES[5:]:
            self.assertEqual(agent.rule_tool.registry[name]["cuad_index"], int(qid[1:]))
        self.assertEqual([t["question_id"] for t in agent.create_tasks(
            {"document_id": "doc"}, ["Q41", "Q10", "Q10"])], ["Q10", "Q41"])
        with self.assertRaises(ValueError):
            agent.create_tasks({"document_id": "doc"}, ["Q42"])

    def test_all_tasks_through_cli_and_transcript(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.txt"
            path.write_text(TEXT, encoding="utf-8")
            agent = make_agent(folder)

            def build(**kwargs):
                agent.progress = kwargs["progress"]
                return agent

            out, err = io.StringIO(), io.StringIO()
            with patch("main.build_agent", side_effect=build), patch("sys.argv", [
                "main.py", str(path), "--model", "offline",
            ]), redirect_stdout(out), redirect_stderr(err):
                main.main()
            summary = json.loads(out.getvalue())
            report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
            conversation = json.loads(Path(summary["conversation_path"]).read_text(encoding="utf-8"))
            self.assertEqual(len(report["checks"]), 41)
            self.assertEqual(len(agent.rag_tool.categories), 41)
            self.assertTrue(any("合同审查报告" in m["content"] for m in conversation["messages"]))
            for item in report["checks"]:
                self.assertEqual(item["processing_status"], "COMPLETED")
                if item["category"] in agent.RULE_CATEGORIES:
                    review = item["rule_review"]
                    self.assertEqual(review["fact_status"], "CONFIRMED")
                    for rule in review["review_results"] + review["context_review_notes"]:
                        self.assertEqual(rule["evidence_indices"], [1])
                    self.assertEqual(review["evidence_checks"][0]["support_status"], "UNSUPPORTED")
            context = report["checks"][9]
            self.assertEqual(context["category"], "Competitive Restriction Exception")
            self.assertTrue(context["rule_review"]["context_review_notes"])
            self.assertEqual(context["next_action"], "ESCALATE")
            self.assertIn("上下文复核意见", err.getvalue())
            self.assertIn("🤝 最惠待遇", err.getvalue())
            self.assertIn("审查模式：上下文复核", err.getvalue())
            self.assertIn("事实描述：", err.getvalue())

    def test_negative_answers_use_boolean_types_and_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.txt"
            path.write_text(TEXT, encoding="utf-8")
            agent = make_agent(folder, negative=True)
            report = agent.run(path)
            for check in report["checks"]:
                if check["category"] in agent.BOOLEAN_CATEGORIES:
                    self.assertEqual(check["category_answer"], "No")
                    self.assertEqual(check["rule_review"]["fact_status"], "CONFIRMED")
            warranty = report["checks"][37]
            self.assertEqual(warranty["category"], "Warranty Duration")
            self.assertEqual(warranty["category_answer"], "No")

    def test_rule_modes_and_incomplete_input(self):
        agent = make_agent(".")
        task = agent.create_tasks({"document_id": "doc"}, ["Q10"])[0]
        extraction = {**task, "category_answer": None, "predicted_answers": [], "processing_status": "INCOMPLETE"}
        verification = {"verification_status": "UNCERTAIN", "coverage_status": "INSUFFICIENT", "evidence_checks": []}
        review = agent.review_rules(extraction, verification)
        self.assertTrue(review["requires_manual_review"])
        self.assertEqual(agent.decide_next_action({
            **extraction, **verification, "rule_review": review, "review_results": [],
        }), "ESCALATE")
        self.assertTrue(agent.rule_manual_reason({"rule_review": review}))
        # 已核验事实在INFORMATION_ONLY或DISABLED模式下可以接收。
        extraction.update(category="License Grant", category_answer="Yes", processing_status="COMPLETED",
                          predicted_answers=[{"text": TEXT, "answer_start": 0}])
        verification.update(verification_status="PASSED", coverage_status="NOT_APPLICABLE",
                            evidence_checks=[{"answer_index": 0, "position_valid": True, "support_status": "SUPPORTED"}])
        for enabled in (True, False):
            agent.rule_tool.config["policies"]["License Grant"]["enabled"] = enabled
            review = agent.review_rules(extraction, verification)
            self.assertFalse(review["requires_manual_review"])
            self.assertEqual(agent.decide_next_action({
                **extraction, **verification, "rule_review": review, "review_results": review["review_results"],
            }), "ACCEPT")

    def test_historical_report_labels_use_category(self):
        report = {"status": "COMPLETED", "manual_review_items": [], "checks": [{
            "question_id": "Q11", "category": "Termination For Convenience", "category_answer": "Yes",
            "processing_status": "COMPLETED", "verification_status": "PASSED",
            "next_action": "ACCEPT", "predicted_answers": [], "review_results": [],
        }]}
        self.assertIn("👤 无因终止", format_terminal_report(report, "fixture.json"))

    def test_report_supports_all_categories_and_modes(self):
        self.assertEqual(set(ICONS), {name for _, name, _ in ContractReviewAgent.CATEGORIES})
        for mode in MODE_LABELS:
            check = {
                "question_id": "Q39", "category": "Insurance", "category_answer": "No",
                "processing_status": "COMPLETED", "verification_status": "UNCERTAIN",
                "next_action": "ESCALATE", "predicted_answers": [], "review_results": [],
                "rule_review": {"mode": mode, "clause_description": "fixture fact",
                                "rule_execution_status": "DISABLED"},
            }
            report = {"status": "NEEDS_MANUAL_REVIEW", "checks": [check], "manual_review_items": [check]}
            text = format_terminal_report(report, "fixture.json")
            self.assertIn("🛡️ 保险义务：候选 No", text)
            self.assertIn(f"审查模式：{MODE_LABELS[mode]}", text)
            self.assertIn("事实描述：fixture fact", text)
            self.assertNotIn("风险：", text)
            self.assertIn("Q39 保险义务", text)


if __name__ == "__main__":
    unittest.main()
