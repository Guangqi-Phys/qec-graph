import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from qecgraph.cli import main
from qecgraph.llm.config import DEFAULT_MODEL


class AICliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.enterContext(patch.dict('os.environ', {'OPENROUTER_API_KEY': ''}))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch(
                'qecgraph.llm.client.LLMClient.complete_json') as complete:
            self.assertEqual(main(['init', '--workspace', str(self.root)]), 0)
            complete.assert_not_called()

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([*args, '--workspace', str(self.root)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_status_and_config_do_not_expose_keys_or_contact_a_provider(self):
        code, stdout, stderr = self.invoke('ai', 'status', '--json')
        self.assertEqual((code, stderr), (0, ''))
        status = json.loads(stdout)
        self.assertEqual(status['provider'], 'openrouter')
        self.assertEqual(status['model'], 'deepseek/deepseek-v4.1-flash-1017')
        self.assertFalse(status['configured'])
        self.assertTrue(status['structure_fallback'])
        self.assertTrue(status['extract_proposals'])
        self.assertNotIn('secret', stdout.lower())
        self.assertEqual(status['config_mode'], '0o600')
        self.assertTrue(status['config_private'])

        code, stdout, stderr = self.invoke('ai', 'config', '--json')
        self.assertEqual((code, stderr), (0, ''))
        config = json.loads(stdout)
        self.assertEqual(config['provider'], 'openrouter')
        self.assertNotIn('api_key_value', stdout)
        self.assertEqual((self.root / 'qecgraph.toml').stat().st_mode & 0o777, 0o600)

    def publish_proposals(self):
        from qecgraph.llm.client import LLMResult
        from qecgraph.workspace import Workspace
        from tests.unit.parsing.test_source_package import TEX

        config = self.root / 'qecgraph.toml'
        config.write_text(config.read_text().replace('provider = "openrouter"', 'provider = "claude_code"')
                          .replace(f'model = "{DEFAULT_MODEL}"', 'model = "fake"'))
        (self.root / 'inputs/main.tex').write_bytes(TEX)

        def complete(messages, schema, **kwargs):
            is_theorem = 'label' in schema['properties']['items']['items']['properties']
            data = {'items': [{'label': 'thm:a', 'statement': 'Hello', 'hypotheses': [],
                               'source_refs': ['main.tex:2']}] if is_theorem else [], 'unresolved': []}
            return LLMResult(data, json.dumps(data), 'fake', {}, None, 1, False, 'test-run', 'f' * 64)

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'offline-test-key'}), patch(
                'qecgraph.llm.client.LLMClient.complete_json', side_effect=complete):
            return Workspace(self.root).sync()

    def test_proposals_lists_only_published_artifacts_without_exposing_content(self):
        self.assertEqual(json.loads(self.invoke('ai', 'proposals', '--json')[1])['count'], 0)
        report = self.publish_proposals()
        orphan = self.root / 'machine/ai/proposals/orphan.json'
        orphan.write_text('{"schema":"qecgraph.ai.proposal","review_status":"proposed"}')
        code, stdout, stderr = self.invoke('ai', 'proposals', '--json')
        self.assertEqual((code, stderr), (0, ''))
        result = json.loads(stdout)
        self.assertEqual(result['count'], 4)
        row = next(row for row in result['proposals'] if row['skill'] == 'extract_theorems')
        self.assertEqual(row['items'], 1)
        self.assertEqual(row['release_id'], report['release_id'])
        self.assertNotIn('thm:a', stdout)
        self.assertNotIn('orphan.json', stdout)

    def test_human_review_requires_the_published_proposal_and_tracks_staleness(self):
        report = self.publish_proposals()
        from qecgraph.workspace_query import WorkspaceSession
        pinned = WorkspaceSession(self.root / 'machine', profile='research')
        items = json.loads(self.invoke('ai', 'proposals', '--json')[1])['proposals']
        proposal = next(item['path'] for item in items if item['skill'] == 'extract_theorems')
        approval = ('--actor-id', 'ada', '--actor-kind', 'human', '--decision', 'approve',
                    '--rationale', 'checked sources', '--checked-scope', 'statement',
                    '--checked-scope', 'hypotheses', '--checked-scope', 'dependencies')
        code, stdout, stderr = self.invoke('ai', 'decide', proposal, *approval)
        self.assertEqual((code, stderr), (0, ''))
        review = json.loads(stdout)
        self.assertEqual(review['status'], 'human_approved')
        self.assertEqual(review['release_id'], report['release_id'])
        self.assertEqual(review['snapshot_id'], report['inputs'][0]['source_snapshot_id'])
        self.assertEqual(review['scope'], 'AI proposal review only; no automatic research-record application')
        current = WorkspaceSession(self.root / 'machine', profile='research')
        self.assertNotEqual(current.release, pinned.release)
        self.assertEqual(pinned.invoke('qec_status', {})['data']['ai_review_decisions']['registered'], 0)
        self.assertEqual(current.invoke('qec_status', {})['data']['ai_review_decisions']['registered'], 1)
        self.assertEqual(review['actor_authentication'], 'self_asserted_local_identity')
        code, stdout, stderr = self.invoke('ai', 'decisions', '--json')
        self.assertEqual((code, stderr), (0, ''))
        self.assertEqual(json.loads(stdout)['decisions'][0]['effective_status'], 'human_approved')

        target = Path(proposal)
        value = json.loads(target.read_text())
        value['items'][0]['statement'] = 'altered'
        target.write_text(json.dumps(value))
        self.assertNotEqual(self.invoke('ai', 'decide', proposal, *approval)[0], 0)
        self.assertEqual(len(list((self.root / 'machine/ai/reviews').glob('*.json'))), 1)
        decisions = json.loads(self.invoke('ai', 'decisions', '--json')[1])['decisions']
        self.assertEqual(decisions[0]['status'], 'human_approved')
        self.assertEqual(decisions[0]['effective_status'], 'stale')
        from qecgraph.workspace import Workspace
        self.assertFalse(Workspace(self.root).validate()['passed'])

    def test_test_reports_missing_key_without_network(self):
        with patch('qecgraph.llm.providers.http.UrllibTransport.request') as transport:
            code, stdout, stderr = self.invoke('ai', 'test')
            transport.assert_not_called()
        self.assertEqual(code, 1)
        self.assertEqual(stdout, '')
        self.assertIn('missing API key', stderr)

    def test_default_sync_extracts_all_four_skills_after_only_setting_key(self):
        from qecgraph.llm.providers.base import HttpResult
        from tests.unit.parsing.test_source_package import TEX

        (self.root / 'inputs/paper.tex').write_bytes(TEX)
        body = {'choices': [{'message': {'content': '{"items": [], "unresolved": []}'}}],
                'model': 'offline-fixture'}
        response = HttpResult(200, {}, json.dumps(body).encode())
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-fixture-key'}), patch(
                'qecgraph.llm.providers.http.UrllibTransport.request', return_value=response) as transport:
            code, stdout, stderr = self.invoke('sync', '--json')
            self.assertEqual((code, stderr), (0, ''))
            report = json.loads(stdout)
            extraction = report['inputs'][0]['ai_extraction']
            self.assertEqual(extraction['status'], 'complete')
            self.assertEqual({row['skill'] for row in extraction['written']}, {
                'extract_theorems', 'extract_assumptions', 'extract_data', 'extract_thoughts'})
            self.assertEqual(transport.call_count, 4)
            for call in transport.call_args_list:
                self.assertEqual(call.args[1], 'https://openrouter.ai/api/v1/chat/completions')
                self.assertEqual(json.loads(call.kwargs['body'])['model'], 'deepseek/deepseek-v4.1-flash-1017')
