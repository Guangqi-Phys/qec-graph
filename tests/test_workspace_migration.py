import tempfile
import unittest
from pathlib import Path

from qecgraph.registry import Registry
from qecgraph.store import ingest
from qecgraph.workspace import Workspace
from qecgraph.workspace_migration import migrate_corpus
from qecgraph.workspace_query import WorkspaceSession
from test_source_package import TEX


class WorkspaceMigrationTests(unittest.TestCase):
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
