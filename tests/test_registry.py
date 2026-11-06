import tempfile
import unittest
from pathlib import Path

from qecgraph.registry import Registry
from qecgraph.store import ingest


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paper = self.root / 'paper'
        self.paper.mkdir()
        self.entry = self.paper / 'main.tex'
        self.entry.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{same}First.\end{lemma}')
        self.registry = Registry(self.root / 'corpus')

    def make_store(self, project='one'):
        store = self.root / project
        ingest(self.entry, project, store)
        return store

    def test_same_label_different_works_and_relocated_archive(self):
        for project in ('one', 'two'):
            store = self.make_store(project)
            self.registry.register_source('work:' + project, 'version:' + project, store)
        first, _, _ = self.registry.source_graph('version:one')
        second, _, _ = self.registry.source_graph('version:two')
        self.assertNotEqual(first['labels']['same'], second['labels']['same'])
        self.entry.unlink()
        graph, snapshot, version = self.registry.source_graph('version:one')
        self.assertTrue((snapshot / 'sources/main.tex').exists())
        self.assertEqual(version['work_id'], 'work:one')
        self.assertEqual(graph['labels'], first['labels'])

    def test_versions_preserve_history_and_reject_rebinding(self):
        store = self.make_store()
        original = self.registry.register_source('work:one', 'version:1', store)
        repeated = self.registry.register_source('work:one', 'version:1', store)
        self.assertEqual(original, repeated)
        self.entry.write_text(self.entry.read_text().replace('First.', 'Second.'))
        self.make_store()
        with self.assertRaisesRegex(ValueError, 'different inputs'):
            self.registry.register_source('work:one', 'version:1', store)
        self.registry.register_source('work:one', 'version:2', store)
        old, _ = self.registry.read(original['registry_revision'])
        current, _ = self.registry.read()
        self.assertEqual(set(old['versions']), {'version:1'})
        self.assertEqual(set(current['versions']), {'version:1', 'version:2'})


if __name__ == '__main__':
    unittest.main()
