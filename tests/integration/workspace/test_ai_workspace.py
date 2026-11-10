import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.llm.client import LLMResult
from qecgraph.workspace import Workspace
from tests.unit.parsing.test_source_package import TEX, tar_bytes


def answer(data):
    return LLMResult(data, json.dumps(data), 'fake', {}, None, 1, False, 'test-run', 'f' * 64)


class AIWorkspaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = Workspace(self.root)
        self.workspace.prepare()
        self.config = self.root / 'qecgraph.toml'
        self.configure('provider = "openrouter"', 'provider = "claude_code"')
        self.configure('model = ""', 'model = "fake"')

    def configure(self, old, new):
        self.config.write_text(self.config.read_text().replace(old, new))

    def test_independent_documents_stay_archived_and_unconsumed(self):
        package = self.root / 'inputs/papers.tar'
        package.write_bytes(tar_bytes({'a.tex': TEX, 'b.tex': TEX.replace(b'Hello', b'Independent paper')}))
        with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=answer({
            'status': 'needs_review', 'documents': [], 'operations': [], 'unresolved': ['independent manuscripts'],
        })):
            result = self.workspace.sync()
        self.assertEqual(result['status'], 'partial_batch')
        self.assertEqual(result['inputs'][0]['status'], 'needs_entrypoint')
        self.assertFalse(result['inputs'][0]['input_consumed'])
        self.assertTrue(package.exists())
        state, _ = self.workspace.registry.read()
        self.assertEqual(state['versions'], {})

    def test_normalized_source_maps_unicode_to_original_and_requires_bound_manifest(self):
        from qecgraph.workspace_query import WorkspaceSession

        supplement = '\\documentclass{article}\r\n\\begin{document}\r\n補遺 é😀\r\n\\end{document}\r\n'
        package = self.root / 'inputs/papers.tar'
        package.write_bytes(tar_bytes({'a.tex': TEX, 'b.tex': supplement.encode()}))
        plan = answer({'status': 'ready', 'documents': [{'path': 'a.tex', 'role': 'main'},
                                                        {'path': 'b.tex', 'role': 'supplement'}],
                       'operations': [{'op': 'use_preamble', 'source': 'a.tex'},
                                      {'op': 'include_body', 'source': 'a.tex'},
                                      {'op': 'append_body', 'source': 'b.tex'}], 'unresolved': []})
        empty = answer({'items': [], 'unresolved': []})
        with patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=[plan, empty, empty, empty]):
            report = self.workspace.sync()
        session = WorkspaceSession(self.root / 'machine', report['release_id'])
        node = next(n for n in session.graph.source.graph['nodes'] if n.get('source') and '補遺 é😀' in n['latex'])
        start = node['source']['char_start'] + node['latex'].index('é😀')
        args = {'identifier': node['id'], 'char_start': start, 'char_end': start + 2}
        result = session.invoke('qec_get_source', args)['data']
        self.assertEqual(result['source']['source_kind'], 'normalized')
        self.assertNotIn('archive_uri', result['source'])
        origin = result['original_ranges'][0]['source']
        self.assertEqual(origin['path'], 'b.tex')
        self.assertEqual(supplement[origin['char_start']:origin['char_end']], 'é😀')
        self.assertEqual(origin['line_start'], 3)
        resource = session.read_resource(result['resource_uri'])['contents'][0]
        self.assertIn('b.tex', {r['source']['path'] for r in resource['_meta']['original_ranges'] if r['source']})
        self.assertTrue(self.workspace.validate()['passed'])
        manifest = next((self.root / 'machine/derived/normalizations').rglob('manifest.json'))
        manifest.unlink()
        self.assertFalse(self.workspace.validate()['passed'])
        self.assertFalse(session.invoke('qec_get_source', args)['ok'])
        with self.assertRaisesRegex(ValueError, 'Candidate machine release failed validation'):
            self.workspace.sync()
        self.assertEqual(self.workspace.registry.read()[1], report['release_id'])
