import unittest

from evaluation.run_evaluation import aggregate, normalize, score_records


class EvaluationTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize("1/2/20", "Agreement Date"),
                         normalize("January 2, 2020", "Agreement Date"))
        self.assertEqual(normalize("December 3rd, 2018", "Agreement Date"),
                         normalize("12/3/18", "Agreement Date"))
        self.assertEqual(normalize("successive 1 year", "Renewal Term"),
                         normalize("12 months", "Renewal Term"))
        self.assertNotEqual(normalize("at least 90 days", "Notice Period To Terminate Renewal"),
                            normalize("90 days", "Notice Period To Terminate Renewal"))

    def test_unknown_is_abstention_and_reduces_recall(self):
        records = []
        for gold, prediction in [("Yes", "Yes"), ("Yes", None), ("No", "Yes"), ("No", "No"), ("No", None)]:
            records.append({
                "question_id": "Q39", "category": "Insurance", "track": "verified",
                "gold": gold, "prediction": prediction, "gold_available": True,
                "answer_available": prediction is not None, "exact_match": int(gold == prediction),
                "answer_token_f1": float(gold == prediction), "evidence_token_set_f1": None,
            })
        row = next(r for r in aggregate(records) if r["category"] == "Insurance" and r["track"] == "verified")
        self.assertEqual((row["tp"], row["tn"], row["fp"], row["fn"]), (1, 1, 1, 0))
        self.assertEqual((row["abstain_yes"], row["abstain_no"]), (1, 1))
        self.assertEqual(row["yes_precision"], 0.5)
        self.assertEqual(row["yes_recall"], 0.5)
        self.assertEqual(row["yes_f1"], 0.5)
        self.assertEqual(row["exact_match"], 0.4)

    def test_manual_review_does_not_erase_verified_fact(self):
        categories = [
            "Document Name", "Parties", "Agreement Date", "Effective Date", "Expiration Date",
            "Renewal Term", "Notice Period To Terminate Renewal", "Governing Law",
            "Termination For Convenience", "Audit Rights", "Insurance",
        ]
        sample = {"filename": "fixture", "truth": {c: {"answer": "", "quotes": []} for c in categories}}
        sample["truth"]["Insurance"]["answer"] = "No"
        report = {"checks": [{
            "category": "Insurance", "category_answer": "No", "processing_status": "COMPLETED",
            "verification_status": "PASSED", "next_action": "ESCALATE", "predicted_answers": [],
        }]}
        records = score_records([sample], {"fixture": report})
        rows = [r for r in records if r["category"] == "Insurance"]
        self.assertTrue(all(r["exact_match"] == 1 for r in rows))
        self.assertTrue(all(not r["gold_available"] for r in records if r["category"] == "Agreement Date"))
        report["checks"][0]["verification_status"] = "UNCERTAIN"
        records = score_records([sample], {"fixture": report})
        verified = next(r for r in records if r["category"] == "Insurance" and r["track"] == "verified")
        self.assertIsNone(verified["prediction"])
        self.assertEqual(verified["exact_match"], 0)


if __name__ == "__main__":
    unittest.main()
