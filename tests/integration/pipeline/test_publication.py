import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.store import current_snapshot, ingest, validate_snapshot
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

    def test_snapshot_build_retries_a_lock_only_directory(self):
        with patch('qecgraph.store.atomic_json', side_effect=OSError('interrupted initial marker write')):
            with self.assertRaisesRegex(OSError, 'interrupted initial marker write'):
                ingest(self.entry, 'publish', self.store)
        self.assertEqual({path.name for path in self.store.iterdir()}, {'.writer.lock'})
        with writer_lock(self.store), self.assertRaisesRegex(ValueError, 'Another writer'):
            ingest(self.entry, 'publish', self.store)
        self.assertTrue(ingest(self.entry, 'publish', self.store)['published'])

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

    def test_publication_retry_after_failed_current_replace(self):
        ingest(self.entry, 'publish', self.store)
        workspace = Workspace(self.root / 'workspace')
        workspace.init(no_ingest=True)
        (workspace.root / 'inputs/paper.tex').write_bytes(self.entry.read_bytes())
        self.entry.write_text(self.entry.read_text().replace('A.', 'B.'))

        cases = [
            (self.store, lambda: ingest(self.entry, 'publish', self.store)),
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
