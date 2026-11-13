import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph import store, workspace_assets
from qecgraph.core.graph import canonical, read_json
from qecgraph.domain.research import make_record
from qecgraph.domain.research_store import publish_records, validate_sources
from qecgraph.domain.status import annotation_eligible
from qecgraph.workspace import Workspace
from tests.unit.parsing.test_source_package import TEX


class SemanticTests(unittest.TestCase):
    def test_needs_review_annotations_are_not_default_eligible(self):
        self.assertFalse(annotation_eligible({'review_status': 'needs_review'}))
        self.assertTrue(annotation_eligible({'review_status': 'needs_review'}, include_candidates=True))
        self.assertTrue(annotation_eligible({'review_status': 'reviewed'}))

    def test_repeated_asset_bindings_stream_one_verification_per_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Workspace(directory)
            ws.init(no_ingest=True)
            raw = b'fixture matrix bytes'
            asset = ws.registry._put_asset(raw, 'application/octet-stream')
            state, _ = ws.registry.read()
            record = {'kind': 'syndrome_measurement_circuit', 'data': {'circuit_asset_ref': asset['uri']},
                      'is_synthetic': False, 'field_evidence': {}}
            with patch.object(workspace_assets, '_hash_regular', wraps=workspace_assets._hash_regular) as verify:
                validate_sources(ws.registry, state, [record, record])
                verify.assert_called_once()
            path = ws.registry.root / asset['path']
            path.write_bytes(raw + b'changed')
            with self.assertRaisesRegex(ValueError, 'Managed asset content changed'):
                validate_sources(ws.registry, state, [record, record])

    def test_new_paper_record_cannot_claim_an_unregistered_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'inputs').mkdir()
            (root / 'inputs/source.tex').write_bytes(TEX)
            ws = Workspace(root)
            previous = ws.init()['release_id']
            state, _ = ws.registry.read(previous)
            version, = state['versions'].values()
            digest = 'a' * 64
            origin = {'id': version['id'], 'revision': digest}
            record = make_record('paper_version', version['id'], digest,
                                 {'work_id': version['work_id'], 'upstream_version': version['upstream_version'],
                                  'source_snapshot_id': digest}, source=origin, method='fixture')
            with self.assertRaisesRegex(ValueError, 'current registered source projection'):
                publish_records(ws.registry, [record])
            self.assertEqual(ws.registry.read()[1], previous)
            self.assertTrue(ws.validate()['valid'])

    def test_iterator_records_are_verified_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'inputs').mkdir()
            (root / 'inputs/source.tex').write_bytes(TEX)
            ws = Workspace(root)
            previous = ws.init()['release_id']
            state, _ = ws.registry.read(previous)
            identifier, = state['versions']
            graph, _, version = ws.registry.source_graph(identifier, previous)
            node = next(n for n in graph['nodes'] if n['latex'] == 'Hello')
            origin = {'id': identifier, 'revision': version['snapshot_id']}
            locator = {**node['source'], 'node_id': node['id'], 'node_content_sha256': 'b' * 64,
                       'source_version_id': identifier, 'snapshot_id': version['snapshot_id']}
            field = '/data/source_label'
            record = make_record('noise_model', 'noise:iterator', 'one',
                                 {'idle': None, 'loss': None, 'erasure': None, 'leakage': None,
                                  'source_label': 'Hello', 'review_status': 'proposed'}, source=origin,
                                 method='fixture', evidence={field: {'status': 'known', 'source_ref': origin,
                                                                   'source_locator': locator, 'method': 'fixture'}})
            with self.assertRaisesRegex(ValueError, 'does not resolve to a verbatim registered span'):
                publish_records(ws.registry, iter([record]))
            self.assertEqual(ws.registry.read()[1], previous)

            record['field_evidence'][field]['source_locator']['node_content_sha256'] = node['content_sha256']
            result = publish_records(ws.registry, iter([record, record]))
            self.assertEqual(result['status'], 'imported')
            self.assertEqual(result['input_records'], 2)
            state, fixed = ws.registry.read()
            self.assertEqual(fixed, result['release_id'])
            self.assertEqual(set(state['research_records'][record['id']]), {'one'})

    def test_source_evidence_uses_the_graph_bytes_that_passed_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'inputs').mkdir()
            (root / 'inputs/source.tex').write_bytes(TEX)
            ws = Workspace(root)
            ws.init()
            state, _ = ws.registry.read()
            identifier, = state['versions']
            version = state['versions'][identifier]
            graph_path = ws.registry.root / version['snapshot_path'] / 'graph.json'
            replacement = read_json(graph_path)
            node = next(n for n in replacement['nodes'] if n['latex'] == 'Hello')
            node['content_sha256'] = 'b' * 64
            locator = {**node['source'], 'node_id': node['id'], 'node_content_sha256': node['content_sha256'],
                       'source_version_id': identifier, 'snapshot_id': version['snapshot_id']}
            record = {'kind': 'noise_model', 'data': {}, 'is_synthetic': False, 'field_evidence': {
                '/data/source_label': {'source_ref': {'id': identifier, 'revision': version['snapshot_id']},
                                       'source_locator': locator}}}
            read_snapshot_file = store._read_snapshot_file

            def replace_after_capture(path, copy_to, relative):
                raw = read_snapshot_file(path, copy_to, relative)
                if path == graph_path:
                    path.write_text(canonical(replacement), encoding='utf-8')
                return raw

            with patch.object(store, '_read_snapshot_file', replace_after_capture):
                with self.assertRaisesRegex(ValueError, 'does not resolve to a verbatim registered span'):
                    validate_sources(ws.registry, state, [record])
            self.assertEqual(read_json(graph_path), replacement)
