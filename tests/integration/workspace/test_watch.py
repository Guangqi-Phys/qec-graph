import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qecgraph.core.graph import read_json
from qecgraph.store import current_snapshot, ingest
from qecgraph.core.transactions import writer_lock
from qecgraph.watch import Watcher


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.paper = self.root / 'paper'
        self.paper.mkdir()
        self.entry = self.paper / 'main.tex'
        self.entry.write_text(r'\newtheorem{lemma}{Lemma}\input{leaf}')
        self.leaf = self.paper / 'leaf.tex'
        self.leaf.write_text(r'\begin{lemma}\label{a}Alpha.\end{lemma}')
        self.store = self.root / 'watched'

    def watcher(self, **kwargs):
        return Watcher(self.entry, 'watch', self.store, retry_interval=0, **kwargs)

    def test_debounce_ignores_editor_files_and_coalesces_batch_saves(self):
        watcher = self.watcher(debounce=1)
        self.assertIsNone(watcher.poll(0))
        self.assertEqual(watcher.poll(1)['event'], 'built')
        for name in ('leaf.tex~', '.leaf.tex.swp', '.#leaf.tex', 'editor.tmp'):
            (self.paper / name).write_text('temporary')
        self.assertIsNone(watcher.poll(2))
        self.leaf.write_text(self.leaf.read_text().replace('Alpha', 'Omega'))
        self.assertIsNone(watcher.poll(3))
        self.leaf.write_text(self.leaf.read_text().replace('Omega', 'Final'))
        self.assertIsNone(watcher.poll(3.5))
        event = watcher.poll(4.5)
        self.assertEqual(event['event'], 'built')
        self.assertEqual(watcher.build_count, 2)
        explicit = ingest(self.entry, 'watch', self.root / 'explicit')
        self.assertEqual(event['result']['snapshot_id'], explicit['snapshot_id'])
        self.assertIsNone(watcher.poll(6))

    def test_lock_failure_is_not_accepted_and_same_inputs_retry(self):
        ingest(self.entry, 'watch', self.store)
        watcher = self.watcher(debounce=0)
        with writer_lock(self.store):
            failure = watcher.poll(0)
        self.assertEqual(failure['event'], 'build_failed')
        self.assertIsNone(watcher.accepted)
        self.assertEqual(watcher.poll(1)['event'], 'built')
        self.assertIsNotNone(watcher.accepted)

    def test_strict_partial_and_new_include_recover_through_full_reconciliation(self):
        watcher = self.watcher(debounce=0, strict=True)
        watcher.poll(0)
        previous = current_snapshot(self.store)
        self.leaf.unlink()
        partial = watcher.poll(1)
        self.assertEqual(partial['result']['publication_status'], 'staged_partial')
        self.assertEqual(current_snapshot(self.store), previous)
        self.leaf.write_text(r'\begin{lemma}\label{a}Restored.\end{lemma}')
        restored = watcher.poll(2)
        self.assertEqual(restored['event'], 'built')
        self.assertTrue(restored['result']['published'])
        self.assertNotEqual(current_snapshot(self.store), previous)
        self.assertIn('previous_unresolved_dependencies', restored['result']['incremental']['fallback_reasons'])

    def test_external_sidecar_is_tracked_and_cli_once_uses_the_same_pipeline(self):
        annotations = self.root / 'annotations.json'
        annotations.write_text('{"schema_version":"qecgraph.annotations"}')
        watcher = self.watcher(debounce=0, annotations_path=annotations)
        first = watcher.poll(0)
        annotations.write_text(json.dumps({'schema_version': 'qecgraph.annotations', 'annotations': [
            {'target': 'label:a', 'review_status': 'draft', 'data': {'note': 'changed'}}]}))
        second = watcher.poll(1)
        self.assertNotEqual(first['result']['snapshot_id'], second['result']['snapshot_id'])
        proc = subprocess.run([sys.executable, '-m', 'qecgraph', 'watch', str(self.entry), '--project-id', 'watch',
                               '--out', str(self.root / 'cli'), '--annotations', str(annotations), '--once'],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        values = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(values[0]['event'], 'built')
        self.assertEqual(values[-1]['event'], 'stopped')
        self.assertEqual(values[0]['result']['snapshot_id'], second['result']['snapshot_id'])
        self.assertEqual(read_json(Path(values[0]['result']['snapshot']) / 'graph.json'), read_json(Path(second['result']['snapshot']) / 'graph.json'))


if __name__ == '__main__':
    unittest.main()
