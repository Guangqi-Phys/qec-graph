import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.llm.client import LLMResult
from qecgraph.llm.config import DEFAULT_MODEL
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
        self.enterContext(patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'offline-test-key'}))
        self.config = self.root / 'qecgraph.toml'
        self.configure('provider = "openrouter"', 'provider = "claude_code"')
        self.configure(f'model = "{DEFAULT_MODEL}"', 'model = "fake"')

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
        with patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=[plan, empty, empty, empty, empty]):
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

    def test_interrupted_http_body_leaves_pending_ai_and_publishes_source(self):
        from http.client import IncompleteRead
        from unittest.mock import MagicMock

        self.configure('provider = "claude_code"', 'provider = "openrouter"')
        (self.root / 'inputs/paper.tex').write_bytes(TEX)
        response = MagicMock(status=200, headers={})
        response.__enter__.return_value = response
        response.read.side_effect = IncompleteRead(b'PRIVATE_PARTIAL_RESPONSE')
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-test-key'}), patch(
                'urllib.request.urlopen', return_value=response), patch('qecgraph.llm.client.time.sleep'):
            report = self.workspace.sync()
        self.assertEqual(report['status'], 'partial_batch')
        self.assertTrue(report['inputs'][0]['input_consumed'])
        self.assertEqual(report['inputs'][0]['ai_extraction']['status'], 'pending')
        self.assertNotIn('PRIVATE_PARTIAL_RESPONSE', json.dumps(report))
        self.assertTrue(self.workspace.validate()['passed'])

    def test_sync_retries_only_failed_ai_skill_from_archive(self):
        from qecgraph.llm.errors import ProviderError

        package = self.root / 'inputs/paper.tex'
        package.write_bytes(TEX)
        empty = answer({'items': [], 'unresolved': []})
        with patch('qecgraph.llm.client.LLMClient.complete_json',
                   side_effect=[empty, ProviderError('temporary provider error'), empty, empty]):
            first = self.workspace.sync()
        self.assertEqual(first['status'], 'partial_batch')
        self.assertTrue(first['inputs'][0]['input_consumed'])
        self.assertEqual(first['inputs'][0]['ai_extraction']['status'], 'pending')
        self.assertFalse(package.exists())
        self.assertEqual(self.workspace.status()['status'], 'partial_batch')
        with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=empty) as client:
            second = self.workspace.sync()
            self.assertEqual(client.call_count, 1)
            self.assertEqual(second['inputs'][0]['ai_extraction']['status'], 'complete')
            self.assertEqual(len(second['inputs'][0]['ai_extraction']['written']), 4)
            self.assertEqual(self.workspace.sync()['status'], 'unchanged')
            self.assertEqual(client.call_count, 1)

    def test_rebuild_reuses_committed_normalization_with_ai_disabled(self):
        package = self.root / 'inputs/papers.tar'
        package.write_bytes(tar_bytes({'a.tex': TEX, 'b.tex': TEX.replace(b'Hello', b'Supplement')}))
        plan = answer({'status': 'ready', 'documents': [{'path': 'a.tex', 'role': 'main'},
                                                        {'path': 'b.tex', 'role': 'source'}],
                       'operations': [{'op': 'use_document', 'source': 'a.tex'}], 'unresolved': []})
        empty = answer({'items': [], 'unresolved': []})
        with patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=[plan, empty, empty, empty, empty]):
            first = self.workspace.sync()['inputs'][0]
        self.configure('enabled = true', 'enabled = false')
        with patch('qecgraph.llm.client.LLMClient.complete_json') as client:
            rebuilt = self.workspace.rebuild()['inputs'][0]
            client.assert_not_called()
        self.assertTrue(rebuilt['processing_completed'])
        self.assertEqual(rebuilt['source_snapshot_id'], first['source_snapshot_id'])
        self.assertEqual(rebuilt['normalization_manifest_sha256'], first['normalization_manifest_sha256'])
        self.assertEqual(rebuilt['ai_extraction'], first['ai_extraction'])

    def test_tool_upgrade_rebinds_english_proposals_with_identical_source_evidence(self):
        from qecgraph.llm.review import read_bound_proposal
        from qecgraph.workspace import extraction_tool_identity

        (self.root / 'inputs/paper.tex').write_bytes(TEX)
        with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=answer({'items': [], 'unresolved': []})):
            first = self.workspace.sync()['inputs'][0]
        old = {b['skill']: b for b in first['ai_extraction']['written']}
        old_bytes = {b['path']: (self.workspace.registry.root / b['path']).read_bytes() for b in old.values()}
        changed = {**extraction_tool_identity(), 'tool_version': 'english-upgrade-fixture'}
        with patch('qecgraph.workspace.extraction_tool_identity', return_value=changed), patch(
                'qecgraph.llm.client.LLMClient.complete_json', side_effect=AssertionError('No AI call needed')) as client:
            latest = self.workspace.rebuild()['inputs'][0]
            client.assert_not_called()
        self.assertNotEqual(latest['source_snapshot_id'], first['source_snapshot_id'])
        self.assertEqual(len(latest['ai_extraction']['written']), 4)
        for binding in latest['ai_extraction']['written']:
            proposal = read_bound_proposal(self.workspace.registry, binding, latest)
            self.assertEqual(proposal['review_status'], 'proposed')
            self.assertEqual(proposal['provenance']['skill_version'], 5)
            self.assertEqual(proposal['provenance']['source_rebindings'], [{
                'snapshot_id': first['source_snapshot_id'], 'proposal_path': old[binding['skill']]['path'],
                'proposal_sha256': old[binding['skill']]['proposal_sha256'],
                'reason': 'Identical source files; citations revalidated for the new snapshot'}])
        self.assertEqual({p: (self.workspace.registry.root / p).read_bytes() for p in old_bytes}, old_bytes)
        self.assertTrue(self.workspace.validate()['passed'])

    def test_changed_entrypoint_does_not_reuse_previous_proposals(self):
        from qecgraph.source.package import unpack

        raw = tar_bytes({'a.tex': TEX, 'b.tex': TEX.replace(b'Hello', b'Other manuscript')})
        (self.root / 'inputs/paper.tar').write_bytes(raw)
        original_config = self.config.read_text()
        setting = f'\n[entrypoints]\n"{unpack(raw).digest}" = '
        self.config.write_text(original_config + setting + '"a.tex"\n')
        with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=answer({'items': [], 'unresolved': []})):
            self.workspace.sync()
        self.config.write_text(original_config + setting + '"b.tex"\n')
        with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=answer({'items': [], 'unresolved': []})) as client:
            result = self.workspace.rebuild()
        self.assertEqual(client.call_count, 4)
        self.assertEqual(result['inputs'][0]['entrypoint'], 'b.tex')

    def test_parallel_extraction_uses_only_the_selected_entry_point(self):
        from qecgraph.source.package import unpack

        raw = tar_bytes({'selected.tex': TEX, 'other.tex': TEX.replace(b'Hello', b'UNSELECTED_MARKER')})
        tree = unpack(raw)
        for workers in (1, 2):
            with self.subTest(workers=workers), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workspace = Workspace(root)
                workspace.prepare()
                config = self.config.read_text().replace('max_parallel_packages = 1', f'max_parallel_packages = {workers}')
                config = config.replace(self.workspace.config()['workspace_id'], workspace.config()['workspace_id'])
                (root / 'qecgraph.toml').write_text(config + f'\n[entrypoints]\n"{tree.digest}" = "selected.tex"\n')
                (root / 'inputs/papers.tar').write_bytes(raw)
                empty = answer({'items': [], 'unresolved': []})
                with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=empty) as client:
                    report = workspace.sync()
                    self.assertEqual(client.call_count, 4)
                    for call in client.call_args_list:
                        self.assertNotIn('UNSELECTED_MARKER', call.args[0][-1].content)
                self.assertEqual(report['inputs'][0]['entrypoint'], 'selected.tex')
                self.assertEqual(report['inputs'][0]['ai_extraction']['status'], 'complete')

    def test_packages_extract_concurrently_but_stage_on_the_writer_thread(self):
        from threading import Barrier, Lock, get_ident

        self.configure('max_parallel_packages = 1', 'max_parallel_packages = 2')
        (self.root / 'inputs/first.tex').write_bytes(TEX)
        (self.root / 'inputs/second.tex').write_bytes(TEX.replace(b'Hello', b'Second paper'))
        ready, lock = Barrier(2), Lock()
        sources, worker_threads, staging_threads = set(), set(), []
        stage = self.workspace._stage_ai

        def answer_in_parallel(messages, schema, **kwargs):
            source = json.loads(messages[1].content)['source_tree_hash']
            with lock:
                first = source not in sources
                sources.add(source)
                worker_threads.add(get_ident())
            if first:
                ready.wait(timeout=5)
            return answer({'items': [], 'unresolved': []})

        def serial_stage(*args, **kwargs):
            staging_threads.append(get_ident())
            return stage(*args, **kwargs)

        with patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=answer_in_parallel) as client, patch.object(
                self.workspace, '_stage_ai', side_effect=serial_stage):
            report = self.workspace.sync()
        self.assertEqual(report['status'], 'published')
        self.assertEqual(client.call_count, 8)
        self.assertEqual(len(worker_threads), 2)
        self.assertEqual(staging_threads, [get_ident(), get_ident()])
        self.assertTrue(self.workspace.validate()['passed'])

    def test_default_ai_extraction_reads_registered_nested_body_and_appendix(self):
        main = TEX.replace(b'Hello', b'\\input{sections/body}\n\\input{appendix}\n\\input{empty}')
        body = b'Included body.\n\\input{nested}\n'
        (self.root / 'inputs/paper.tar').write_bytes(tar_bytes({
            'main.tex': main, 'sections/body.tex': body,
            'sections/nested.tex': '条件 é😀\r\nNested result.\r\n'.encode(),
            'appendix.tex': b'Appendix evidence.\n',
            'empty.tex': b'',
            'unrelated.tex': b'UNRELATED_PRIVATE_MARKER',
        }))
        empty = answer({'items': [], 'unresolved': []})
        with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=empty) as client:
            report = self.workspace.sync()
        self.assertEqual(report['status'], 'published')
        self.assertEqual(client.call_count, 4)
        for call in client.call_args_list:
            content = call.args[0][-1].content
            sources = {row['path']: row for row in json.loads(content)['sources']}
            self.assertEqual(set(sources), {'main.tex', 'sections/body.tex', 'sections/nested.tex', 'appendix.tex', 'empty.tex'})
            self.assertEqual(sources['sections/nested.tex']['lines'][0], [1, '条件 é😀\r\n'])
            self.assertNotIn('UNRELATED_PRIVATE_MARKER', content)
        self.assertTrue(self.workspace.validate()['passed'])

    def test_duplicate_source_labels_do_not_block_line_cited_ai_extraction(self):
        (self.root / 'inputs/paper.tex').write_bytes(TEX.replace(
            b'Hello', b'\\section{First}\\label{repeated}\nHello.\n\\section{Second}\\label{repeated}\nWorld.'))
        with patch('qecgraph.llm.client.LLMClient.complete_json',
                   return_value=answer({'items': [], 'unresolved': []})) as client:
            report = self.workspace.sync()
        self.assertEqual(client.call_count, 4)
        self.assertEqual(report['inputs'][0]['ai_extraction']['status'], 'complete')
        for call in client.call_args_list:
            source = json.loads(call.args[0][-1].content)['sources'][0]
            self.assertEqual(''.join(row[1] for row in source['lines']).count('\\label{repeated}'), 2)

    def test_missing_http_credentials_leave_offline_sync_available_with_concurrency(self):
        self.configure('provider = "claude_code"', 'provider = "openrouter"')
        self.configure('api_key_env = "OPENROUTER_API_KEY"', 'api_key_env = "QECGRAPH_TEST_UNSET_KEY"')
        self.configure('max_parallel_packages = 1', 'max_parallel_packages = 2')
        (self.root / 'inputs/paper.tex').write_bytes(TEX)
        with patch('qecgraph.llm.providers.http.UrllibTransport.request') as transport:
            report = self.workspace.sync()
            transport.assert_not_called()
        self.assertEqual(report['status'], 'published')
        self.assertTrue(report['inputs'][0]['input_consumed'])

    def test_proposals_left_by_failed_publication_cannot_be_reviewed(self):
        from qecgraph.llm.review import AIReviewError, decide, proposals

        (self.root / 'inputs/paper.tex').write_bytes(TEX)
        empty = answer({'items': [], 'unresolved': []})
        with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=empty), patch.object(
                self.workspace.registry, 'validate', return_value={'passed': False}):
            with self.assertRaisesRegex(ValueError, 'Candidate machine release failed validation'):
                self.workspace.sync()
        orphan = next((self.workspace.registry.root / 'ai/proposals').rglob('*.json'))
        self.assertEqual(proposals(self.root), [])
        with self.assertRaisesRegex(AIReviewError, 'No machine release'):
            decide(self.root, orphan, actor={'id': 'reviewer', 'kind': 'human'}, decision='approve',
                   rationale='checked', checked_scopes=['statement', 'hypotheses', 'dependencies'])

    def test_rebuild_revalidates_legacy_map_without_calling_a_provider(self):
        from qecgraph.core.transactions import writer_lock

        package = self.root / 'inputs/papers.tar'
        package.write_bytes(tar_bytes({'a.tex': TEX, 'b.tex': TEX.replace(b'Hello', b'Supplement')}))
        plan = answer({'status': 'ready', 'documents': [{'path': 'a.tex', 'role': 'main'},
                                                        {'path': 'b.tex', 'role': 'supplement'}],
                       'operations': [{'op': 'use_preamble', 'source': 'a.tex'},
                                      {'op': 'include_body', 'source': 'a.tex'},
                                      {'op': 'append_body', 'source': 'b.tex'}], 'unresolved': []})
        empty = answer({'items': [], 'unresolved': []})
        with patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=[plan, empty, empty, empty, empty]):
            initial = self.workspace.sync()['inputs'][0]

        registry = self.workspace.registry
        manifest_path = next((registry.root / 'derived/normalizations').rglob('manifest.json'))
        manifest = json.loads(manifest_path.read_text())
        manifest.pop('source_map')
        manifest['fallback_reason'] = None
        manifest_path.write_text(json.dumps(manifest))
        with writer_lock(registry.root):
            state, _ = registry.read()
            material = state['materials'][initial['archive_sha256']]
            material.pop('normalization_manifest_sha256')
            material.pop('ai_extraction')
            registry._publish(state)

        self.configure('enabled = true', 'enabled = false')
        with patch('qecgraph.llm.client.LLMClient.complete_json') as client:
            result = self.workspace.rebuild()
            client.assert_not_called()
        row, = result['inputs']
        self.assertTrue(row['processing_completed'])
        self.assertNotEqual(row['normalization_id'], initial['normalization_id'])
        self.assertEqual(row['normalization_sha256'], initial['normalization_sha256'])
        self.assertTrue(self.workspace.validate()['passed'])
