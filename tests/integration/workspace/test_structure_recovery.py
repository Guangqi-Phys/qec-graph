import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.core.graph import read_json
from qecgraph.llm.providers.base import HttpResult
from qecgraph.store import validate_snapshot
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from tests.unit.parsing.test_source_package import TEX as ORDINARY
from tests.unit.parsing.test_structure import TEX, plan


class WorkspaceStructureRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.ws = Workspace(self.root)
        self.ws.prepare()
        self.cfg = self.root / 'qecgraph.toml'
        self.configure('model = ""', 'model = "fake"')
        self.enterContext(patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-structure-test'}))

    def configure(self, old, new):
        self.cfg.write_text(self.cfg.read_text().replace(old, new))

    def provider(self, value):
        body = {'choices': [{'message': {'content': json.dumps(value)}}], 'model': 'offline'}
        return patch('qecgraph.llm.providers.http.UrllibTransport.request',
                     return_value=HttpResult(200, {}, json.dumps(body).encode()))

    def test_ordinary_packages_never_call_provider_by_default(self):
        (self.root / 'inputs/paper.tex').write_bytes(ORDINARY)
        with self.provider(plan()) as provider:
            result = self.ws.sync()
            provider.assert_not_called()
        self.assertEqual(result['status'], 'published')
        self.assertNotIn('structure_recovery', result['inputs'][0])

    def test_eligible_failure_publishes_proposed_verbatim_structure_and_rebuilds_offline(self):
        package = self.root / 'inputs/paper.tex'
        package.write_bytes(TEX)
        with self.provider(plan()) as provider:
            report = self.ws.sync()
        self.assertEqual(report['status'], 'published')
        self.assertEqual(provider.call_count, 1)
        payload = json.loads(provider.call_args.kwargs['body'])
        self.assertNotIn('PREAMBLE_ONLY', payload['messages'][-1]['content'])
        row, = report['inputs']
        self.assertTrue(row['input_consumed'])
        self.assertEqual(row['structure_recovery']['status'], 'proposed')
        source = self.root / 'archive/blobs/sha256' / hashlib.sha256(TEX).hexdigest()
        self.assertEqual(source.read_bytes(), TEX)
        snapshot = self.root / 'machine/source_snapshots' / row['source_snapshot_id']
        self.assertEqual((snapshot / 'sources/main.tex').read_bytes(), TEX)
        graph = read_json(snapshot / 'graph.json')
        self.assertEqual(graph['extraction_status'], 'recovered_proposed')
        self.assertEqual({n['review_status'] for n in graph['nodes'] if n['source']}, {'proposed'})
        self.assertTrue(validate_snapshot(snapshot)['passed'])
        self.assertTrue(self.ws.validate()['passed'])
        self.assertEqual(self.ws.status()['counts']['processed'], 1)
        pinned = WorkspaceSession(self.root / 'machine')
        prose = next(n for n in pinned.graph.source.graph['nodes'] if n.get('reading_text') == 'λ cites .')
        excerpt = pinned.source_excerpt(prose['id'])
        self.assertIn(r'\cite{example}', excerpt['latex'])
        self.configure('enabled = true', 'enabled = false')
        with self.provider(plan()) as provider:
            rebuilt = self.ws.rebuild()
            provider.assert_not_called()
        self.assertEqual(rebuilt['inputs'][0]['source_snapshot_id'], row['source_snapshot_id'])
        self.assertEqual(rebuilt['inputs'][0]['structure_recovery'], row['structure_recovery'])

    def test_declined_and_invalid_plans_leave_inbox_and_retry(self):
        package = self.root / 'inputs/paper.tex'
        package.write_bytes(TEX)
        for output, reason in (({'status': 'needs_review', 'blocks': []}, 'provider_requested_review'),
                               ({'status': 'ready', 'blocks': []}, 'invalid_structure_plan')):
            with self.subTest(reason=reason), self.provider(output) as provider:
                row, = self.ws.sync()['inputs']
                provider.assert_called_once()
                self.assertEqual(row['status'], 'parse_failed')
                self.assertEqual(row['structure_recovery']['reason'], reason)
                self.assertFalse(row['input_consumed'])
                self.assertEqual(package.read_bytes(), TEX)
                self.assertEqual(self.ws.registry.read()[0]['versions'], {})
        with self.provider(plan()):
            self.assertEqual(self.ws.sync()['status'], 'published')

    def test_external_inputs_and_disabled_fallback_never_call_provider(self):
        package = self.root / 'inputs/paper.tex'
        package.write_bytes(TEX.replace(b'Later source.', rb'\input{missing}'))
        with self.provider(plan()) as provider:
            report = self.ws.sync()
            provider.assert_not_called()
        self.assertEqual(report['inputs'][0]['structure_recovery']['reason'], 'body_outside_supported_scope')
        package.write_bytes(TEX)
        self.configure('structure_fallback = true', 'structure_fallback = false')
        with self.provider(plan()) as provider:
            report = self.ws.sync()
            provider.assert_not_called()
        self.assertEqual(report['inputs'][0]['structure_recovery']['reason'], 'fallback_disabled')

    def test_failed_publication_preserves_pinned_release_and_exact_claim(self):
        (self.root / 'inputs/ordinary.tex').write_bytes(ORDINARY)
        first = self.ws.sync()['release_id']
        (self.root / 'inputs/special.tex').write_bytes(TEX)
        with self.provider(plan()), patch.object(self.ws.registry, 'validate', return_value={'passed': False}):
            with self.assertRaisesRegex(ValueError, 'CURRENT was retained'):
                self.ws.sync()
        self.assertEqual(self.ws.registry.read()[1], first)
        self.assertEqual(WorkspaceSession(self.ws.registry.root, first).release, first)
        claim, = (self.root / 'inputs/.processing').glob('*/payload')
        self.assertEqual(claim.read_bytes(), TEX)
        with self.provider(plan()) as provider:
            retry = self.ws.sync()
            provider.assert_not_called()  # The checked plan was cached before the failed publication.
        self.assertEqual(retry['status'], 'published')
        self.assertTrue(retry['inputs'][0]['input_consumed'])

    def test_rejects_tampered_plan_or_classification_even_with_updated_output_hash(self):
        (self.root / 'inputs/paper.tex').write_bytes(TEX)
        with self.provider(plan()):
            row, = self.ws.sync()['inputs']
        snapshot = self.root / 'machine/source_snapshots' / row['source_snapshot_id']
        graph_path, manifest_path = snapshot / 'graph.json', snapshot / 'manifest.json'
        original_graph = graph_path.read_bytes()
        manifest = read_json(manifest_path)
        for edit in ('plan', 'classification'):
            with self.subTest(edit=edit):
                graph = json.loads(original_graph)
                if edit == 'plan':
                    graph['structure_recovery']['plan']['blocks'][1]['kind'] = 'theorem'
                else:
                    node = next(node for node in graph['nodes'] if node.get('structure_classification') == 'unknown')
                    node['review_status'] = 'reviewed'
                graph_path.write_text(json.dumps(graph))
                binding = next(item for item in manifest['outputs'] if item['path'] == 'graph.json')
                binding['sha256'] = hashlib.sha256(graph_path.read_bytes()).hexdigest()
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, 'structure'):
                    validate_snapshot(snapshot)
