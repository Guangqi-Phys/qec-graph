import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph import store
from qecgraph.graph import canonical, read_json
from qecgraph.research import make_record
from qecgraph.research_store import publish_records, validate_sources
from qecgraph.semantic import request_extraction, review_extraction, submit_extraction
from qecgraph.source_package import unpack
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from test_source_package import TEX, tar_bytes


class SemanticTests(unittest.TestCase):
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

    def test_provider_draft_is_bound_reviewed_and_stale_on_projection_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ws = Workspace(root)
            ws.init(no_ingest=True)
            raw = tar_bytes({'one.tex': TEX, 'two.tex': TEX.replace(b'Hello', b'Later')})
            (root / 'inputs/source').write_bytes(raw)
            config = root / 'qecgraph.toml'
            initial = config.read_text()
            settings = f'\n[entrypoints]\n"{unpack(raw).digest}" = '
            config.write_text(initial + settings + '"one.tex"\n')
            ws.sync()
            state, _ = ws.registry.read()
            identifier, = state['versions']
            req = request_extraction(root, identifier)
            block = next(b for b in req['blocks'] if b['latex'] == 'Hello')
            origin = req['source_ref']
            locator = {k: block[k] for k in ('node_id', 'node_content_sha256', 'path', 'char_start', 'char_end')}
            locator.update(source_version_id=origin['id'], snapshot_id=origin['revision'])
            evidence = {'status': 'known', 'source_ref': origin, 'source_locator': locator, 'method': 'provider_fixture'}
            record = make_record('noise_model', 'noise:proposal', 'one',
                                 {'idle': None, 'loss': None, 'erasure': None, 'leakage': None,
                                  'source_label': 'Hello', 'review_status': 'proposed'}, source=origin,
                                 method='provider_fixture', evidence={'/data/source_label': evidence})
            payload = {'provider': {'model_id': 'local-test', 'processor_version': '1', 'prompt_sha256': 'a' * 64},
                       'records': [record]}
            submitted_locator = record['field_evidence']['/data/source_label']['source_locator']
            submitted_locator['path'] = '../human/notes/private'
            with self.assertRaisesRegex(ValueError, 'cite a span'):
                submit_extraction(root, req['id'], payload)
            submitted_locator['path'] = block['path']
            queued = submit_extraction(root, req['id'], payload)
            query = {'identifier': record['id']}
            self.assertFalse(WorkspaceSession(ws.registry.root).invoke('qec_get_entity', query)['ok'])
            result = review_extraction(root, queued['proposal_id'], reviewer='human:test', decision='approve',
                                       rationale='Checked fixture text')
            session = WorkspaceSession(ws.registry.root, result['release_id'])
            self.assertEqual(session.invoke('qec_get_entity', query)['data']['entity']['effective_review']['status'], 'reviewed')
            config.write_text(initial + settings + '"two.tex"\n')
            ws.rebuild()
            after = WorkspaceSession(ws.registry.root)
            self.assertFalse(after.invoke('qec_get_entity', query)['ok'])
            self.assertEqual(after.invoke('qec_workspace_status', {})['data']['coverage']['excluded_stale_provider_reviews'], 1)
            self.assertTrue(session.invoke('qec_get_entity', query)['ok'])
            self.assertTrue(ws.validate()['passed'])
            old_graph = ws.registry.root / state['versions'][identifier]['snapshot_path'] / 'graph.json'
            with old_graph.open('ab') as output:
                output.write(b' ')
            with self.assertRaisesRegex(ValueError, 'Snapshot file changed: graph.json'):
                ws.validate()
