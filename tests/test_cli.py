import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import chdir, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from qecgraph.cli import main
from qecgraph.store import ingest
from qecgraph.transactions import writer_lock
from qecgraph.workspace import Workspace


class CLIContractTests(unittest.TestCase):
    def test_quiet_and_color_control_reports_without_hiding_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            Workspace(root).init(no_ingest=True)

            def run(*args):
                return subprocess.run([sys.executable, '-m', 'qecgraph', *args, '--workspace', str(root)],
                                      capture_output=True, text=True, timeout=5)

            with patch.dict('os.environ', {'FORCE_COLOR': '1', 'NO_COLOR': '1'}):
                normal = run('status')
                forced = run('--color', 'always', 'workspace', 'status')
                never = run('workspace', 'status', '--color=never')
            self.assertEqual((normal.returncode, forced.returncode, never.returncode), (0, 0, 0))
            self.assertNotIn('\x1b', normal.stdout)
            self.assertIn('\x1b[32m', forced.stdout)
            self.assertNotIn('\x1b', never.stdout)

            quiet = run('status', '--quiet')
            self.assertEqual((quiet.returncode, quiet.stdout, quiet.stderr), (0, '', ''))
            requested = run('workspace', '--quiet', 'status', '--json')
            self.assertEqual(requested.returncode, 0, requested.stderr)
            self.assertEqual(json.loads(requested.stdout)['status'], 'ok')

            broken = root / 'inputs/broken.zip'
            broken.write_bytes(b'PK\x03\x04broken')
            failed = run('sync', '--no-human', '--quiet')
            self.assertEqual(failed.returncode, 2, failed.stderr)
            self.assertEqual(failed.stdout, '')
            self.assertIn('ERROR', failed.stderr)
            self.assertTrue(broken.is_file())

    def test_grouped_commands_share_handlers_and_show_the_invoked_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            Workspace(root).init(no_ingest=True)

            def run(*args):
                return subprocess.run([sys.executable, '-m', 'qecgraph', *args],
                                      capture_output=True, text=True, timeout=5)

            scope = ('--workspace', str(root))
            flat = run('status', '--json', *scope)
            self.assertEqual(flat.returncode, 0, flat.stderr)
            for args in (('workspace', 'status', '--json'), ('workspace', '--json', 'status')):
                nested = run(*args, *scope)
                self.assertEqual(nested.returncode, 0, nested.stderr)
                self.assertEqual(json.loads(nested.stdout), json.loads(flat.stdout))

            help_result = run('help', 'mcp', 'serve')
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn('usage: qec-graph mcp serve', help_result.stdout)
            self.assertIn('--machine', help_result.stdout)

            with patch.dict('os.environ', {'QECGRAPH_DEPRECATIONS': '0'}):
                quiet_alias = run('mcp-config', *scope)
            with patch.dict('os.environ', {'QECGRAPH_DEPRECATIONS': '1'}):
                warned_alias = run('mcp-config', *scope)
                canonical = run('mcp', 'config', *scope)
                shortcut = run('status', '--json', *scope)
            self.assertEqual(quiet_alias.returncode, 0)
            self.assertEqual(warned_alias.returncode, 0)
            self.assertEqual(canonical.returncode, 0)
            self.assertEqual(quiet_alias.stderr, '')
            self.assertIn('use qec-graph mcp config', warned_alias.stderr)
            self.assertEqual(canonical.stderr, '')
            self.assertEqual(shortcut.stderr, '')
            config = json.loads(canonical.stdout)
            self.assertEqual(json.loads(warned_alias.stdout), config)
            self.assertIn('serve', config['mcpServers']['qecgraph']['args'])
            self.assertIn('mcp-config', run('help', 'aliases').stdout)

            (root / 'list').write_text('{}', encoding='utf-8')
            stderr = io.StringIO()
            with chdir(root), redirect_stderr(stderr):
                self.assertEqual(main(['review', 'list', '--corpus', 'example', '--actor-id', 'fixture']), 1)
            self.assertIn('changes, rationale', stderr.getvalue())
            self.assertFalse((root / 'example').exists())

    def test_structured_cli_errors_keep_status_and_stream_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = str(Path(temporary) / 'missing.json')
            args = ['check-css', '--hx', missing, '--hz', missing]
            for options in (['--json', *args], [*args, '--json']):
                with self.subTest(options=options):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        self.assertEqual(main(options), 4)
                    self.assertEqual(stderr.getvalue(), '')
                    report = json.loads(stdout.getvalue())
                    self.assertEqual(report['envelope_version'], 1)
                    self.assertFalse(report['ok'])
                    self.assertEqual(report['error']['code'], 'NOT_FOUND')
                    self.assertEqual(report['error']['command'], 'check-css')
                    self.assertEqual(report['error']['details'], {'path': missing})

            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(['--json', 'mcp', 'serve']), 64)
            self.assertEqual(stdout.getvalue(), '')
            error = json.loads(stderr.getvalue())['error']
            self.assertEqual(error['code'], 'USAGE')
            self.assertEqual(error['command'], 'serve-mcp')

    def test_unexpected_cli_failures_only_show_traceback_in_debug_mode(self):
        with patch.dict('qecgraph.cli.HANDLERS', {'doctor': lambda _: {}['unexpected']}):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(['doctor', '--json']), 1)
            self.assertEqual(stderr.getvalue(), '')
            report = json.loads(stdout.getvalue())['error']
            self.assertEqual(report['code'], 'INTERNAL_ERROR')
            self.assertNotIn('unexpected', report['message'])
            self.assertIn('--debug', report['hint'])
            with self.assertRaises(KeyError):
                main(['--debug', 'doctor'])

    def test_managed_config_pointer_and_writer_errors_are_actionable(self):
        def report(args, exit_code, error_code, path):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main([*args, '--json']), exit_code)
            self.assertEqual(stderr.getvalue(), '')
            result = json.loads(stdout.getvalue())['error']
            self.assertEqual(result['code'], error_code)
            self.assertEqual(result['details']['path'], str(path))
            self.assertTrue(result['hint'])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            Workspace(root).init(no_ingest=True)
            pointer = root / 'machine/CURRENT.json'
            original = pointer.read_bytes()
            lock = root / '.qecgraph'
            with writer_lock(lock):
                report(['sync', '--workspace', str(root)], 5, 'CONFLICT', lock)
            self.assertEqual(pointer.read_bytes(), original)

            config = root / 'qecgraph.toml'
            config.write_text('[broken', encoding='utf-8')
            report(['status', '--workspace', str(root)], 1, 'INVALID_CONFIG', config)

            pointer.write_text('[]', encoding='utf-8')
            report(['snapshot', 'list', '--workspace', str(root)], 1, 'STORAGE_ERROR', pointer)
            self.assertEqual(pointer.read_text(), '[]')

            store = root / 'store'
            store.mkdir()
            current = store / 'CURRENT.json'
            current.write_text('{"format":"qecgraph.current.v1","path":[]}', encoding='utf-8')
            report(['validate', '--store', str(store)], 1, 'STORAGE_ERROR', current)

    def test_doctor_and_snapshot_list_distinguish_current_and_prepared_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = Workspace(root)
            current = workspace.init(no_ingest=True)['release_id']
            state, _ = workspace.registry.read()
            candidate = workspace.registry.prepare_publication({**state, 'candidate_fixture': True})
            pointer = root / 'machine/CURRENT.json'
            original = pointer.read_bytes()

            def report(*args, expected=0):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(main(args), expected)
                self.assertEqual(stderr.getvalue(), '')
                return json.loads(stdout.getvalue())

            health = report('doctor', '--workspace', str(root), '--json')
            self.assertEqual(health['release_id'], current)
            self.assertEqual(health['checks']['archive_inventory']['blobs'], 0)
            rows = report('snapshot', 'list', '--workspace', str(root))
            self.assertEqual(rows['current'], current)
            self.assertEqual(set(rows['stored_states']), {current, candidate})
            self.assertTrue(rows['includes_unpublished_candidates'])
            self.assertEqual(pointer.read_bytes(), original)
            pointer.write_text('{', encoding='utf-8')
            diagnosis = report('doctor', '--workspace', str(root), '--json', expected=1)
            self.assertEqual(diagnosis['checks']['machine/CURRENT.json']['status'], 'error')
            self.assertEqual(pointer.read_text(), '{')

            entry = root / 'paper.tex'
            entry.write_text(r'\section{First}', encoding='utf-8')
            store = root / 'store'
            first = ingest(entry, 'doctor-test', store)['snapshot_id']
            entry.write_text(r'\section{Second}', encoding='utf-8')
            second = ingest(entry, 'doctor-test', store)['snapshot_id']
            rows = report('snapshot', 'list', '--store', str(store))
            self.assertEqual(rows['current'], second)
            self.assertEqual(set(rows['snapshots']), {first, second})

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
        self.assertIn('qec-graph query search HGP', run('help', 'query', 'search').stdout)
        self.assertIn('130  interrupted', run('help', 'errors').stdout)
        self.assertIn('MCP reserves stdout', run('help', 'json').stdout)
        for module, program in (('splitter', 'qec-latex-split'), ('mcp_server', 'qecgraph-mcp')):
            result = subprocess.run([sys.executable, '-m', f'qecgraph.{module}', '--help'], text=True,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith(f'usage: {program} '), result.stdout)
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
