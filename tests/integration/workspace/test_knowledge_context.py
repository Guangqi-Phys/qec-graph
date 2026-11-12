import copy
from pathlib import Path
import tempfile
import unittest

from qecgraph.core.graph import canonical
from qecgraph.domain.research import make_record
from qecgraph.domain.research_store import publish_records
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession


class KnowledgeContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'inputs').mkdir()
        (self.root / 'inputs/p.tex').write_text(r'''\documentclass{article}
\begin{document}
\section{Memory}
Offline fixture: CSS code, n=13, k=1, lower distance 12, measured X weight 4; idle included; p=.001 and LER=.01.
\begin{definition}A memory stores a state.\end{definition}
\begin{lemma}\label{lem:target}Under hypothesis H, the memory survives.\end{lemma}
\begin{proof}This is the proof text.\end{proof}
\section{Other}
\begin{definition}An unrelated definition.\end{definition}
\end{document}
''')
        self.ws = Workspace(self.root)
        self.ws.init()
        session = WorkspaceSession(self.root / 'machine', profile='research')
        node = next(n for n in session._source_nodes.values() if n['kind'] == 'paragraph')
        self.source = {'id': node['source']['source_version_id'], 'revision': node['source']['snapshot_id']}
        self.locator = {**node['source'], 'node_id': node['original_node_id'], 'node_content_sha256': node['content_sha256']}
        self.lemma = next(n['id'] for n in session._source_nodes.values() if n['kind'] == 'lemma')

    def record(self, kind, identifier, data):
        evidence = {'status': 'known', 'source_ref': self.source, 'source_locator': self.locator, 'method': 'offline_fixture'}
        return make_record(kind, identifier, '1', data, source=self.source, method='offline_fixture',
                           evidence={'/data/' + k: evidence for k, value in data.items() if value is not None})

    def session(self):
        return WorkspaceSession(self.root / 'machine', profile='research')

    def test_theorem_and_lean_context_preserve_statement_and_report_missing_assumptions(self):
        session = self.session()
        result = session.invoke('qec_get_context', {'identifier': self.lemma, 'purpose': 'theorem'})
        self.assertTrue(result['ok'], result)
        data = result['data']
        self.assertIn('Under hypothesis H', data['nodes'][0]['latex'])
        self.assertTrue(any('memory stores' in n.get('latex', '') for n in data['nodes']))
        self.assertFalse(any('unrelated definition' in n.get('latex', '') for n in data['nodes']))
        self.assertIn('explicit_assumptions', data['missing_components'])
        self.assertFalse(data['context_complete'])
        lean = session.invoke('qec_get_context', {'identifier': self.lemma, 'purpose': 'lean'})['data']
        self.assertIn('formalization_mapping', lean['missing_components'])
        self.assertIn('no Lean build', lean['formalization_status'])
        limited = session.invoke('qec_get_context', {'identifier': self.lemma, 'purpose': 'theorem',
                                                   'max_chars': len(canonical(data)) - 100})
        self.assertTrue(limited['ok'], limited)
        self.assertTrue(limited['data']['truncated'])
        self.assertEqual(limited['data']['nodes'][0]['latex'], data['nodes'][0]['latex'])

    def test_typed_trace_filters_proposed_edges_and_resolves_exact_revisions(self):
        a = self.record('construction', 'construction:a', {'description': 'recipe'})
        c = self.record('quantum_code', 'code:a', {'code_type': 'quantum', 'n': 13, 'k': 1,
                      'construction_ref': {'id': a['id'], 'revision': '1'}, 'review_status': 'proposed'})
        publish_records(self.ws.registry, [a, c])
        session = self.session()
        args = {'identifier': 'code:a', 'relations': ['construction_ref']}
        self.assertEqual(len(session.invoke('qec_trace', args)['data']['nodes']), 1)
        approved_view = session.invoke('qec_trace', {**args, 'include_candidates': True})['data']
        self.assertEqual({n['id'] for n in approved_view['nodes']}, {'code:a', 'construction:a'})
        self.assertEqual(approved_view['edges'][0]['status'], 'proposed')
        reverse = session.invoke('qec_trace', {'identifier': 'construction:a', 'direction': 'incoming',
                                              'relations': ['construction_ref'], 'include_candidates': True})['data']
        self.assertIn('code:a', {n['id'] for n in reverse['nodes']})
        context = session.invoke('qec_get_context', {'identifier': 'code:a', 'purpose': 'construction'})['data']
        self.assertIn('construction', context['missing_components'])

    def test_theorem_context_keeps_local_proposals_unverified(self):
        session = self.session()
        def proposal(identifier, reference):
            return {'id': identifier, 'kind': 'assumption_proposal', 'origin': 'ai_proposal',
                    'source_version_id': self.source['id'], 'snapshot_id': self.source['revision'],
                    'review_status': 'proposed', 'data': {'text': 'hypothesis H', 'source_refs': [reference]}}
        session.knowledge.proposal_items = {'local': proposal('local', 'main.tex:6'),
                                            'other': proposal('other', 'main.tex:10')}
        data = session.invoke('qec_get_context', {'identifier': self.lemma, 'purpose': 'theorem'})['data']
        selected = {n['id']: n for n in data['nodes']}
        self.assertEqual(selected['local']['review_status'], 'proposed')
        self.assertNotIn('other', selected)
        self.assertIn('explicit_assumptions', data['missing_components'])
        self.assertFalse(any(e['target']['id'] == 'local' for e in data['edges']))

    def records_for_conditions(self):
        def ref(identifier):
            return {'id': identifier, 'revision': '1'}
        return [
            self.record('metric', 'metric:d', {'name': 'joint distance'}),
            self.record('quantum_code', 'code:a', {'code_type': 'quantum', 'classification': 'css', 'n': 13, 'k': 1,
                         'check_matrix_refs': [ref('matrix:a'), ref('matrix:b')], 'distance_estimate_refs': [ref('distance:a')]}),
            self.record('check_matrix', 'matrix:a', {'code_ref': ref('code:a'), 'check_weight_statistics': [
                {'check_set_id': 'measured-X', 'sector': 'X', 'scope': 'measured', 'max': 10}]}),
            self.record('check_matrix', 'matrix:b', {'code_ref': ref('code:a'), 'check_weight_statistics': [
                {'check_set_id': 'measured-X', 'sector': 'X', 'scope': 'measured', 'max': 4}]}),
            self.record('distance_estimate', 'distance:a', {'subject_ref': ref('matrix:a'), 'metric_ref': ref('metric:d'),
                'relation': 'lower_bound', 'lower_bound': 12, 'upper_bound': None, 'sector': 'joint',
                'method': 'reported_bound', 'conditions': []}),
        ]

    def test_exact_code_conditions_do_not_mix_different_presentations(self):
        publish_records(self.ws.registry, self.records_for_conditions())
        session = self.session()
        args = {'n_max': 1000, 'k_min': 1, 'classification': 'css', 'distance_at_least': 12,
                'metric_id': 'metric:d', 'metric_revision': '1', 'evidence_policy': 'source_reported',
                'check_weight_max': 4, 'check_weight_sector': 'X', 'check_weight_scope': 'measured',
                'source_query': 'CSS'}
        result = session.invoke('qec_query_codes', args)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['data']['results'], [])
        self.assertTrue(result['data']['source_candidates']['results'])
        wider = session.invoke('qec_query_codes', {**args, 'check_weight_max': 10})
        self.assertTrue(wider['ok'], wider)
        self.assertEqual(wider['data']['total_matches'], 1)
        self.assertIn('enumeration', wider['data']['query_semantics'])
        incomplete = session.invoke('qec_query_codes', {'check_weight_max': 4})
        self.assertEqual(incomplete['error']['code'], 'INVALID_ARGUMENT')

    def test_performance_conditions_are_bound_and_unknowns_stay_visible(self):
        def ref(identifier):
            return {'id': identifier, 'revision': '1'}
        records = self.records_for_conditions()
        records += [
            self.record('noise_model', 'noise:a', {'idle': {'consideration': 'included'}, 'loss': None, 'erasure': None, 'leakage': None}),
            self.record('syndrome_measurement_circuit', 'circuit:a', {'check_matrix_ref': ref('matrix:a')}),
            self.record('noise_model_instance', 'noise-point:a', {'model_ref': ref('noise:a'), 'circuit_ref': ref('circuit:a'),
                         'reported_coordinates': {'p': .001}, 'resolved_channel_parameters': {'idle': .001}}),
            self.record('decoder', 'decoder:a', {'name': 'fixture decoder'}),
            self.record('metric', 'metric:ler', {'event': 'logical failure', 'denominator': 'per_round', 'unit': 'probability'}),
            self.record('experiment', 'experiment:a', {'source_ref': self.source, 'code_ref': ref('code:a'),
                         'check_matrix_ref': ref('matrix:a'), 'circuit_ref': ref('circuit:a'),
                         'noise_model_ref': ref('noise:a'), 'decoder_ref': ref('decoder:a')}),
            self.record('performance_data_point', 'point:a', {'experiment_ref': ref('experiment:a'),
                         'noise_model_instance_ref': ref('noise-point:a'), 'metric_ref': ref('metric:ler'), 'value': .01}),
        ]
        publish_records(self.ws.registry, records)
        session = self.session()
        args = {'idle': 'included', 'circuit_id': 'circuit:a', 'coordinate_name': 'p', 'coordinate': .001}
        result = session.invoke('qec_query_performance', args)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['data']['total_matches'], 1)
        self.assertIsNotNone(result['data']['results'][0]['comparison_group'])
        self.assertEqual(session.invoke('qec_query_performance', {**args, 'loss': 'included'})['data']['results'], [])
        self.assertEqual(session.invoke('qec_query_performance', {**args, 'coordinate': .002})['data']['results'], [])
        context = session.invoke('qec_get_context', {'identifier': 'point:a', 'purpose': 'performance', 'depth': 3})
        self.assertTrue(context['ok'], context)
        self.assertTrue(any(f['field'] == '/data/loss' and f['status'] == 'not_extracted' for f in context['data']['unknown_fields']))
        self.assertFalse(context['data']['context_complete'])
        other = copy.deepcopy(records[-2])
        other['id'] = 'experiment:b'
        other['data']['decoder_ref'] = None
        other['field_evidence']['/data/decoder_ref'] = {'status': 'not_extracted'}
        point = copy.deepcopy(records[-1])
        point['id'] = 'point:b'
        point['data']['experiment_ref'] = ref('experiment:b')
        publish_records(self.ws.registry, [other, point])
        session = self.session()
        page = session.invoke('qec_query_performance', args)['data']
        rows = list(page['results'])
        while page['continuation'] is not None:
            page = session.invoke('qec_query_performance', {**args, 'offset': page['continuation']})['data']
            rows.extend(page['results'])
        incomplete = next(row for row in rows if row['point']['id'] == 'point:b')
        self.assertIsNone(incomplete['comparison_group'])
        self.assertIn('decoder', incomplete['unresolved'])
