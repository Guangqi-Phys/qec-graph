import json
import tempfile
import unittest
from pathlib import Path

from qecgraph.llm.artifacts import write_normalization
from qecgraph.llm.client import LLMResult
from qecgraph.llm.normalize import normalize_package
from qecgraph.source.package import SourceTree

MAIN = b'\\documentclass{article}\n\\begin{document}\nMain.\n\\end{document}\n'
SUPP = b'\\documentclass{article}\n\\begin{document}\nSupplement.\n\\end{document}\n'


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    def complete_json(self, messages, schema, **kwargs):
        self.calls += 1
        self.messages = messages
        return LLMResult(data=self.data, text=json.dumps(self.data), model='fake-model',
                         usage={'cost': 0.01}, request_id='req', attempts=1, cached=False,
                         run_id='run-1', prompt_sha256='prompt')


class RunnerTests(unittest.TestCase):
    def test_single_root_does_not_call_ai(self):
        client = FakeClient({})
        result = normalize_package(SourceTree('tex', {'main.tex': MAIN}), client)
        self.assertEqual(client.calls, 0)
        self.assertEqual(result.source.text, MAIN.decode())
        self.assertIsNone(result.ai_result)

    def test_multi_root_calls_ai_and_writes_auditable_artifact(self):
        plan = {'status': 'ready', 'documents': [],
                'operations': [{'op': 'use_preamble', 'source': 'main.tex'},
                               {'op': 'include_body', 'source': 'main.tex'},
                               {'op': 'append_body', 'source': 'supp.tex'}],
                'label_renames': {}, 'unresolved': []}
        client = FakeClient(plan)
        result = normalize_package(SourceTree('tex', {'main.tex': MAIN, 'supp.tex': SUPP}), client)
        self.assertEqual(client.calls, 1)
        self.assertIn('Supplement', result.source.text)
        self.assertEqual(result.ai_result.model, 'fake-model')
        with tempfile.TemporaryDirectory() as directory:
            target, manifest = write_normalization(Path(directory), result)
            self.assertTrue((target / 'main.tex').is_file())
            self.assertEqual(manifest['schema'], 'qecgraph.normalization')
            self.assertEqual(manifest['ai']['model'], 'fake-model')
            self.assertNotIn('secret', json.dumps(manifest))


class FallbackTests(unittest.TestCase):
    def test_needs_review_plan_falls_back_without_losing_sources(self):
        from qecgraph.llm.normalize import normalize_package
        plan = {'status': 'needs_review', 'documents': [],
                'operations': [{'op': 'include_asset', 'source': 'main.tex'}],
                'label_renames': {}, 'unresolved': []}
        client = FakeClient(plan)
        source = SourceTree('tex', {'main.tex': MAIN, 'Supplement.tex': SUPP})
        result = normalize_package(source, client)
        self.assertIn('Main.', result.source.text)
        self.assertIn('Supplement.', result.source.text)
        self.assertIn('AI plan was not usable', result.fallback_reason)
        self.assertEqual({segment['origin']['path'] for segment in result.source.segments
                          if segment['origin'] is not None}, {'main.tex', 'Supplement.tex'})
