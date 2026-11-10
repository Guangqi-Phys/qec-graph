import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from qecgraph.cli import main


class AICliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['init', '--workspace', str(self.root)]), 0)

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
        self.assertEqual(status['model'], '')
        self.assertFalse(status['configured'])
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
                          .replace('model = ""', 'model = "fake"')
                          .replace('extract_proposals = false', 'extract_proposals = true'))
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
        self.assertEqual(result['count'], 3)
        row = next(row for row in result['proposals'] if row['skill'] == 'extract_theorems')
        self.assertEqual(row['items'], 1)
        self.assertEqual(row['release_id'], report['release_id'])
        self.assertNotIn('thm:a', stdout)
        self.assertNotIn('orphan.json', stdout)

    def test_human_review_requires_the_published_proposal_and_tracks_staleness(self):
        report = self.publish_proposals()
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

    def test_test_reports_missing_model_without_network(self):
        code, stdout, stderr = self.invoke('ai', 'test')
        self.assertEqual(code, 1)
        self.assertEqual(stdout, '')
        self.assertIn('model is empty', stderr)
