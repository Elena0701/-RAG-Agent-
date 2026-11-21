import json
import unittest
from unittest.mock import Mock

from agents.contract_review_agent import ContractReviewAgent
from agents.verification_adapter import VerificationAdapter
from tools.rules import RuleTool


def no_messages():
    payload = {"category": "Insurance", "proposed_answer": "No", "quotes": [],
               "context": "Fictional agreement.", "category_criteria": "An insurance obligation."}
    return [{"role": "system", "content": "Previous prompt"},
            {"role": "user", "content": json.dumps(payload)}]


def no_response(status="SUPPORTED"):
    return {"evidence_checks": [], "overall_support": {
        "status": status, "reason": "fixture", "evidence_indices": [],
    }}


class VerificationAdapterTests(unittest.TestCase):
    def test_uncited_no_schema_and_fenced_json(self):
        client = Mock(return_value="```json\n" + json.dumps(no_response()) + "\n```")
        adapter = VerificationAdapter(client)
        self.assertEqual(adapter(no_messages())["overall_support"]["status"], "SUPPORTED")
        prompt = client.call_args.args[0][0]["content"]
        self.assertIn("Both arrays MUST be empty", prompt)
        self.assertNotIn("Previous prompt", prompt)
        self.assertEqual(adapter.request_count, 1)

    def test_invalid_indices_require_fresh_response(self):
        bad = no_response()
        bad["overall_support"]["evidence_indices"] = [0]
        client = Mock(side_effect=[bad, no_response("INSUFFICIENT")])
        adapter = VerificationAdapter(client)
        self.assertEqual(adapter(no_messages())["overall_support"]["status"], "INSUFFICIENT")
        self.assertEqual(adapter.request_count, 2)

    def test_invalid_replies_never_become_supported(self):
        adapter = VerificationAdapter(Mock(return_value={"wrong": "schema"}))
        with self.assertRaises(ValueError):
            adapter(no_messages())
        self.assertEqual(adapter.request_count, 2)
        self.assertIn("REVIEW_SCHEMA_INVALID", adapter.last_error)

    def test_cited_answer_still_requires_supporting_indices(self):
        messages = no_messages()
        payload = json.loads(messages[-1]["content"])
        payload.update(proposed_answer="Yes", quotes=[{"answer_index": 0, "text": "insurance", "answer_start": 0}])
        messages[-1]["content"] = json.dumps(payload)
        response = no_response()
        response["evidence_checks"] = [{"answer_index": 0, "support_status": "SUPPORTED", "reason": "fixture"}]
        adapter = VerificationAdapter(Mock(return_value=response))
        with self.assertRaises(ValueError):
            adapter(messages)

    def test_q7_rejects_ordinary_termination_quote(self):
        agent = ContractReviewAgent(None, RuleTool(), None, model="offline")
        task = agent.create_tasks({"document_id": "doc"}, ["Q7"])[0]
        texts = [
            ("Either party may terminate without cause on 90 days notice.", "INCOMPLETE"),
            ("This agreement renews unless 90 days notice of nonrenewal is given.", "COMPLETED"),
        ]
        for text, expected in texts:
            agent._call_llm_json = Mock(return_value={
                "category_answer": "90 days", "uncertain": False,
                "evidence": [{"chunk_id": "C0", "quote": text}],
            })
            result = agent.extract(task, [{"chunk_id": "C0", "text": text, "start": 0}], {})
            self.assertEqual(result["processing_status"], expected)

    def test_date_format_is_prompt_guidance_only(self):
        agent = ContractReviewAgent(None, RuleTool(), None, model="offline")
        text = "The Agreement expires on October 24, 2010."
        chunks = [{"chunk_id": "C0", "start": 0, "text": text}]
        for task in agent.create_tasks({"document_id": "doc"}, ["Q3", "Q4", "Q5"]):
            for answer in ("10/24/10", "2010-10-24", "October 24, 2010"):
                agent._call_llm_json = Mock(return_value={
                    "category_answer": answer, "uncertain": False,
                    "evidence": [{"chunk_id": "C0", "quote": text}],
                })
                result = agent.extract(task, chunks, {})
                self.assertEqual(result["processing_status"], "COMPLETED")
                self.assertEqual(result["category_answer"], answer)

    def test_unknown_policy_escalates_without_retrieval_retry(self):
        agent = ContractReviewAgent(None, RuleTool(), None, model="offline", max_retries=2)
        extraction = {"document_id": "doc", "question_id": "Q39", "category": "Insurance",
                      "category_answer": "No", "predicted_answers": [], "processing_status": "COMPLETED"}
        verification = {"evidence_checks": [], "verification_status": "PASSED", "coverage_status": "SUFFICIENT"}
        review = agent.review_rules(extraction, verification)
        self.assertTrue(any(i["code"] == "POLICY_INCOMPLETE" for i in review["issues"]))
        result = {**extraction, **verification, "rule_review": review,
                  "review_results": review["review_results"], "retry_count": 0}
        self.assertEqual(agent.decide_next_action(result), "ESCALATE")

    def test_simple_jurisdiction_matches_rule(self):
        agent = ContractReviewAgent(None, RuleTool(), None, model="offline")
        extraction = {"document_id": "doc", "question_id": "Q8", "category": "Governing Law",
                      "category_answer": "State of Israel", "predicted_answers": [
                          {"text": "governed by the domestic laws of the State of Israel", "answer_start": 0}],
                      "processing_status": "COMPLETED"}
        verification = {"evidence_checks": [{"answer_index": 0, "position_valid": True, "support_status": "SUPPORTED"}],
                        "verification_status": "PASSED", "coverage_status": "NOT_APPLICABLE"}
        self.assertEqual(agent.review_rules(extraction, verification)["review_results"][0]["status"], "TRIGGERED")


if __name__ == "__main__":
    unittest.main()
