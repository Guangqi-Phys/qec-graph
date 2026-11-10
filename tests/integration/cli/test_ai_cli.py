import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

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

    def test_proposals_lists_artifacts_without_exposing_content(self):
        target = self.root / 'machine/ai/proposals/source'
        target.mkdir(parents=True)
        (target / 'p.json').write_text(json.dumps({'schema': 'qecgraph.ai.proposal',
                                                   'skill': 'extract_theorems',
                                                   'review_status': 'proposed',
                                                   'items': [{'label': 'thm:a'}]}), encoding='utf-8')
        code, stdout, stderr = self.invoke('ai', 'proposals', '--json')
        self.assertEqual((code, stderr), (0, ''))
        result = json.loads(stdout)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['proposals'][0]['skill'], 'extract_theorems')
        self.assertNotIn('thm:a', stdout)

    def test_test_reports_missing_model_without_network(self):
        code, stdout, stderr = self.invoke('ai', 'test')
        self.assertEqual(code, 1)
        self.assertEqual(stdout, '')
        self.assertIn('model is empty', stderr)
