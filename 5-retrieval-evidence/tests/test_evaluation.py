"""Regression tests for the CUAD evaluation accounting."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.evaluate_rag_tool import evaluate, gold_spans  # noqa: E402


class StubRAGTool:
    def __init__(self, config):
        self._contexts = {}

    def prepare_text(self, document_id, text):
        self._contexts[document_id] = text
        return {"status": "SUCCESS"}

    def context(self, document_id):
        return self._contexts[document_id]

    def retrieve(self, document_id, query, top_k=5, category=None):
        context = self._contexts[document_id]
        gold_start = context.index("successive one year renewals")
        chunks = [
            {"start": 0, "end": 4, "text": context[0:4]},
            {"start": 5, "end": 9, "text": context[5:9]},
            {"start": 10, "end": 14, "text": context[10:14]},
            {"start": 15, "end": 19, "text": context[15:19]},
            {"start": gold_start, "end": len(context), "text": context[gold_start:]},
        ]
        return {"text": chunks[:top_k]}


class EvaluationAccountingTest(unittest.TestCase):
    def test_different_length_spans_at_same_position_are_preserved(self):
        context = 'Acme Corporation'
        qas = [{'id':'D__Parties', 'answers':[
            {'answer_start':0,'text':'Acme'}, {'answer_start':0,'text':context},
            {'answer_start':0,'text':'Acme'}]}]
        self.assertEqual(len(gold_spans(qas,'Parties',context)), 2)

    def test_repeated_text_at_wrong_position_is_not_exact_hit(self):
        gold = 'successive one year renewals'
        context = gold + ' ' + gold
        payload = {'data':[{'title':'D', 'paragraphs':[{'context':context,'qas':[
            {'id':'D__Renewal Term','answers':[{'text':gold,'answer_start':len(gold)+1}]}]}]}]}
        class WrongOccurrence(StubRAGTool):
            def retrieve(self, *args, **kwargs):
                return {'text':[{'start':0,'end':len(gold),'text':gold}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'test.json'
            path.write_text(json.dumps(payload))
            with patch('evaluation.evaluate_rag_tool.RAGTool', WrongOccurrence):
                result = evaluate(0,5,.8,'as-agent',retrieval_mode='bm25',cuad_path=path)
        self.assertEqual(result['micro']['exact@5'], 0)

    def test_prepare_failure_remains_in_denominator(self):
        gold = 'successive one year renewals'
        payload = {'data':[{'title':'D','paragraphs':[{'context':gold,'qas':[
            {'id':'D__Renewal Term','answers':[{'text':gold,'answer_start':0}]}]}]}]}
        class FailedTool(StubRAGTool):
            def prepare_text(self, document_id, text):
                self._contexts[document_id] = None
                return {'status':'FAILED','reason':'simulated failure'}
            def retrieve(self, *args, **kwargs):
                return {'text':[]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.json'
            path.write_text(json.dumps(payload))
            with patch('evaluation.evaluate_rag_tool.RAGTool',FailedTool):
                result=evaluate(0,5,.8,'as-agent',retrieval_mode='bm25',cuad_path=path)
        self.assertEqual(result['gold_spans'],1)
        self.assertEqual(result['micro']['recall@5'],0)
        self.assertEqual(len(result['prepare_failures']),1)

    def test_contract_hits_are_counted_per_k_and_unavailable_k_is_omitted(self):
        context = "zero one two three successive one year renewals"
        gold = "successive one year renewals"
        payload = {"data": [{
            "title": "D1",
            "paragraphs": [{"context": context, "qas": [{
                "id": "D1__Renewal Term",
                "answers": [{"text": gold, "answer_start": context.index(gold)}],
            }]}],
        }]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("evaluation.evaluate_rag_tool.RAGTool", StubRAGTool):
                summary = evaluate(0, 5, 0.8, "as-agent", retrieval_mode="bm25",
                                   cuad_path=path)
        row = summary["categories"][0]
        self.assertEqual(row["contract@1"], 0.0)
        self.assertEqual(row["contract@5"], 1.0)
        self.assertNotIn("recall@10", row)
        self.assertEqual(summary["config"]["reported_k"], [1, 3, 5])
        self.assertEqual(summary["dataset"]["split"], "test")

    def test_train_separate_question_suffix_is_recognised(self):
        context = "successive one year renewals"
        qas = [{"id": "D1__Renewal Term_0",
                "answers": [{"text": context, "answer_start": 0}]}]
        payload = {"data": [{"title": "D1", "paragraphs": [{
            "context": context, "qas": qas,
        }]}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "train_separate_questions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("evaluation.evaluate_rag_tool.RAGTool", StubRAGTool):
                summary = evaluate(0, 5, 0.8, "as-agent", retrieval_mode="bm25",
                                   cuad_path=path)
        self.assertEqual(summary["gold_spans"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
