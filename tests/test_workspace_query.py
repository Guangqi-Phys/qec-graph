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

    def test_direct_cli_queries_share_the_fixed_workspace_mcp_scope(self):
        state, _ = self.ws.registry.read()
        version, = state['versions']
        graph, _, _ = self.ws.registry.source_graph(version)
        node = next(n for n in graph['nodes'] if n['latex'] == 'Hello')
        identifier = occurrence_id(version, node['id'])
        (self.root / 'inputs/second').write_bytes(TEX.replace(b'Hello', b'Later source'))
        self.assertNotEqual(self.ws.sync()['release_id'], self.release)
        cases = [
            (['search', 'Later source'], 'qecgraph_search', {'query': 'Later source'}),
            (['show', version], 'qec_get_entity', {'identifier': version}),
            (['context', version], 'qec_get_context', {'identifier': version}),
            (['deps', identifier], 'qecgraph_deps', {'identifier': identifier, 'depth': 2, 'max_nodes': 60}),
            (['impact', identifier], 'qecgraph_impact', {'identifier': identifier, 'depth': 2, 'max_nodes': 60}),
        ]
        for command, tool, arguments in cases:
            with self.subTest(command=command[0]):
                process = subprocess.run([sys.executable, '-m', 'qecgraph', *command,
                                          '--workspace', str(self.root), '--release', self.release],
                                         text=True, capture_output=True, check=True, timeout=5)
                result = json.loads(process.stdout)
                expected = self.session.invoke(tool, arguments)
                self.assertTrue(result['ok'], result)
                self.assertTrue(expected['ok'], expected)
                self.assertEqual(result['data'], expected['data'])

    def test_python_responses_cannot_mutate_the_pinned_session(self):
        state, _ = self.ws.registry.read()
        version, = state['versions']
        args = {'identifier': version}
        result = self.session.invoke('qec_get_entity', args)
        self.assertTrue(result['ok'])
        original = result['data']['entity']['data']['source_snapshot_id']
        result['data']['entity']['data']['source_snapshot_id'] = 'caller mutation'
        result['data']['scope']['release_id'] = 'caller mutation'
        result['data']['coverage']['registered'] = -1
        failure = self.session.invoke('unknown', {})
        failure['error']['scope']['release_id'] = 'caller mutation'

        fresh = self.session.invoke('qec_get_entity', args)['data']
        self.assertEqual(fresh['entity']['data']['source_snapshot_id'], original)
        self.assertEqual(fresh['scope']['release_id'], self.release)
        self.assertEqual(fresh['coverage']['registered'], 2)

    def test_research_lookup_requires_revision_when_multiple_are_visible(self):
        from qecgraph.research import make_record
        state, _ = self.ws.registry.read()
        version, = state['versions'].values()
        source = {'id': version['id'], 'revision': version['snapshot_id']}
        identifier = 'seed:multiple-revisions'
        publish_records(self.ws.registry, [
            make_record('classical_seed', identifier, revision, {'n_data': n},
                        source=source, method='test_fixture')
            for revision, n in [('r1', 3), ('r2', 5)]
        ])
        session = WorkspaceSession(self.ws.registry.root)
        for tool in ('qec_get_entity', 'qec_get_context'):
            with self.subTest(tool=tool):
                response = session.invoke(tool, {'identifier': identifier})
                self.assertEqual(response['error']['code'], 'AMBIGUOUS_REVISION')
                self.assertEqual(response['error']['details']['revisions'], ['r1', 'r2'])
        first = session.invoke('qec_get_entity', {'identifier': identifier, 'revision': 'r1'})
        self.assertEqual(first['data']['entity']['data']['n_data'], 3)
        missing = session.invoke('qec_get_entity', {'identifier': identifier, 'revision': 'missing'})
        self.assertEqual(missing['error']['code'], 'NOT_FOUND')

    def test_software_results_bind_usage_to_each_project_revision(self):
        from qecgraph.research import make_record
        state, _ = self.ws.registry.read()
        version, = state['versions'].values()
        source = {'id': version['id'], 'revision': version['snapshot_id']}
        identifier = 'software:fixture'
        records = [
            make_record('software_project', identifier, revision, {'name': 'Fixture decoder'},
                        source=source, method='test_fixture')
            for revision in ('r1', 'r2')
        ]
        records.append(make_record('software_usage', 'usage:fixture', 'r1', {
            'usage_kind': 'mention', 'project_ref': {'id': identifier, 'revision': 'r2'},
            'release_ref': None, 'source_ref': source,
        }, source=source, method='test_fixture'))
        publish_records(self.ws.registry, records)
        session = WorkspaceSession(self.ws.registry.root)
        args = {'query': 'Fixture decoder', 'limit': 1}
        first = session.invoke('qec_find_software', args)['data']
        self.assertEqual(first['total_matches'], 2)
        self.assertEqual(first['results'][0]['related_usage_or_observations'], [])
        second = session.invoke('qec_find_software', {**args, 'offset': first['continuation']})['data']
        self.assertEqual(second['results'][0]['revision'], 'r2')
        self.assertEqual(second['results'][0]['related_usage_or_observations'], [
            {'id': 'usage:fixture', 'revision': 'r1', 'kind': 'software_usage'},
        ])

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

    def test_resources_are_fixed_uri_bindings_not_file_names(self):
        from qecgraph.mcp_server import MCPServer
        (self.root / 'inputs/second').write_bytes(TEX.replace(b'Hello', b'Second source'))
        release = self.ws.sync()['release_id']
        server = MCPServer(WorkspaceSession(self.ws.registry.root, max_results=1))
        offer = server.handle(initialization())['result']
        self.assertIn('resources', offer['capabilities'])
        server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        listing = server.handle(request(2, 'resources/list'))['result']
        self.assertEqual(len(listing['resources']), 1)
        self.assertIn('nextCursor', listing)
        resource = listing['resources'][0]
        second = server.handle(request(5, 'resources/list', {'cursor': listing['nextCursor']}))['result']
        self.assertNotEqual(second['resources'][0]['uri'], resource['uri'])
        content, = server.handle(request(3, 'resources/read', {'uri': resource['uri']}))['result']['contents']
        self.assertEqual(content['_meta']['release_id'], release)
        self.assertTrue(content['text'])
        for uri in ('file:///human/notes/private-only-name.md', 'qec://source/%2e%2e/human/notes'):
            failure = server.handle(request(4, 'resources/read', {'uri': uri}))
            self.assertEqual(failure['error']['code'], -32002)
            self.assertNotIn(uri, str(failure))

    def test_assets_need_an_exact_record_binding_and_cannot_import_notes(self):
        from qecgraph.research import make_record
        from qecgraph.workspace_assets import add_asset
        path = self.root / 'matrix.bin'
        path.write_bytes(b'\x00\x01\x10\x11')
        asset = add_asset(self.root, path)
        uri = asset['uri']
        self.assertFalse(WorkspaceSession(self.ws.registry.root).invoke('qec_get_asset', {'identifier': uri})['ok'])
        with self.assertRaisesRegex(ValueError, 'Human vault'):
            add_asset(self.root, self.notes / 'private-only-name.md')
        state, _ = self.ws.registry.read()
        version, = state['versions']
        origin = {'id': version, 'revision': state['versions'][version]['snapshot_id']}
        record = make_record('code_presentation', 'presentation:matrix', 'r1',
                             {'code_ref': None, 'check_weight_metrics': None,
                              'generator_asset_refs': [uri], 'reconstruction_status': 'complete'},
                             source=origin, method='fixture')
        publish_records(self.ws.registry, [record])
        session = WorkspaceSession(self.ws.registry.root)
        response = session.invoke('qec_get_asset', {'identifier': uri, 'offset': 1, 'length': 2})['data']
        self.assertEqual(response['content'], 'ARA=')
        self.assertEqual(response['continuation'], 3)
        self.assertTrue(response['truncated'])
