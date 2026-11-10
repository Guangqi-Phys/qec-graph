import unittest

from qecgraph.llm.extract import ExtractionError, make_proposal, validate_extraction
from qecgraph.llm.client import LLMResult


def result():
    return LLMResult(data={}, text='{}', model='model', usage={}, request_id='r',
                     attempts=1, cached=False, run_id='run', prompt_sha256='p' * 64)


def theorem():
    return {'items': [{'label': 'thm:a', 'statement': 'A statement.',
                       'source_refs': ['paper.tex:1-5'],
                       'hypotheses': [{'text': 'Assume q is odd.', 'kind': 'explicit',
                                       'source_refs': ['paper.tex:6-7'], 'confidence': 0.9}]}],
            'unresolved': []}


class ExtractionValidationTests(unittest.TestCase):
    def test_valid_theorem_proposal_is_marked_proposed_with_provenance(self):
        proposal = make_proposal('extract_theorems', theorem(), source_tree_hash='a' * 64,
                                 ai_result=result())
        self.assertEqual(proposal['review_status'], 'proposed')
        self.assertEqual(proposal['schema'], 'qecgraph.ai.proposal')
        self.assertEqual(proposal['provenance']['run_id'], 'run')
        self.assertEqual(proposal['items'][0]['label'], 'thm:a')

    def test_explicit_hypothesis_without_source_is_rejected(self):
        value = theorem()
        value['items'][0]['hypotheses'][0].pop('source_refs')
        with self.assertRaisesRegex(ExtractionError, 'lacks source_refs'):
            validate_extraction('extract_theorems', value)

    def test_duplicate_theorem_labels_and_bad_data_are_rejected(self):
        value = theorem()
        value['items'].append(dict(value['items'][0]))
        with self.assertRaisesRegex(ExtractionError, 'duplicate theorem'):
            validate_extraction('extract_theorems', value)
        with self.assertRaisesRegex(ExtractionError, 'data value'):
            validate_extraction('extract_data', {'items': [
                {'metric': 'p', 'value': None, 'source_refs': ['x']}], 'unresolved': []})

    def test_assumption_and_provenance_checks(self):
        value = {'items': [{'claim': 'c', 'text': 't', 'kind': 'explicit',
                            'source_refs': [], 'confidence': 0.5}], 'unresolved': []}
        with self.assertRaisesRegex(ExtractionError, 'explicit assumption source_refs'):
            validate_extraction('extract_assumptions', value)
        with self.assertRaisesRegex(ExtractionError, 'source_tree_hash'):
            make_proposal('extract_theorems', theorem(), source_tree_hash='short',
                          ai_result=result())
