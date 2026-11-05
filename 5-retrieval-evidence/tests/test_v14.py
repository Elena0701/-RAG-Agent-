"""Failure regressions and compatibility checks for ranking and evidence safety."""
import inspect
import unittest
from unittest.mock import patch
from tools.rag_tool import RAGTool, CATEGORY_NAMES
from rag_core.ranking import select_candidates
from tests.test_rag_tool import FakeEmbedder, CONTRACT, model_supported


class RevisionTests(unittest.TestCase):
    def tool(self, **config):
        tool = RAGTool({'retrieval_mode': 'bm25', 'semantic': False, **config})
        tool.prepare_text('doc', CONTRACT)
        return tool

    def test_signatures_and_categories_preserved(self):
        self.assertEqual(list(inspect.signature(RAGTool.prepare).parameters), ['self','document_id','file_path'])
        self.assertEqual(list(inspect.signature(RAGTool.retrieve).parameters), ['self','document_id','query','top_k','category'])
        self.assertEqual(list(inspect.signature(RAGTool.verify).parameters),
                         ['self','document_id','category','category_answer','predicted_answers','retrieval_history','question'])
        self.assertEqual(len(CATEGORY_NAMES), 11)

    def test_dense_query_does_not_receive_keyword_bag(self):
        tool = self.tool(retrieval_mode='embedding', embedder=FakeEmbedder(), hybrid_enabled=False)
        query = 'Who are the contracting parties?'
        result = tool.retrieve('doc', query)
        self.assertEqual(result['effective_query'], query)
        self.assertNotEqual(result['lexical_query'], query)

    def test_failed_replacement_invalidates_old_document(self):
        tool = self.tool()
        self.assertEqual(tool.prepare('doc', '/nonexistent/contract.txt')['status'], 'FAILED')
        self.assertIsNone(tool.context('doc'))
        self.assertEqual(tool.retrieve('doc', 'renewal')['status'], 'FAILED')
        tool.prepare_text('doc', CONTRACT)
        tool.prepare_text('doc', '')
        self.assertIsNone(tool.context('doc'))

    def test_unreturned_chunk_ids_do_not_count_as_coverage(self):
        tool = self.tool()
        ids = [f"C{c['start']}" for c in tool._indexes['doc']['chunks']]
        result = tool.verify('doc', 'Renewal Term', 'No', [],
                             retrieval_history=[{'retrieved_chunk_ids': ids}])
        self.assertEqual(result['coverage_status'], 'INSUFFICIENT')

    def test_no_cannot_pass_even_when_positive_clause_was_retrieved(self):
        tool = self.tool()
        result = tool.retrieve('doc', 'renewal', 50)
        checked = tool.verify('doc', 'Renewal Term', 'No', [],
                              retrieval_history=[{'retrieved_chunk_ids': [c['chunk_id'] for c in result['text']]}])
        self.assertEqual(checked['coverage_status'], 'SUFFICIENT')
        self.assertEqual(checked['verification_status'], 'UNCERTAIN')

    def test_long_context_is_not_silently_truncated_or_sent(self):
        calls = []
        tool = self.tool(model_call=lambda m: calls.append(m), semantic_context_max_chars=50)
        result = tool.verify('doc', 'Document Name', 'SOFTWARE SUBSCRIPTION AGREEMENT',
                             [{'text': CONTRACT[:31], 'answer_start': 0}])
        self.assertEqual(result['verification_status'], 'UNCERTAIN')
        self.assertEqual(result['diagnostic_codes'], ['SEMANTIC_CONTEXT_TOO_LARGE'])
        self.assertFalse(calls)

    def test_structure_returns_original_chunk_with_same_shape(self):
        tool = self.tool(retrieval_mode='embedding', embedder=FakeEmbedder())
        result = tool.retrieve('doc', 'What is the name of this agreement?', 3)
        self.assertEqual(result['text'][0]['start'], 0)
        for item in result['text']:
            self.assertEqual(CONTRACT[item['start']:item['end']], item['text'])
        self.assertLessEqual(len(result['text']), 3)

    def test_nonstructural_category_is_not_forced_to_opening(self):
        chunks = [{'start':0,'end':10,'text':'Heading...'}, {'start':100,'end':110,'text':'Insurance.'}]
        dense = [{**chunks[1], 'score':.8}]
        sparse = [{**chunks[1], 'score':5.0}]
        result = select_candidates(dense, sparse, chunks, 'Insurance', 1, policy='structured_protected')
        self.assertEqual(result[0]['start'], 100)

    def test_supported_negative_quote_can_still_pass(self):
        tool = self.tool(model_call=model_supported)
        quote = 'No party is granted audit or inspection rights.'
        tool.prepare_text('doc', quote)
        retrieved = tool.retrieve('doc', 'audit')
        checked = tool.verify('doc', 'Audit Rights', 'No', [{'text':quote,'answer_start':0}],
                              retrieval_history=[{'retrieved_chunk_ids':[c['chunk_id'] for c in retrieved['text']]}])
        self.assertEqual(checked['verification_status'], 'PASSED')

    def test_partial_parse_prevents_negative_pass(self):
        tool = self.tool(model_call=model_supported)
        quote = 'No party is granted audit or inspection rights.'
        tool.prepare_text('doc', quote, warnings=['pages_without_extractable_text:2'])
        retrieved = tool.retrieve('doc', 'audit')
        checked = tool.verify('doc','Audit Rights','No',[{'text':quote,'answer_start':0}],
                              retrieval_history=[{'retrieved_chunk_ids':[c['chunk_id'] for c in retrieved['text']]}])
        self.assertEqual(checked['verification_status'], 'UNCERTAIN')
