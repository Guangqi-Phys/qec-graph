import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qecgraph.store import current_snapshot, ingest, recover_store, validate_snapshot
from qecgraph.transactions import writer_lock


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
        with writer_lock(self.store):
            result = subprocess.run([sys.executable, '-m', 'qecgraph', 'ingest', str(self.entry), '--project-id', 'publish',
                                     '--out', str(self.store)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 5)
            self.assertIn('Another writer', result.stderr)
        self.assertEqual(current_snapshot(self.store), original)
        # os._exit bypasses Python cleanup; the kernel must still release flock.
        code = 'import os,sys; from qecgraph.transactions import writer_lock\nwith writer_lock(sys.argv[1]): os._exit(7)'
        crashed = subprocess.run([sys.executable, '-c', code, str(self.store)])
        self.assertEqual(crashed.returncode, 7)
        self.assertTrue(ingest(self.entry, 'publish', self.store)['published'])

    def test_recovery_only_removes_marked_tool_builds(self):
        ingest(self.entry, 'publish', self.store)
        owned = self.store / 'snapshots/.building-owned'
        owned.mkdir()
        (owned / '.qecgraph-building.json').write_text(json.dumps({'format': 'qecgraph.building.v1', 'snapshot_id': 'f' * 64}))
        unrelated = self.store / 'snapshots/.building-user-files'
        unrelated.mkdir()
        (unrelated / 'important.txt').write_text('keep')
        report = recover_store(self.store, remove_abandoned=True)
        self.assertIn(str(owned), report['removed'])
        self.assertIn(str(unrelated), report['unrecognized'])
        self.assertTrue((unrelated / 'important.txt').exists())
        self.assertTrue(report['current']['passed'])


if __name__ == '__main__':
    unittest.main()
