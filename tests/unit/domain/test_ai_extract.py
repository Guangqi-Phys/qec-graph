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


class ExtractionRunnerTests(unittest.TestCase):
    def normalized(self):
        from qecgraph.llm.normalize import NormalizedSource
        data = b'\\documentclass{article}\n\\begin{document}\nTheorem text.\n\\end{document}\n'
        return NormalizedSource('b' * 64, data, {'status': 'ready', 'documents': [],
                                                 'operations': [{'op': 'use_document', 'source': 'main.tex'}],
                                                 'label_renames': {}, 'unresolved': []},
                                ({'normalized': {'byte_start': 0, 'byte_end': len(data)},
                                  'origin': {'path': 'main.tex', 'byte_start': 0, 'byte_end': len(data)},
                                  'kind': 'original'},))

    def test_runner_uses_skill_prompt_and_returns_proposal(self):
        from qecgraph.llm.extract import extract

        class Client:
            def complete_json(self, messages, schema, **kwargs):
                self.messages = messages
                return result_with({'items': [{'label': 'thm:a', 'statement': 'Theorem text.',
                                               'source_refs': ['main.tex:3'], 'hypotheses': []}],
                                    'unresolved': []})

        client = Client()
        value = extract(self.normalized(), client, 'extract_theorems')
        self.assertEqual(value.proposal['skill'], 'extract_theorems')
        self.assertEqual(value.proposal['review_status'], 'proposed')
        self.assertIn('source_refs', value.proposal['items'][0])
        self.assertIn('theorem extractor', client.messages[-1].content)

    def test_extraction_tasks_share_a_source_prefix_and_keep_the_task_after_data(self):
        from qecgraph.llm.extract import extract, EXTRACTION_SYSTEM
        calls = []
        class Client:
            def complete_json(self, messages, schema, **kwargs):
                calls.append(messages)
                return result_with({'items': [], 'unresolved': []})
        for skill in ('extract_theorems', 'extract_assumptions'):
            extract(self.normalized(), Client(), skill)
        self.assertEqual(calls[0][:2], calls[1][:2])
        self.assertEqual(calls[0][0].content, EXTRACTION_SYSTEM)
        self.assertIn('3 | Theorem text.', calls[0][1].content)
        self.assertNotEqual(calls[0][2], calls[1][2])

    def test_runner_rejects_forged_citations_and_nonverbatim_theorems(self):
        from qecgraph.llm.extract import extract

        for reference, statement, error in (
            ('missing.tex:9000-9999', 'Invented theorem', 'supplied projection'),
            ('main.tex:9000-9999', 'Theorem text.', 'out of bounds'),
            ('main.tex:3', 'Invented theorem', 'not verbatim'),
        ):
            with self.subTest(reference=reference, statement=statement):
                class Client:
                    def complete_json(self, *args, **kwargs):
                        return result_with({'items': [{'label': 'thm:a', 'statement': statement,
                                                       'hypotheses': [], 'source_refs': [reference]}],
                                            'unresolved': []})

                with self.assertRaisesRegex(ExtractionError, error):
                    extract(self.normalized(), Client(), 'extract_theorems')

    def test_runner_rejects_unsupported_skill(self):
        from qecgraph.llm.extract import extract
        with self.assertRaisesRegex(ExtractionError, 'unsupported extraction skill'):
            extract(self.normalized(), object(), 'unknown')


def result_with(data):
    return LLMResult(data=data, text='{}', model='model', usage={}, request_id='r',
                     attempts=1, cached=False, run_id='run', prompt_sha256='p' * 64)
