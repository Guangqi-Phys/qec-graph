import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.core.graph import canonical
from qecgraph.llm.providers.base import HttpResult
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from qecgraph.retrieval import configuration


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ws = Workspace(self.root)
        self.ws.prepare()
        self.cfg = self.root / 'qecgraph.toml'
        self.cfg.write_text(self.cfg.read_text().replace('enabled = false', 'enabled = true', 1))
        (self.root / 'inputs/a.tex').write_text('\\documentclass{article}\n\\begin{document}\n'
                                              '\\section{Memory}\nProtecting qubits using a quantum memory.\n\nA second quantum memory passage.\n\\end{document}\n')

    def session(self):
        return WorkspaceSession(self.root / 'machine', profile='research')

    def test_local_modes_filters_paging_pin_and_incremental_reuse(self):
        self.ws.sync()
        first = self.session()
        for mode in ('keyword', 'vector', 'hybrid'):
            result = first.invoke('qec_search', {'query': 'quantum protecting', 'mode': mode,
                                               'kind': 'paragraph', 'limit': 1})
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['data']['results'][0]['kind'], 'paragraph')
            self.assertEqual(result['data']['retrieval']['status'], 'current')
        self.assertEqual(self.ws.sync()['status'], 'unchanged')
        old_binding = first.state['retrieval_index']
        notes = self.root / 'human/notes'
        notes.mkdir(parents=True)
        (notes / 'private.md').write_text('privatecanaryzrq')
        self.assertEqual(self.ws.sync()['status'], 'unchanged')
        self.assertEqual(self.session().invoke('qec_search', {'query': 'privatecanaryzrq', 'mode': 'keyword'})['data']['results'], [])
        (self.root / 'inputs/b.tex').write_text('\\documentclass{article}\n\\begin{document}\nUnique decoder decoding.\n\\end{document}')
        self.ws.sync()
        new = self.session()
        self.assertNotEqual(old_binding, new.state['retrieval_index'])
        self.assertEqual(first.invoke('qec_search', {'query': 'Unique decoder', 'mode': 'keyword'})['data']['results'], [])
        version = next(iter(first.state['versions']))
        self.assertEqual(new.invoke('qec_search', {'query': 'decoder', 'mode': 'keyword', 'source_version_id': version})['data']['results'], [])
        all_rows = new.invoke('qec_search', {'query': 'quantum', 'limit': 100})
        self.assertFalse(all_rows['ok'])  # Session maximum is enforced.
        rows = new.invoke('qec_search', {'query': 'quantum', 'limit': 1})['data']
        self.assertTrue(rows['truncated'])
        next_page = new.invoke('qec_search', {'query': 'quantum', 'limit': 1, 'offset': rows['continuation']})['data']
        self.assertNotEqual(rows['results'][0]['id'], next_page['results'][0]['id'])

    def external_config(self):
        text = self.cfg.read_text().replace('provider = "local"', 'provider = "openai_compatible"', 1).replace(
            'model = "qecgraph-word-char-hash"', 'model = "fake-embedding"', 1).replace('dimensions = 512', 'dimensions = 8', 1).replace(
                'allow_source_upload = false', 'allow_source_upload = true\nbase_url = "https://embedding.example/v1"', 1)
        self.cfg.write_text(text)

    def fake_transport(self, method, url, *, headers, body, timeout):
        request = json.loads(body)
        self.assertEqual(url, 'https://embedding.example/v1/embeddings')
        self.assertEqual(request['dimensions'], 8)
        rows = []
        for i, text in enumerate(request['input']):
            # Controlled semantic fixture: memory and storage share a vector despite different words.
            semantic = 'memory' in text.casefold() or 'storage' in text.casefold()
            rows.append({'index': i, 'embedding': [1, 0, 0, 0, 0, 0, 0, 0] if semantic else [0, 1, 0, 0, 0, 0, 0, 0]})
        return HttpResult(200, {}, json.dumps({'model': request['model'], 'data': list(reversed(rows))}).encode())

    def test_external_semantic_vectors_model_binding_and_offline_reuse(self):
        self.external_config()
        with patch.dict('os.environ', {'QECGRAPH_EMBEDDING_API_KEY': 'TEST-SECRET'}), patch(
                'qecgraph.llm.providers.http.UrllibTransport.request', side_effect=self.fake_transport) as transport:
            self.ws.sync()
            self.assertGreater(transport.call_count, 0)
            session = self.session()
            results = session.invoke('qec_search', {'query': 'storage', 'kind': 'paragraph', 'mode': 'vector'})
            self.assertTrue(results['ok'], results)
            self.assertTrue(results['data']['results'])
            self.assertNotIn('TEST-SECRET', canonical(session.state))
        with patch('qecgraph.llm.providers.http.UrllibTransport.request', side_effect=AssertionError('unexpected provider call')):
            self.assertEqual(self.ws.sync()['status'], 'unchanged')
        # Model revision is part of cache identity even when dimensions are equal.
        self.cfg.write_text(self.cfg.read_text().replace('model_revision = "1"', 'model_revision = "2"', 1))
        with patch.dict('os.environ', {'QECGRAPH_EMBEDDING_API_KEY': 'TEST-SECRET'}), patch(
                'qecgraph.llm.providers.http.UrllibTransport.request', side_effect=self.fake_transport) as transport:
            self.ws.sync()
            self.assertGreater(transport.call_count, 0)
        self.assertEqual(self.session().state['retrieval_index']['identity']['model_revision'], '2')

    def test_failed_embedding_keeps_release_and_archive_and_query_fallback_is_visible(self):
        self.ws.sync()
        previous = self.session().release
        self.external_config()
        with patch.dict('os.environ', {'QECGRAPH_EMBEDDING_API_KEY': 'TEST-SECRET'}), patch(
                'qecgraph.llm.providers.http.UrllibTransport.request', return_value=HttpResult(200, {}, b'{"model":"wrong","data":[]}')):
            with self.assertRaisesRegex(ValueError, 'Embedding provider failed'):
                self.ws.sync()
        self.assertEqual(self.session().release, previous)
        self.assertTrue(list((self.root / 'archive/blobs/sha256').iterdir()))
        with patch.dict('os.environ', {'QECGRAPH_EMBEDDING_API_KEY': 'TEST-SECRET'}), patch(
                'qecgraph.llm.providers.http.UrllibTransport.request', side_effect=self.fake_transport):
            self.ws.sync()
        with patch.dict('os.environ', {}, clear=True):
            answer = self.session().invoke('qec_search', {'query': 'memory', 'mode': 'hybrid'})
            self.assertTrue(answer['ok'], answer)
            self.assertIn('unavailable', answer['data']['fallback'])
            failed = self.session().invoke('qec_search', {'query': 'memory', 'mode': 'vector'})
            self.assertEqual(failed['error']['code'], 'EMBEDDING_UNAVAILABLE')

    def test_explicit_upload_and_budgets_no_human_indexing(self):
        with self.assertRaises(ValueError):
            configuration({'enabled': True, 'provider': 'openai_compatible', 'base_url': 'https://example.org'})
        self.cfg.write_text(self.cfg.read_text().replace('chunk_chars = 2048', 'chunk_chars = 128\nmax_chunks = 1', 1))
        with self.assertRaisesRegex(ValueError, 'chunk budget'):
            self.ws.sync()
        self.assertFalse((self.root / 'machine/CURRENT.json').exists())

    def test_corrupt_projection_is_detected_and_rebuild_restores_derived_bytes(self):
        self.ws.sync()
        binding = self.session().state['retrieval_index']
        path = self.root / 'machine/retrieval/indexes' / (binding['sha256'] + '.json')
        original = path.read_bytes()
        path.write_text('{}')
        self.assertFalse(self.ws.validate()['passed'])
        self.assertFalse(self.session().invoke('qec_search', {'query': 'memory'})['ok'])
        self.ws.rebuild()
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(self.ws.validate()['passed'])
