import tempfile
import unittest
from pathlib import Path

from qecgraph.corpus import execute
from qecgraph.core.graph import read_json
from qecgraph.registry import Registry
from qecgraph.store import current_snapshot, ingest, pin_snapshot
from qecgraph.query import show
from qecgraph.core.transactions import writer_lock


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

    def test_registration_copies_only_verified_snapshot_files(self):
        store = self.root / 'c'
        ingest(self.entry, 'c', store)
        snapshot = current_snapshot(store)
        manifest = read_json(snapshot / 'manifest.json')
        names = {row['path'] for row in manifest['outputs']}
        graph = read_json(snapshot / 'graph.json')
        relative = next(node['fragment_path'] for node in graph['nodes'] if node.get('fragment_path'))
        fragment = snapshot / relative
        retained = snapshot / 'unlisted-fragment.tex'
        fragment.rename(retained)
        fragment.symlink_to(retained)
        (snapshot / 'unlisted-external.tex').symlink_to(self.entry)

        self.registry.register_source('work:c', 'version:c', store)
        _, registered, _ = self.registry.source_graph('version:c')
        self.assertEqual({str(path.relative_to(registered)) for path in registered.rglob('*') if path.is_file()},
                         names | {'manifest.json'})
        self.assertFalse((registered / relative).is_symlink())
        self.assertEqual((registered / relative).read_bytes(), retained.read_bytes())
        self.assertTrue(self.registry.validate()['passed'])

    def test_registration_discards_a_copy_with_a_damaged_output(self):
        store = self.root / 'c'
        ingest(self.entry, 'c', store)
        snapshot = current_snapshot(store)
        (snapshot / 'report.json').write_text('{}')
        previous = self.registry.read()[1]
        registered = self.registry.root / 'source_snapshots'
        before = sorted(registered.iterdir())
        with self.assertRaisesRegex(ValueError, 'Snapshot file changed: report.json'):
            self.registry.register_source('work:c', 'version:c', store)
        self.assertEqual(self.registry.read()[1], previous)
        self.assertEqual(sorted(registered.iterdir()), before)

    def test_snapshot_must_match_the_registered_project_fingerprint(self):
        state, fixed = self.registry.read()
        original = state['versions']['version:a']
        state['versions']['version:a'] = {**original, 'project_source_hash': '0' * 64}
        candidate = self.registry.prepare_publication(state)
        with self.assertRaisesRegex(ValueError, 'Registered snapshot project fingerprint mismatch'):
            self.registry.source_graph('version:a', candidate)
        with self.assertRaisesRegex(ValueError, 'Registered snapshot project fingerprint mismatch'):
            self.registry.validate(candidate)
        self.assertTrue(self.registry.validate(fixed)['passed'])

    def test_claim_mapping_is_candidate_and_bound_to_exact_revision(self):
        claim = {'schema': 'qecgraph.record', 'id': 'claim:a', 'revision': '1',
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
        claim = {'schema': 'qecgraph.record', 'id': 'claim:a', 'revision': '1',
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

    def test_claim_mapping_cannot_publish_from_a_changed_graph_file(self):
        self.registry.add_record({'schema': 'qecgraph.record', 'id': 'claim:a', 'revision': '1',
                                  'kind': 'claim', 'title': 'Claim',
                                  'data': {'statement': 'First.', 'hypotheses': [], 'quantifiers': []}})
        previous = self.registry.read()[1]
        _, snapshot, _ = self.registry.source_graph('version:a', previous)
        with (snapshot / 'graph.json').open('ab') as output:
            output.write(b' ')
        with self.assertRaisesRegex(ValueError, 'Snapshot file changed: graph.json'):
            self.registry.link_claim('link:a', 'version:a', 'same', 'claim:a')
        self.assertEqual(self.registry.read()[1], previous)


if __name__ == '__main__':
    unittest.main()
