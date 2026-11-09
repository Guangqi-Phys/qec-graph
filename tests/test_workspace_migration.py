import tempfile
import unittest
from pathlib import Path

from qecgraph.registry import Registry
from qecgraph.store import ingest
from qecgraph.workspace import Workspace
from qecgraph.workspace_migration import migrate_corpus
from qecgraph.workspace_query import WorkspaceSession
from test_qec_validation import record
from test_source_package import TEX


class WorkspaceMigrationTests(unittest.TestCase):
    def test_migration_reports_ambiguous_fields_without_rewriting_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = Registry(root / 'corpus')
            cases = (
                ('code:legacy', 'code_instance', {'parameters': {'n': 13, 'k': 1, 'd': 3}}, 'untyped_distance'),
                ('noise:legacy', 'noise', {'idle': False}, 'unbound_negative_idle'),
                ('decoder:legacy', 'decoder', {'software': 'Decoder name'}, 'unresolved_software_name'),
                ('circuit:legacy', 'circuit', {'depth': 8}, 'unspecified_depth_definition'),
            )
            for identifier, kind, data, _ in cases:
                legacy.add_record(record(identifier, kind, data))
            _, revision = legacy.read()

            migrated = migrate_corpus(legacy.root, root / 'workspace')
            self.assertEqual(migrated['legacy_registry_revision'], revision)
            self.assertEqual(migrated['rejected_records'], [])
            self.assertCountEqual(migrated['uncertain_fields'], [
                {'id': identifier, 'revision': '1', 'reason': reason} for identifier, _, _, reason in cases
            ])
            workspace = Workspace(root / 'workspace')
            for identifier, _, _, _ in cases:
                self.assertEqual(workspace.registry.record(identifier), legacy.record(identifier))
            self.assertEqual(legacy.read()[1], revision)
            self.assertTrue(workspace.validate()['passed'])

    def test_clone_keeps_legacy_snapshot_and_history_after_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / 'legacy.tex'
            entry.write_bytes(TEX)
            ingest(entry, 'legacy', root / 'store')
            legacy = Registry(root / 'corpus')
            first = legacy.register_source('work:historic', 'version:historic', root / 'store')
            original = (legacy.root / 'CURRENT.json').read_bytes()
            result = migrate_corpus(legacy.root, root / 'new')
            workspace = Workspace(root / 'new')
            state, fixed = workspace.registry.read(result['release_id'])
            self.assertEqual(result['legacy_registry_revision'], first['registry_revision'])
            self.assertEqual(workspace.registry.read(first['registry_revision']), legacy.read(first['registry_revision']))
            self.assertEqual(state['versions'], legacy.read()[0]['versions'])
            self.assertEqual(workspace.rebuild()['release_id'], result['release_id'])
            session = WorkspaceSession(workspace.registry.root)
            self.assertTrue(session.invoke('qecgraph_search', {'query': 'Hello'})['data']['results'])
            self.assertEqual((legacy.root / 'CURRENT.json').read_bytes(), original)
            with self.assertRaisesRegex(ValueError, 'new, independent directory'):
                migrate_corpus(legacy.root, workspace.root)
