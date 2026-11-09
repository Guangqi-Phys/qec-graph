import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from qecgraph.corpus import occurrence_id
from qecgraph.graph import read_json
from qecgraph.research import adapt_synthetic
from qecgraph.research_store import publish_records
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from test_mcp import initialization, request
from test_source_package import TEX

DESIGN = Path(__file__).resolve().parents[1] / 'docs/rfc-002'


class WorkspaceQueryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.notes = self.root / 'human/notes'
        self.notes.mkdir(parents=True)
        (self.notes / 'private-only-name.md').write_text('PRIVATE-ONLY-468f')
        (self.root / 'inputs').mkdir()
        (self.root / 'inputs/first').write_bytes(TEX)
        (self.root / 'inputs/unreadable').write_bytes(b'PK\x03\x04broken')
        self.ws = Workspace(self.root)
        self.release = self.ws.init()['release_id']
        self.session = WorkspaceSession(self.ws.registry.root)

    def test_registered_failed_artifact_and_fixed_source_occurrence(self):
        result = self.session.invoke('qecgraph_search', {'query': 'damaged_archive'})
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['results'][0]['kind'], 'source_artifact')
        state, _ = self.ws.registry.read()
        version, = state['versions']
        graph, _, _ = self.ws.registry.source_graph(version)
        node = next(n for n in graph['nodes'] if n['latex'] == 'Hello')
        identifier = occurrence_id(version, node['id'])
        source = self.session.invoke('qec_get_source', {'identifier': identifier})
        self.assertEqual(source['data']['latex'], 'Hello')
        (self.root / 'inputs/second').write_bytes(TEX.replace(b'Hello', b'Later source'))
        newer = self.ws.sync()['release_id']
        old = self.session.invoke('qecgraph_search', {'query': 'Later source'})
        self.assertEqual(old['data']['knowledge_snapshot'], self.release)
        self.assertEqual(old['data']['results'], [])
        rejected = self.session.invoke('qec_workspace_status', {'release_id': newer})
        self.assertEqual(rejected['error']['code'], 'SNAPSHOT_UNAVAILABLE')
        status = self.session.invoke('qec_workspace_status', {})
        self.assertEqual(status['data']['operational_status']['release_id'], newer)

    def test_real_stdio_does_not_return_human_files_or_synthetic_entities(self):
        publish_records(self.ws.registry, adapt_synthetic(read_json(DESIGN / 'examples/performance_context.synthetic.json')))
        lines = [initialization(), {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                 request(2, 'tools/list'),
                 request(3, 'tools/call', {'name': 'qecgraph_search', 'arguments': {'query': 'PRIVATE-ONLY-468f'}}),
                 request(4, 'tools/call', {'name': 'qec_get_source', 'arguments': {'identifier': '%2e%2e/human/notes/private-only-name.md'}}),
                 request(5, 'tools/call', {'name': 'qec_find_performance', 'arguments': {}})]
        process = subprocess.run([sys.executable, '-m', 'qecgraph', 'mcp', 'serve', '--machine', str(self.ws.registry.root)],
                                 input=''.join(json.dumps(line) + '\n' for line in lines), text=True,
                                 capture_output=True, timeout=15, check=True)
        self.assertNotIn('PRIVATE-ONLY-468f', process.stdout + process.stderr)
        self.assertNotIn('private-only-name', process.stdout + process.stderr)
        responses = {row['id']: row['result'] for row in map(json.loads, process.stdout.splitlines())}
        self.assertIn('qec_find_software', {t['name'] for t in responses[2]['tools']})
        self.assertEqual(responses[3]['structuredContent']['data']['results'], [])
        self.assertEqual(responses[4]['structuredContent']['error']['code'], 'NOT_FOUND')
        self.assertEqual(responses[5]['structuredContent']['data']['results'], [])
        self.assertEqual(responses[5]['structuredContent']['data']['coverage']['excluded_synthetic'], 11)

    def test_symlink_in_machine_is_rejected_before_reading(self):
        (self.ws.registry.root / 'operational/status.json').unlink()
        (self.ws.registry.root / 'operational/status.json').symlink_to(self.notes / 'private-only-name.md')
        with self.assertRaisesRegex(ValueError, 'Linked or special'):
            WorkspaceSession(self.ws.registry.root)
        failure = self.session.invoke('qec_workspace_status', {})
        self.assertFalse(failure['ok'])
        self.assertNotIn('private-only-name', str(failure))

    def test_source_reported_upper_bound_is_not_a_lower_bound(self):
        from qecgraph.research import make_record
        state, fixed = self.ws.registry.read()
        version, = state['versions']
        graph, _, meta = self.ws.registry.source_graph(version, fixed)
        node = next(n for n in graph['nodes'] if n['latex'] == 'Hello')
        origin = {'id': version, 'revision': meta['snapshot_id']}
        metric = {'id': 'metric:distance', 'revision': 'one'}
        code_ref = {'id': 'code:separate', 'revision': 'one'}
        claim_ref = {'id': 'distance:upper', 'revision': 'one'}
        locator = {'source_version_id': version, 'snapshot_id': meta['snapshot_id'],
                   'node_id': node['id'], 'node_content_sha256': node['content_sha256'], **node['source']}
        def record(kind, binding, data, evidence=None):
            return make_record(kind, binding['id'], binding['revision'], data,
                               source=origin, method='test_input', evidence=evidence)
        publish_records(self.ws.registry, [
            record('metric_definition', metric, {'name': 'joint Pauli weight'}),
            record('code_instance', code_ref, {'coding_domain': 'quantum', 'n_data': 13, 'k_logical': 1,
                                               'distance_claim_refs': [claim_ref]}),
            record('distance_claim', claim_ref, {'subject_ref': code_ref, 'metric_definition_ref': metric,
                   'relation': 'upper_bound', 'upper_bound': 12, 'lower_bound': None,
                   'sector': 'joint', 'method': 'witness', 'conditions': []},
                   {'/data/upper_bound': {'status': 'known', 'source_ref': origin, 'method': 'test_input',
                                          'source_locator': locator}}),
        ])
        session = WorkspaceSession(self.ws.registry.root)
        response = session.invoke('qec_find_codes', {'distance_at_least': 12, 'metric_definition_id': metric['id'],
                                                       'metric_revision': metric['revision'], 'evidence_policy': 'source_reported'})
        self.assertTrue(response['ok'])
        self.assertEqual(response['data']['results'], [])
        context = session.invoke('qec_get_context', {'identifier': code_ref['id'], 'depth': 2})
        self.assertTrue(context['ok'])
        self.assertIn(claim_ref['id'], {row['id'] for row in context['data']['nodes']})

    def test_nearest_point_reports_actual_coordinate_and_never_fakes_exact_match(self):
        from qecgraph.research import make_record, ref
        state, _ = self.ws.registry.read()
        version, = state['versions']
        origin = {'id': version, 'revision': state['versions'][version]['snapshot_id']}
        def make(kind, name, data):
            return make_record(kind, name, 'r1', data, source=origin, method='reported_fixture')
        exp = make('reported_experiment', 'exp:test', {'source_ref': origin, 'code_ref': None, 'presentation_ref': None,
                                                       'circuit_ref': None, 'noise_model_ref': None, 'decoder_ref': None})
        metric = make('metric_definition', 'metric:test', {'event': 'logical failure', 'denominator': 'block', 'unit': 'rate'})
        series = make('performance_series', 'series:test', {'experiment_ref': ref(exp), 'metric_definition_ref': ref(metric)})
        rows = [exp, metric, series]
        for i, coordinate in enumerate((0.01, 0.03)):
            noise = make('noise_instantiation', 'noise:' + str(i),
                         {'model_ref': None, 'reported_coordinates': {'p': coordinate}, 'resolved_channel_parameters': None})
            point = make('performance_point', 'point:' + str(i), {'experiment_ref': ref(exp), 'noise_instantiation_ref': ref(noise),
                           'metric_definition_ref': ref(metric), 'curve_ref': ref(series), 'value': None})
            rows.extend([noise, point])
        publish_records(self.ws.registry, rows)
        session = WorkspaceSession(self.ws.registry.root)
        inputs = {'coordinate_name': 'p', 'coordinate': 0.011}
        self.assertEqual(session.invoke('qec_find_performance', inputs)['data']['results'], [])
        found, = session.invoke('qec_find_performance', {**inputs, 'selection': 'nearest_reported'})['data']['results']
        self.assertEqual(found['selection']['reported'], 0.01)
        self.assertEqual(found['selection']['requested'], 0.011)
        self.assertFalse(found['selection']['is_interpolated'])
        self.assertIn('resolved_channel_parameters', found['unresolved'])
