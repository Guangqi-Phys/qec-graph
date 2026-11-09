import tempfile
import unittest
from pathlib import Path

from qecgraph.corpus import execute
from qecgraph.registry import Registry
from qecgraph.store import ingest, pin_snapshot
from qecgraph.query import show
from qecgraph.transactions import writer_lock


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entry = self.root / 'main.tex'
        self.entry.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{same}First.\end{lemma}')
        self.registry = Registry(self.root / 'corpus')
        for project in ('a', 'b'):
            ingest(self.entry, project, self.root / project)
            self.registry.register_source('work:' + project, 'version:' + project, self.root / project)

    def test_namespace_scope_and_empty_result_are_explicit(self):
        with self.assertRaisesRegex(ValueError, 'require source_version'):
            execute(self.registry.root, 'show', 'same')
        first = execute(self.registry.root, 'show', 'version:a::same')
        second = execute(self.registry.root, 'show', 'same', source_version_id='version:b')
        self.assertNotEqual(first['node']['id'], second['node']['id'])
        self.assertEqual(first['node']['source']['source_version_id'], 'version:a')
        result = execute(self.registry.root, 'search', text='nonexistent')
        self.assertEqual(result['results'], [])
        self.assertEqual(len(result['scope']['source_versions']), 2)
        self.assertIn('does not establish nonexistence', result['absence_note'])
        with self.assertRaisesRegex(ValueError, 'Unknown source version'):
            execute(self.registry.root, 'search', text='First', source_version_id='missing')

    def test_pinned_corpus_and_store_do_not_follow_current(self):
        fixed = self.registry.read()[1]
        old_snapshot = pin_snapshot(self.root / 'a')
        self.entry.write_text(self.entry.read_text().replace('First.', 'Changed.'))
        ingest(self.entry, 'a', self.root / 'a')
        self.registry.register_source('work:a', 'version:a:2', self.root / 'a')
        old = execute(self.registry.root, 'show', 'version:a::same', registry_revision=fixed)
        self.assertIn('First.', old['node']['latex'])
        self.assertNotIn('version:a:2', old['scope']['source_versions'])
        self.assertIn('First.', show(old_snapshot, 'same')['node']['latex'])
        self.assertIn('Changed.', show(self.root / 'a', 'same')['node']['latex'])

    def test_claim_mapping_is_candidate_and_bound_to_exact_revision(self):
        claim = {'schema_version': 'qecgraph.record.v3', 'id': 'claim:a', 'revision': '1',
                 'kind': 'claim', 'title': 'Claim', 'data': {'statement': 'First.', 'hypotheses': [], 'quantifiers': []}}
        self.registry.add_record(claim)
        self.registry.link_claim('link:a', 'version:a', 'same', 'claim:a')
        result = execute(self.registry.root, 'context', 'claim:a')
        self.assertEqual(result['edges'], [])
        candidates = execute(self.registry.root, 'context', 'claim:a', include_candidates=True)
        self.assertTrue(any(e['relation'] == 'normalizes_to' for e in candidates['edges']))
        claim['revision'] = '2'
        claim['data']['statement'] = 'Revised.'
        self.registry.add_record(claim)
        stale = execute(self.registry.root, 'show', 'claim:a')
        self.assertEqual(stale['incoming'][0]['status'], 'stale')
        context = execute(self.registry.root, 'context', 'claim:a', include_candidates=True)
        self.assertEqual(context['edges'], [])

    def test_claim_mapping_becomes_stale_after_source_projection_replacement(self):
        claim = {'schema_version': 'qecgraph.record.v3', 'id': 'claim:a', 'revision': '1',
                 'kind': 'claim', 'title': 'Claim', 'data': {'statement': 'First.', 'hypotheses': [], 'quantifiers': []}}
        self.registry.add_record(claim)
        original = self.registry.link_claim('link:a', 'version:a', 'same', 'claim:a')['registry_revision']
        changed = self.entry.read_text().replace('First.', 'Changed.')
        for source, expected in ((changed, ['stale']), (r'\section{Changed}\label{same}', [])):
            with self.subTest(expected=expected):
                self.entry.write_text(source)
                store = self.root / 'a'
                ingest(self.entry, 'a', store)
                with writer_lock(self.registry.root):
                    state, _ = self.registry.read()
                    self.registry.stage_source(state, 'work:a', 'version:a', store, replace_projection=True)
                    self.registry._publish(state)
                current = execute(self.registry.root, 'show', 'claim:a')
                self.assertEqual([edge['status'] for edge in current['incoming']], expected)
                self.assertTrue(self.registry.validate()['passed'])
                historical = execute(self.registry.root, 'show', 'claim:a', registry_revision=original)
                self.assertEqual(historical['incoming'][0]['status'], 'candidate')


if __name__ == '__main__':
    unittest.main()
