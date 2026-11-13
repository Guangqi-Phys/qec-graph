import unittest

from qecgraph.query import context, dependencies
from qecgraph.domain.status import reviewed_cycles
from qecgraph.store import GraphInput


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
