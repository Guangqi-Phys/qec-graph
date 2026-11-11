import fcntl
import io
import json
import os
import pty
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from qecgraph.cli import main
from qecgraph.core.progress import reporting, task
from qecgraph.llm.client import LLMClient
from qecgraph.llm.errors import ProviderError
from qecgraph.llm.providers.base import Completion, Message
from qecgraph.workspace import Workspace
from tests.support import ROOT
from tests.unit.domain.test_ai_client import FakeProvider, SCHEMA, config


class CLIProgressTests(unittest.TestCase):
    def test_json_plain_off_and_quiet_have_independent_stream_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            Workspace(directory).prepare()
            for options in (['--progress', 'plain'], ['--progress=off'], ['--progress', 'plain', '--quiet']):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main([*options, 'workspace', 'sync', '--workspace', directory,
                                 '--json', '--no-human'])
                self.assertEqual(code, 0)
                self.assertIn(json.loads(stdout.getvalue())['status'], {'published', 'unchanged'})
                self.assertNotIn('\x1b', stdout.getvalue() + stderr.getvalue())
                if options == ['--progress', 'plain']:
                    self.assertIn('Archiving inbox packages', stderr.getvalue())
                    self.assertIn('Publishing workspace', stderr.getvalue())
                else:
                    self.assertEqual(stderr.getvalue(), '')

    def test_sync_reports_real_package_totals_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            workspace.prepare()
            for name in ('one', 'two'):
                (Path(directory) / 'inputs' / (name + '.tex')).write_text(
                    '\\documentclass{article}\n\\begin{document}' + name + '\\end{document}')
            events = []
            with reporting(events.append), task('Sync workspace'):
                workspace.sync()
            packages = [e for e in events if e.label == 'Checking inbox packages' and e.state == 'running']
            self.assertEqual([(e.completed, e.total) for e in packages], [(0, 2), (1, 2), (2, 2)])
            self.assertTrue(any(e.label == 'one.tex' for e in events))
            publication = next(e for e in events if e.label == 'Publishing workspace')
            self.assertIsNone(publication.total)

    def test_ai_retry_reports_attempt_timeout_and_backoff_without_source_or_credentials(self):
        events = []
        provider = FakeProvider(ProviderError('temporary secret-key', retryable=True),
                                Completion('{"ok":true}', 'model', usage={'input_tokens': 123, 'output_tokens': 7}))
        provider.api_key = 'secret-key'
        with reporting(events.append):
            result = LLMClient(config(), provider=provider, sleeper=lambda _: None).complete_json(
                [Message('user', 'PRIVATE SOURCE BODY')], SCHEMA)
        self.assertEqual(result.attempts, 2)
        waiting = [e.detail for e in events if e.label == 'Waiting for AI provider']
        self.assertTrue(any('attempt 1/3' in text and 'timeout 10s' in text for text in waiting))
        self.assertTrue(any('attempt 2/3' in text for text in waiting))
        self.assertTrue(any(e.label == 'Waiting to retry AI request' for e in events))
        self.assertTrue(all(e.kind == 'ai' for e in events))
        self.assertTrue(any('123 input tokens | 7 output tokens' == e.detail for e in events))
        self.assertNotIn('PRIVATE SOURCE BODY', repr(events))
        self.assertNotIn('secret-key', repr(events))

    def test_real_pty_animates_while_stdout_is_redirected_and_cleans_up_on_interrupt(self):
        code = '''
import sys, time
from qecgraph.cli import main, HANDLERS
from qecgraph.cli.render import print_json
from qecgraph.core.progress import phase, task
def run(args):
    with task('Checking packages', total=3, unit='packages') as progress:
        progress.advance()
        with task('Waiting for AI provider', detail='attempt 1/3 | timeout 10s', kind='ai'):
            time.sleep(0.35)
            if sys.argv[1] == 'interrupt':
                raise KeyboardInterrupt
    print_json({'ok': True})
    return 0
HANDLERS['doctor'] = run
raise SystemExit(main(['doctor', '--json', '--color', 'never']))
'''
        for outcome in ('success', 'interrupt'):
            with self.subTest(outcome=outcome):
                master, slave = pty.openpty()
                process = None
                try:
                    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 76, 0, 0))
                    env = dict(os.environ, TERM='xterm-256color', PYTHONPATH=str(ROOT))
                    process = subprocess.Popen([sys.executable, '-c', code, outcome], cwd=ROOT, env=env,
                                               stdout=subprocess.PIPE, stderr=slave, text=True)
                    os.close(slave)
                    slave = None
                    chunks = []

                    def drain():
                        while True:
                            try:
                                chunk = os.read(master, 65536)
                            except OSError:
                                break
                            if not chunk:
                                break
                            chunks.append(chunk)

                    reader = threading.Thread(target=drain, daemon=True)
                    reader.start()
                    stdout, _ = process.communicate(timeout=10)
                    reader.join(timeout=5)
                    self.assertFalse(reader.is_alive())
                    output = b''.join(chunks).decode('utf-8')
                    self.assertGreater(output.count('Waiting for provider'), 1)
                    self.assertIn('AI ', output)
                    self.assertIn('33.3%', output)
                    self.assertIn('1/3 packages', output)
                    self.assertNotIn('100.0%', output)
                    self.assertNotIn('\x1b', stdout)
                    if outcome == 'success':
                        self.assertEqual(process.returncode, 0)
                        self.assertEqual(json.loads(stdout), {'ok': True})
                        self.assertIn('doctor: OK', output)
                        self.assertTrue(output.endswith('\r\n'))
                    else:
                        self.assertEqual(process.returncode, 130)
                        self.assertEqual(json.loads(stdout)['error']['code'], 'INTERRUPTED')
                        self.assertIn('interrupted', output)
                        self.assertTrue(output.endswith('\r\n'))
                finally:
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.communicate()
                    os.close(master)
                    if slave is not None:
                        os.close(slave)

    def test_help_and_version_stay_immediate_and_free_of_progress(self):
        for args in (['help'], ['version', '--progress', 'plain']):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(args), 0)
            self.assertEqual(stderr.getvalue(), '')
            self.assertNotIn('\x1b', stdout.getvalue())

    def test_early_failure_restores_progress_context_for_the_next_invocation(self):
        with patch.dict('qecgraph.cli.HANDLERS', {'doctor': lambda _: (_ for _ in ()).throw(ValueError('broken'))}):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(['doctor', '--json', '--progress', 'plain']), 1)
            self.assertEqual(json.loads(stdout.getvalue())['error']['message'], 'broken')
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(main(['version']), 0)
        self.assertEqual(stderr.getvalue(), '')
