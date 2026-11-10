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

    def test_provider_error_body_and_environment_key_never_reach_release(self):
        from qecgraph.llm.providers.base import HttpResult

        self.configure('provider = "claude_code"', 'provider = "openrouter"')
        (self.root / 'inputs/paper.tex').write_bytes(TEX)
        token = 'TEST_ENV_TOKEN_VALUE_94'
        body = json.dumps({'error': {'message': 'remote private diagnostic ' + token}}).encode()
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': token}), patch(
                'qecgraph.llm.providers.http.UrllibTransport.request', return_value=HttpResult(401, {}, body)):
            report = self.workspace.sync()
        state_path = self.root / 'machine/states' / (report['release_id'] + '.json')
        for output in (json.dumps(report), state_path.read_text()):
            self.assertNotIn(token, output)
            self.assertNotIn('remote private diagnostic', output)
            self.assertIn('HTTP 401', output)

    def test_sync_retries_only_failed_ai_skill_from_archive(self):
        from qecgraph.llm.errors import ProviderError

        package = self.root / 'inputs/paper.tex'
        package.write_bytes(TEX)
        empty = answer({'items': [], 'unresolved': []})
        with patch('qecgraph.llm.client.LLMClient.complete_json',
                   side_effect=[empty, ProviderError('temporary provider error'), empty]):
            first = self.workspace.sync()
        self.assertEqual(first['status'], 'partial_batch')
        self.assertTrue(first['inputs'][0]['input_consumed'])
        self.assertEqual(first['inputs'][0]['ai_extraction']['status'], 'pending')
        self.assertFalse(package.exists())
        with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=empty) as client:
            second = self.workspace.sync()
            self.assertEqual(client.call_count, 1)
            self.assertEqual(second['inputs'][0]['ai_extraction']['status'], 'complete')
            self.assertEqual(len(second['inputs'][0]['ai_extraction']['written']), 3)
            self.assertEqual(self.workspace.sync()['status'], 'unchanged')
            self.assertEqual(client.call_count, 1)

    def test_rebuild_reuses_committed_normalization_with_ai_disabled(self):
        package = self.root / 'inputs/papers.tar'
        package.write_bytes(tar_bytes({'a.tex': TEX, 'b.tex': TEX.replace(b'Hello', b'Supplement')}))
        plan = answer({'status': 'ready', 'documents': [{'path': 'a.tex', 'role': 'main'},
                                                        {'path': 'b.tex', 'role': 'source'}],
                       'operations': [{'op': 'use_document', 'source': 'a.tex'}], 'unresolved': []})
        empty = answer({'items': [], 'unresolved': []})
        with patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=[plan, empty, empty, empty]):
            first = self.workspace.sync()['inputs'][0]
        self.configure('enabled = true', 'enabled = false')
        with patch('qecgraph.llm.client.LLMClient.complete_json') as client:
            rebuilt = self.workspace.rebuild()['inputs'][0]
            client.assert_not_called()
        self.assertTrue(rebuilt['processing_completed'])
        self.assertEqual(rebuilt['source_snapshot_id'], first['source_snapshot_id'])
        self.assertEqual(rebuilt['normalization_manifest_sha256'], first['normalization_manifest_sha256'])
        self.assertEqual(rebuilt['ai_extraction'], first['ai_extraction'])
