import json
import os
from select import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from qecgraph.registry import Registry
from qecgraph.store import current_snapshot, ingest, recover_store, validate_snapshot
from qecgraph.core.transactions import ManagedDataError, writer_lock
from qecgraph.workspace import Workspace


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.entry = self.root / 'main.tex'
        self.entry.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{a}A.\end{lemma}')
        self.store = self.root / 'store'

    def test_strict_partial_stages_without_changing_current_and_legacy_still_publishes(self):
        ingest(self.entry, 'publish', self.store)
        original = current_snapshot(self.store)
        self.entry.write_text(self.entry.read_text() + r'\input{missing}')
        staged = ingest(self.entry, 'publish', self.store, strict=True)
        self.assertFalse(staged['published'])
        self.assertEqual(staged['publication_status'], 'staged_partial')
        self.assertEqual(Path(staged['snapshot']).parent.name, 'staging')
        self.assertTrue(validate_snapshot(staged['snapshot'])['passed'])
        self.assertEqual(current_snapshot(self.store), original)
        legacy = ingest(self.entry, 'publish', self.store)
        self.assertTrue(legacy['published'])
        self.assertEqual(legacy['snapshot_id'], staged['snapshot_id'])
        self.assertNotEqual(current_snapshot(self.store), original)

    def test_strict_initial_store_has_no_current_and_cannot_change_project(self):
        self.entry.write_text(self.entry.read_text() + r'\input{missing}')
        staged = ingest(self.entry, 'publish', self.store, strict=True)
        self.assertFalse((self.store / 'CURRENT.json').exists())
        self.assertTrue(Path(staged['snapshot']).exists())
        with self.assertRaisesRegex(ValueError, 'different project'):
            ingest(self.entry, 'other', self.store, strict=True)

    def test_another_process_cannot_write_and_lock_is_released_after_crash(self):
        ingest(self.entry, 'publish', self.store)
        original = current_snapshot(self.store)
        self.entry.write_text(self.entry.read_text().replace('A.', 'B.'))
        arguments = ['ingest', str(self.entry), '--project-id', 'publish', '--out', str(self.store)]
        waiting_writer = dedent('''
            import sys
            from qecgraph import store
            from qecgraph.cli import main

            ingest_locked = store._ingest_locked

            def wait_under_lock(*args, **kwargs):
                print('ready', flush=True)
                if sys.stdin.readline() != '\\n':
                    raise RuntimeError('No resume signal from test')
                return ingest_locked(*args, **kwargs)

            store._ingest_locked = wait_under_lock
            raise SystemExit(main(sys.argv[1:]))
        ''')
        with subprocess.Popen([sys.executable, '-c', waiting_writer, *arguments], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as first:
            try:
                ready, _, _ = select([first.stdout], [], [], 10)
                self.assertTrue(ready, 'First ingest did not reach its writer lock')
                self.assertEqual(first.stdout.readline(), 'ready\n')
                result = subprocess.run([sys.executable, '-m', 'qecgraph', *arguments], capture_output=True,
                                        text=True, timeout=10)
                self.assertEqual(result.returncode, 5)
                self.assertIn('Another writer', result.stderr)
                self.assertEqual(current_snapshot(self.store), original)
                _, stderr = first.communicate('\n', timeout=15)
                self.assertEqual(first.returncode, 0, stderr)
            finally:
                if first.poll() is None:
                    first.kill()
        self.assertNotEqual(current_snapshot(self.store), original)
        # os._exit bypasses Python cleanup; the kernel must still release flock.
        code = 'import os,sys; from qecgraph.core.transactions import writer_lock\nwith writer_lock(sys.argv[1]): os._exit(7)'
        crashed = subprocess.run([sys.executable, '-c', code, str(self.store)])
        self.assertEqual(crashed.returncode, 7)
        self.assertTrue(ingest(self.entry, 'publish', self.store)['published'])

    def test_first_ingest_retries_a_lock_only_directory(self):
        with patch('qecgraph.store.atomic_json', side_effect=OSError('interrupted initial marker write')):
            with self.assertRaisesRegex(OSError, 'interrupted initial marker write'):
                ingest(self.entry, 'publish', self.store)
        self.assertEqual({path.name for path in self.store.iterdir()}, {'.writer.lock'})
        with writer_lock(self.store):
            result = subprocess.run([sys.executable, '-m', 'qecgraph', 'ingest', str(self.entry), '--project-id',
                                     'publish', '--out', str(self.store), '--json'], capture_output=True, text=True, timeout=10)
            self.assertEqual((result.returncode, result.stderr), (5, ''))
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'CONFLICT')
        retry = ingest(self.entry, 'publish', self.store)
        self.assertTrue(retry['published'])
        self.assertTrue(validate_snapshot(current_snapshot(self.store))['passed'])

    def test_current_cannot_point_at_a_snapshot_outside_the_published_inventory(self):
        ingest(self.entry, 'publish', self.store)
        current = current_snapshot(self.store)
        path = self.store / 'CURRENT.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        path.write_text(json.dumps({**original, 'path': f'staging/{current.name}'}), encoding='utf-8')
        with self.assertRaisesRegex(ManagedDataError, 'CURRENT does not identify a stored snapshot'):
            current_snapshot(self.store)
        path.write_text(json.dumps(original), encoding='utf-8')
        outside = self.root / 'another' / current.name
        outside.parent.mkdir()
        current.rename(outside)
        current.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ManagedDataError, 'Snapshot paths must be local directories'):
            current_snapshot(self.store)

    def test_recovery_only_removes_marked_tool_builds(self):
        ingest(self.entry, 'publish', self.store)
        owned = self.store / 'snapshots/.building-owned'
        owned.mkdir()
        (owned / '.qecgraph-building.json').write_text(json.dumps({'format': 'qecgraph.building.v1', 'snapshot_id': 'f' * 64}))
        unrelated = self.store / 'snapshots/.building-user-files'
        unrelated.mkdir()
        (unrelated / 'important.txt').write_text('keep')
        external_marker = self.root / 'not-a-store-marker.json'
        external_marker.write_bytes((owned / '.qecgraph-building.json').read_bytes())
        copies = []
        for name, marker in (('symlink', lambda p: p.symlink_to(external_marker)),
                             ('hardlink', lambda p: p.hardlink_to(external_marker)),
                             ('malformed', lambda p: p.write_text('[]', encoding='utf-8'))):
            directory = self.store / 'snapshots' / ('.building-' + name)
            directory.mkdir()
            (directory / 'important.txt').write_text('keep', encoding='utf-8')
            marker(directory / '.qecgraph-building.json')
            copies.append(directory)
        report = recover_store(self.store, remove_abandoned=True)
        self.assertIn(str(owned), report['removed'])
        self.assertEqual(set(report['unrecognized']), {str(path) for path in (unrelated, *copies)})
        for path in (unrelated, *copies):
            self.assertEqual((path / 'important.txt').read_text(), 'keep')
        self.assertTrue(external_marker.exists())
        self.assertTrue(report['current']['passed'])

    def test_publication_retry_after_failed_current_replace(self):
        ingest(self.entry, 'publish', self.store)
        registry = Registry(self.root / 'corpus')
        registry.register_source('work:first', 'version:first', self.store)
        workspace = Workspace(self.root / 'workspace')
        workspace.init(no_ingest=True)
        (workspace.root / 'inputs/paper.tex').write_bytes(self.entry.read_bytes())
        self.entry.write_text(self.entry.read_text().replace('A.', 'B.'))

        cases = [
            (self.store, lambda: ingest(self.entry, 'publish', self.store)),
            (registry.root, lambda: registry.register_source('work:second', 'version:second', self.store)),
            (workspace.registry.root, workspace.sync),
        ]
        replace = os.replace
        for root, publish in cases:
            current = root / 'CURRENT.json'
            before = current.read_bytes()

            def reject_current(source, target):
                if Path(target) == current:
                    raise OSError('Interrupted CURRENT replacement')
                return replace(source, target)

            with self.subTest(root=root.name):
                with patch('qecgraph.core.transactions.os.replace', side_effect=reject_current):
                    with self.assertRaisesRegex(OSError, 'Interrupted CURRENT'):
                        publish()
                self.assertEqual(current.read_bytes(), before)
                self.assertEqual(list(root.glob('.CURRENT.json*')), [])
                publish()
                self.assertNotEqual(current.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
