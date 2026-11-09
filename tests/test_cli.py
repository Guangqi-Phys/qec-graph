import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from qecgraph.cli import main


class CLIContractTests(unittest.TestCase):
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
