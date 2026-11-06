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

    def test_many_to_many_claims_keep_source_blocks_and_assumptions(self):
        for project in ('one', 'two'):
            self.registry.register_source('work:' + project, 'version:' + project, self.make_store(project))
        for identifier in ('claim:first', 'claim:second'):
            self.registry.add_record({'schema_version': 'qecgraph.record.v2', 'id': identifier,
                                      'kind': 'claim', 'revision': '1', 'title': 'Same title',
                                      'data': {'statement': 'Explicit normalized statement',
                                               'hypotheses': ['binary field'], 'quantifiers': []}})
        for version in ('one', 'two'):
            self.registry.link_claim('link:' + version, 'version:' + version, 'same', 'claim:first',
                                     assumptions=['binary field'], notation_scope={'H': version})
        self.registry.link_claim('link:second', 'version:one', 'same', 'claim:second')
        state, _ = self.registry.read()
        self.assertEqual(len(state['links']), 3)
        self.assertEqual(len(state['records']), 2)
        self.assertEqual({x['status'] for x in state['links']}, {'proposed'})
        graph, _, _ = self.registry.source_graph('version:one')
        self.assertEqual(next(n for n in graph['nodes'] if 'same' in n['labels'])['kind'], 'lemma')
        self.assertEqual(state['links'][0]['assumptions'], ['binary field'])

    def test_entity_revisions_cannot_be_overwritten_or_merged_by_parameters(self):
        record = {'schema_version': 'qecgraph.record.v2', 'id': 'code:a', 'kind': 'code_instance',
                  'revision': '1', 'title': '[[13,1,3]]', 'data': {'parameters': {'n': 13, 'k': 1}}}
        first = self.registry.add_record(record)
        record['id'] = 'code:b'
        self.registry.add_record(record)
        self.assertEqual(len(self.registry.read()[0]['records']), 2)
        record['data']['parameters']['n'] = 14
        with self.assertRaisesRegex(ValueError, 'revision already'):
            self.registry.add_record(record)
        record['revision'] = '2'
        self.registry.add_record(record)
        self.assertEqual(self.registry.record('code:b', '1')['data']['parameters']['n'], 13)
        self.assertEqual(self.registry.record('code:b')['data']['parameters']['n'], 14)
        self.assertEqual(self.registry.record('code:a', registry_revision=first['registry_revision'])['revision'], '1')

    def test_unknown_schema_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'explicit migration'):
            self.registry.add_record({'schema_version': 'future.v99'})


if __name__ == '__main__':
    unittest.main()
