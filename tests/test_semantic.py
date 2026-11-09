import tempfile
import unittest
from pathlib import Path

from qecgraph.research import make_record
from qecgraph.semantic import request_extraction, review_extraction, submit_extraction
from qecgraph.source_package import unpack
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from test_source_package import TEX, tar_bytes


class SemanticTests(unittest.TestCase):
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
