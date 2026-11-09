import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from qecgraph.cli import main


class CLIContractTests(unittest.TestCase):
    def test_installed_entry_point_help_version_and_usage_status(self):
        from qecgraph import __version__

        def run(*args):
            return subprocess.run([sys.executable, '-m', 'qecgraph', *args], text=True,
                                  capture_output=True, timeout=5)

        quick = run()
        self.assertEqual(quick.returncode, 0, quick.stderr)
        self.assertIn('mcp serve', quick.stdout)
        version = run('--version')
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), f'qec-graph {__version__}')
        self.assertEqual(run('version').stdout, version.stdout)
        self.assertIn('--include-candidates', run('help', 'context').stdout)
        help_text = run('--help').stdout
        for name in ('deps', 'impact', 'context'):
            self.assertIn(f'    {name} ', help_text)
        for args in [('unknown',), ('help', 'unknown'), ('ingest',)]:
            result = run(*args)
            self.assertEqual(result.returncode, 64, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertIn('--help', result.stderr)

    def test_bad_json_command_fields_report_input_errors_before_writing(self):
        cases = [
            (['review', '--actor-id', 'test'], {}, 'changes, rationale'),
            (['review', '--actor-id', 'test'], {'changes': [None], 'rationale': 'test'}, 'record object'),
            (['claim-link'], {'link_id': 'link:test'}, 'claim_id, source_selector, source_version_id'),
            (['check-experiment'], {'record': [], 'metric': {}}, 'Experiment record needs a data object'),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / 'input.json'
            for command, body, expected in cases:
                with self.subTest(command=command, body=body):
                    payload.write_text(json.dumps(body), encoding='utf-8')
                    args = [*command, str(payload)]
                    if command[0] != 'check-experiment':
                        args += ['--corpus', str(root / 'corpus')]
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        self.assertEqual(main(args), 1)
                    self.assertEqual(stdout.getvalue(), '')
                    self.assertIn(expected, json.loads(stderr.getvalue())['error'])
                    self.assertFalse((root / 'corpus').exists())
