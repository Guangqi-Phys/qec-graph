import hashlib
import tempfile
import unittest
from pathlib import Path

from qecgraph.corpus import execute
from qecgraph.query import context, dependencies
from qecgraph.registry import Registry
from qecgraph.review import apply, create_proposal, decide
from qecgraph.domain.status import reviewed_cycles
from qecgraph.store import GraphInput, ingest


def claim(identifier, revision='1'):
    return {'schema': 'qecgraph.record', 'id': identifier, 'revision': revision, 'kind': 'claim',
            'title': identifier, 'data': {'statement': 'Statement ' + revision, 'hypotheses': [], 'quantifiers': []}}


def graph_with(edges, annotations=()):
    return {'snapshot_id': 'fixed-fixture', 'project_source_hash': 'fixed-input',
            'extraction_status': 'complete_for_supported_syntax', 'labels': {},
            'nodes': [{'id': 'a', 'kind': 'claim', 'annotations': list(annotations)}, {'id': 'b', 'kind': 'claim'}], 'edges': edges}


class StatusTests(unittest.TestCase):
    def test_candidate_status_and_unresolved_annotations_filter_at_every_stage(self):
        edge = {'id': 'ab', 'source': 'a', 'target': 'b', 'relation': 'depends_on_declared', 'status': 'candidate'}
        annotations = [{'effective_status': 'unresolved'}, {'effective_status': 'stale'},
                       {'effective_status': 'unbound_review'}, {'effective_status': 'candidate'}]
        graph = GraphInput(graph_with([edge], annotations))
        self.assertEqual(dependencies(graph, 'a')['edges'], [])
        self.assertEqual(context(graph, 'a')['edges'], [])
        self.assertEqual(context(graph, 'a')['nodes'][0]['annotations'], [])
        candidates = context(graph, 'a', include_candidates=True)
        self.assertEqual(candidates['edges'], [edge])
        self.assertEqual(candidates['nodes'][0]['annotations'], [{'effective_status': 'candidate'}])
        edge['status'] = 'stale'
        self.assertEqual(dependencies(graph, 'a', include_candidates=True)['edges'], [])

    def test_only_active_reviewed_logic_has_scc_issues(self):
        forward = {'id': 'ab', 'source': 'a', 'target': 'b', 'relation': 'references', 'status': 'observed'}
        reverse = {'id': 'ba', 'source': 'b', 'target': 'a', 'relation': 'references', 'status': 'observed'}
        graph = graph_with([forward, reverse])
        self.assertEqual(reviewed_cycles(graph), [])
        for edge in graph['edges']:
            edge.update(relation='depends_on_reviewed', status='declared')  # v1 relation category is independent of status.
        issues = reviewed_cycles(graph)
        self.assertEqual(issues[0]['node_ids'], ['a', 'b'])
        self.assertEqual(issues[0]['edge_ids'], ['ab', 'ba'])
        graph['edges'][0]['status'] = 'unbound_review'
        self.assertEqual(reviewed_cycles(graph), [])

    def reviewed_fixture(self, root, with_asset=False, source_store=None):
        registry = Registry(root / 'corpus')
        if source_store is not None:
            registry.register_source('work:review-fixture', 'source:review-fixture', source_store)
        target = claim('claim:target')
        asset_path = None
        if with_asset:
            raw = b'asset bound to review inputs'
            digest = hashlib.sha256(raw).hexdigest()
            target['assets'] = [{'asset_id': 'asset:sha256:' + digest, 'uri': 'qecasset:sha256:' + digest,
                                 'path': 'assets/' + digest, 'sha256': digest, 'size_bytes': len(raw), 'media_type': 'text/plain'}]
            asset_path = registry.root / 'assets' / digest
        registry.add_record(target)
        if asset_path:
            asset_path.parent.mkdir()
            asset_path.write_bytes(raw)
        original = registry.add_record(claim('claim:source'))['record']
        after = claim('claim:source', '2')
        after['refs'] = [{'relation': 'depends_on_reviewed', 'target': 'claim:target', 'revision': '1', 'status': 'declared'}]
        proposal = create_proposal(registry.root, [{'record': after, 'expected_revision': '1',
                                   'expected_content_sha256': original['content_sha256']}],
                                   actor={'id': 'fixture:ai', 'kind': 'ai'}, rationale='Review invalidation fixture')
        review = decide(registry.root, proposal['id'], actor={'id': 'fixture:human', 'kind': 'human'}, decision='approve',
                        rationale='Isolated human-category test fixture only', checked_scopes=['statement', 'hypotheses', 'dependencies'])
        apply(registry.root, proposal['id'], review['id'])
        return registry, asset_path

    def test_dependency_change_invalidates_review_without_rewriting_history(self):
        with tempfile.TemporaryDirectory() as folder:
            registry, _ = self.reviewed_fixture(Path(folder))
            fixed = registry.read()[1]
            self.assertTrue(execute(registry.root, 'deps', 'claim:source')['edges'])
            registry.add_record(claim('claim:target', '2'))
            shown = execute(registry.root, 'show', 'claim:source')
            self.assertEqual(shown['node']['review_binding']['effective_status'], 'stale')
            self.assertEqual(shown['outgoing'][0]['status'], 'stale')
            self.assertEqual(registry.record('claim:source')['review']['status'], 'reviewed')  # immutable historical decision retained
            for candidates in (False, True):
                self.assertEqual(execute(registry.root, 'context', 'claim:source', include_candidates=candidates)['edges'], [])
            historical = execute(registry.root, 'deps', 'claim:source', registry_revision=fixed)
            self.assertTrue(historical['edges'])

    def test_missing_asset_is_stale_not_still_reviewed(self):
        with tempfile.TemporaryDirectory() as folder:
            registry, path = self.reviewed_fixture(Path(folder), with_asset=True)
            path.unlink()
            shown = execute(registry.root, 'show', 'claim:source')
            self.assertEqual(shown['node']['review_status'], 'stale')
            self.assertIn('review_asset_unavailable', {reason['code'] for reason in shown['node']['review_binding']['reasons']})
            self.assertFalse(execute(registry.root, 'deps', 'claim:source', include_candidates=True)['edges'])

    def test_tampered_archived_source_invalidates_bound_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paper = root / 'main.tex'
            paper.write_text(r'\documentclass{article}\begin{document}A statement.\end{document}')
            store = root / 'store'
            ingest(paper, 'review-fixture', store)
            registry, _ = self.reviewed_fixture(root, source_store=store)
            self.assertTrue(execute(registry.root, 'deps', 'claim:source')['edges'])
            _, snapshot, _ = registry.source_graph('source:review-fixture')
            (snapshot / 'sources' / 'main.tex').write_text('Changed archived source')
            shown = execute(registry.root, 'show', 'claim:source')
            self.assertEqual(shown['node']['review_status'], 'stale')
            reasons = shown['node']['review_binding']['reasons']
            self.assertIn('review_source_unavailable', {reason['code'] for reason in reasons})
            self.assertFalse(execute(registry.root, 'deps', 'claim:source', include_candidates=True)['edges'])


if __name__ == '__main__':
    unittest.main()
