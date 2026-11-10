import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qecgraph.domain.domain_query import codes
from qecgraph.core.graph import read_json
from qecgraph.validators import DOMAIN_FIELDS
from qecgraph.validators.qec import basis, check_css, check_experiment, comparable_experiments, distance_issues, matrix_rows

from tests.support import ROOT


def record(identifier, kind, data):
    fields = {key: None for key in DOMAIN_FIELDS[kind]}
    fields.update(data)
    fields['unknown_reason'] = 'Synthetic contract fixture: unspecified fields remain unknown'
    return {'schema': 'qecgraph.record', 'id': identifier, 'kind': kind, 'revision': '1',
            'title': identifier, 'data': fields}


def matrix(rows, columns, ones):
    return {'field': 'GF(2)', 'format': 'coordinate-ones-v1', 'index_base': 0,
            'shape': [rows, columns], 'ones': ones}


class QECValidationTests(unittest.TestCase):
    def test_check_css_cli_distinguishes_invalid_input_from_noncommutation(self):
        with tempfile.TemporaryDirectory() as directory:
            hx = Path(directory) / 'hx.json'
            hz = Path(directory) / 'hz.json'
            one = matrix(1, 1, [[0, 0]])
            hx.write_text(json.dumps(one), encoding='utf-8')
            hz.write_text(json.dumps(one), encoding='utf-8')
            command = [sys.executable, '-m', 'qecgraph', 'check-css', '--hx', str(hx), '--hz', str(hz), '--json']
            failed = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(failed.returncode, 2)
            report = json.loads(failed.stdout)
            self.assertFalse(report['commutes'])
            self.assertEqual(report['suggested_exit_code'], 2)

            hx.write_text('[]', encoding='utf-8')
            malformed = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(malformed.returncode, 1)
            error = json.loads(malformed.stdout)['error']
            self.assertEqual(error['code'], 'INVALID_INPUT')
            self.assertIn('Matrix needs a JSON object', error['message'])

    def test_gf2_rank_noncommutation_and_malformed_coordinates(self):
        rows, _ = matrix_rows(matrix(3, 3, [[0, 0], [0, 1], [1, 0], [1, 2], [2, 1], [2, 2]]))
        self.assertEqual(len(basis(rows)), 2)  # Real-valued rank of this matrix is 3.
        one = matrix(1, 1, [[0, 0]])
        invalid = check_css(one, one)
        self.assertFalse(invalid['passed'])
        self.assertIsNone(invalid['k'])
        for ones in ([[0, 0], [0, 0]], [[0, 1], [0, 0]], [[False, 0]], [[0, 2]]):
            with self.subTest(ones=ones), self.assertRaises(ValueError):
                matrix_rows(matrix(1, 2, ones))

    def test_real_finite_hgp_exact_distance_and_logicals(self):
        folder = ROOT / 'legacy/knowledge_starter/assets/matrices'
        matrices = [read_json(folder / (name + '.gf2.json')) for name in ('HX', 'HZ', 'LX', 'LZ')]
        result = check_css(*matrices, enumerate_distance=True)
        self.assertTrue(result['passed'])
        self.assertEqual((result['n'], result['k']), (13, 1))
        self.assertEqual(result['distance']['d'], 3)
        self.assertEqual(result['lean_status'], 'not_performed')
        with self.assertRaisesRegex(ValueError, 'budget'):
            check_css(*matrices, enumerate_distance=True, max_n=12)
        zero = check_css(matrix(0, 0, []), matrix(0, 0, []), enumerate_distance=True)
        self.assertEqual(zero['distance_status'], 'out_of_domain_k_zero')

    def test_upper_bound_never_satisfies_lower_bound_and_current_inputs_required(self):
        from qecgraph.workspace import Workspace
        from qecgraph.workspace_query import WorkspaceSession

        with tempfile.TemporaryDirectory() as folder:
            workspace = Workspace(folder)
            workspace.init(no_ingest=True)
            registry = workspace.registry
            raw = b'explicit synthetic matrix asset'
            digest = hashlib.sha256(raw).hexdigest()
            asset = {'asset_id': 'asset:sha256:' + digest, 'uri': 'qecasset:sha256:' + digest,
                     'path': 'assets/' + digest, 'sha256': digest, 'size_bytes': len(raw), 'media_type': 'application/octet-stream'}
            code = record('code:test', 'quantum_code', {'construction_id': None, 'parameters': {'n': 13, 'k': 1},
                          'check_matrix_ids': ['check_matrix:test'], 'distance_estimate_ids': ['claim:distance'], 'fixed_inputs': []})
            registry.add_record(code)
            check_matrix = record('check_matrix:test', 'check_matrix', {'instance_id': 'code:test', 'matrices': {},
                                  'row_order': 'fixed', 'qubit_order': 'fixed', 'index_base': 0, 'matrix_definition_id': 'metric:distance'})
            check_matrix['assets'] = [asset]
            registry.add_record(check_matrix)
            target = registry.root / asset['path']
            target.parent.mkdir(parents=True)
            target.write_bytes(raw)
            registry.add_record(record('metric:distance', 'definition', {'statement': 'Binary CSS code distance', 'scope': 'k>0'}))
            distance = record('claim:distance', 'claim', {'statement': 'Synthetic distance bound', 'hypotheses': [], 'quantifiers': [],
                              'subject_id': 'code:test', 'check_matrix_id': 'check_matrix:test', 'metric_id': 'metric:distance',
                              'sector': 'joint', 'relation': 'upper_bound', 'lower_bound': None, 'upper_bound': 12,
                              'assumptions': [], 'method': 'synthetic_fixture'})
            distance['evidence_ids'] = ['evidence:test']
            registry.add_record(distance)
            bindings = [{key: registry.record(identifier)[key] for key in ('id', 'revision', 'content_sha256')}
                        for identifier in ('code:test', 'check_matrix:test', 'metric:distance')]
            claim = registry.record(distance['id'])
            upper_binding = {key: claim[key] for key in ('id', 'revision', 'content_sha256')}
            evidence = record('evidence:test', 'evidence', {'evidence_kind': 'computed_exact', 'method': 'synthetic_fixture',
                              'inputs': bindings + [upper_binding], 'checker': 'synthetic_fixture_only', 'outputs': ['fixture result'],
                              'scope': 'contract test', 'limitations': ['Not real mathematical evidence'], 'status': 'passed'})
            registry.add_record(evidence)
            self.assertEqual(codes(registry.root, distance_at_least=12, metric_id='metric:distance')['results'], [])
            distance['revision'] = '2'
            distance['data'].update(relation='lower_bound', lower_bound=3, upper_bound=None)
            registry.add_record(distance)
            self.assertEqual(codes(registry.root, distance_at_least=3, metric_id='metric:distance')['results'], [])
            evidence['revision'] = '2'
            evidence['data']['inputs'] = bindings
            registry.add_record(evidence)
            self.assertEqual(codes(registry.root, distance_at_least=3, metric_id='metric:distance')['results'], [])
            claim = registry.record(distance['id'])
            evidence['revision'] = '3'
            evidence['data']['inputs'] = bindings + [{key: claim[key] for key in ('id', 'revision', 'content_sha256')}]
            bound_revision = registry.add_record(evidence)['registry_revision']
            result = codes(registry.root, distance_at_least=3, metric_id='metric:distance')
            self.assertEqual(len(result['results']), 1)
            self.assertEqual(result['results'][0]['distance_estimates'][0]['evidence'][0]['kind'], 'computed_exact')
            self.assertEqual(result['results'][0]['distance_estimates'][0]['review_status'], 'proposed')
            self.assertEqual(result['results'][0]['distance_estimates'][0]['evidence'][0]['review_status'], 'proposed')
            self.assertEqual(codes(registry.root, distance_at_least=3, metric_id='another:metric')['results'], [])
            session = WorkspaceSession(registry.root, bound_revision)
            arguments = {'distance_at_least': 3, 'metric_id': 'metric:distance'}
            for metric_revision, expected in (('1', 1), ('other', 0)):
                response = session.invoke('qec_find_codes', {**arguments, 'metric_revision': metric_revision})
                self.assertTrue(response['ok'], response)
                self.assertEqual(len(response['data']['results']), expected)
            distance['revision'] = '3'
            distance['data']['lower_bound'] = 12
            registry.add_record(distance)
            self.assertEqual(codes(registry.root, distance_at_least=12, metric_id='metric:distance')['results'], [])
            self.assertEqual(len(codes(registry.root, registry_revision=bound_revision, distance_at_least=3,
                                       metric_id='metric:distance')['results']), 1)
            target.write_bytes(b'changed')
            self.assertEqual(codes(registry.root, registry_revision=bound_revision, distance_at_least=3,
                                   metric_id='metric:distance')['results'], [])
            with self.assertRaisesRegex(ValueError, 'metric_id'):
                codes(registry.root, distance_at_least=3)
        self.assertTrue(distance_issues({'relation': 'exact', 'lower_bound': 3, 'upper_bound': 12}))

    def test_default_distance_filter_requires_computed_evidence_not_source_report(self):
        from qecgraph.workspace import Workspace
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            workspace.init(no_ingest=True)
            registry = workspace.registry
            code = record('code:test', 'quantum_code', {'construction_id': None, 'parameters': {'n': 13, 'k': 1},
                          'check_matrix_ids': ['check_matrix:test'], 'distance_estimate_ids': ['claim:distance'], 'fixed_inputs': []})
            registry.add_record(code)
            registry.add_record(record('check_matrix:test', 'check_matrix', {'instance_id': 'code:test', 'matrices': {},
                                  'row_order': 'fixed', 'qubit_order': 'fixed', 'index_base': 0,
                                  'matrix_definition_id': 'metric:distance'}))
            registry.add_record(record('metric:distance', 'definition', {'statement': 'Binary CSS code distance', 'scope': 'k>0'}))
            claim = record('claim:distance', 'claim', {'statement': 'Reported distance', 'hypotheses': [], 'quantifiers': [],
                          'subject_id': 'code:test', 'check_matrix_id': 'check_matrix:test',
                          'metric_id': 'metric:distance', 'sector': 'joint', 'relation': 'lower_bound',
                          'lower_bound': 3, 'upper_bound': None, 'assumptions': [], 'method': 'source_report'})
            claim['evidence_ids'] = ['evidence:reported']
            registry.add_record(claim)
            bindings = [{key: registry.record(identifier)[key] for key in ('id', 'revision', 'content_sha256')}
                        for identifier in ('code:test', 'check_matrix:test', 'metric:distance')]
            bound_claim = registry.record('claim:distance')
            evidence = record('evidence:reported', 'evidence', {
                'evidence_kind': 'source_reported', 'method': 'paper_report', 'checker': 'human transcription',
                'inputs': bindings + [{key: bound_claim[key] for key in ('id', 'revision', 'content_sha256')}],
                'outputs': ['paper Table 2'], 'scope': 'reported only', 'limitations': ['not recomputed'],
                'status': 'source_reported'})
            registry.add_record(evidence)

            self.assertEqual(codes(registry.root, distance_at_least=3, metric_id='metric:distance')['results'], [])
            result = codes(registry.root, distance_at_least=3, metric_id='metric:distance',
                           metric_revision='1', evidence_policy='source_reported')
            self.assertEqual(len(result['results']), 1)
            self.assertEqual(result['evidence_policy'], 'source_reported')
            with self.assertRaisesRegex(ValueError, 'metric_revision'):
                codes(registry.root, distance_at_least=3, metric_id='metric:distance',
                      evidence_policy='source_reported')

    def test_corpus_codes_cli_forwards_metric_revision_and_policy(self):
        from qecgraph.cli.commands import records as record_commands
        args = SimpleNamespace(corpus='corpus', registry_revision=None, n_min=None, n_max=None,
                               distance_at_least=3, metric_id='metric:distance',
                               metric_revision='7', sector='joint', construction=None, limit=None,
                               evidence_policy='source_reported', release=None, offset=None,
                               max_chars=None, quiet=True)
        with patch('qecgraph.domain.domain_query.codes', return_value={'results': []}) as mocked, \
                patch('qecgraph.cli.commands.records.emit_report', return_value=0):
            self.assertEqual(record_commands.codes(args), 0)
        self.assertEqual(mocked.call_args.kwargs['metric_revision'], '7')
        self.assertEqual(mocked.call_args.kwargs['evidence_policy'], 'source_reported')

    def experiment_fixture(self):
        bindings = {key: {'id': key + ':test', 'revision': '1', 'content_sha256': 'a' * 64}
                    for key in ('code', 'check_matrix', 'circuit', 'noise', 'decoder', 'metric')}
        experiment = record('experiment:test', 'experiment', {'input_revisions': bindings, 'configuration': {'rounds': 5},
                            'metric': 'metric:test', 'environment': {},
                            'sampling': {'method': 'iid', 'stopping_rule': 'fixed_shots', 'random_stream': 'recorded', 'interval_method': 'explicit_fixture'},
                            'statistics': {'shots': 100, 'discarded': 20, 'accepted': 80, 'failures': 4,
                                           'confidence_interval': {'level': .95, 'lower': .01, 'upper': .12}}})
        metric = record('metric:test', 'metric', {'event': 'any logical observable differs', 'denominator': 'accepted_shots',
                        'sector': 'joint', 'rounds': 5, 'boundaries': 'specified', 'postselection': 'specified', 'timeout_policy': 'count_as_failure'})
        return experiment, metric

    def test_check_experiment_cli_reports_bound_sampling_and_metric_errors(self):
        experiment, metric = self.experiment_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'experiment.json'
            command = [sys.executable, '-m', 'qecgraph', 'check-experiment', str(path), '--json']
            path.write_text(json.dumps({'record': experiment, 'metric': metric}), encoding='utf-8')
            verified = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
            report = json.loads(verified.stdout)
            self.assertTrue(report['passed'])
            self.assertEqual(report['estimate'], .05)
            self.assertEqual(report['acceptance_rate'], .8)

            malformed = copy.deepcopy(experiment)
            malformed['data']['input_revisions']['circuit']['content_sha256'] = 'not-a-digest'
            for record_, metric_, message in (
                (malformed, metric, 'circuit binding needs a lowercase SHA-256'),
                (experiment, {**metric, 'revision': 'different'}, 'metric input revision disagree'),
                (experiment, {**metric, 'content_sha256': 'b' * 64}, 'metric input content_sha256 disagree'),
            ):
                with self.subTest(message=message):
                    path.write_text(json.dumps({'record': record_, 'metric': metric_}), encoding='utf-8')
                    rejected = subprocess.run(command, capture_output=True, text=True, timeout=10)
                    self.assertEqual(rejected.returncode, 1)
                    error = json.loads(rejected.stdout)['error']
                    self.assertEqual(error['code'], 'INVALID_INPUT')
                    self.assertIn(message, error['message'])

            metric['data']['denominator'] = 'all_shots'
            path.write_text(json.dumps({'record': experiment, 'metric': metric}), encoding='utf-8')
            rejected = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(rejected.returncode, 1)
            error = json.loads(rejected.stdout)['error']
            self.assertEqual(error['code'], 'INVALID_INPUT')
            self.assertIn('accepted_shots metrics', error['message'])

    def test_experiment_postselection_and_sampling_are_not_interchangeable(self):
        experiment, metric = self.experiment_fixture()
        result = check_experiment(experiment, metric)
        self.assertEqual(result['estimate'], .05)
        self.assertEqual(result['acceptance_rate'], .8)
        self.assertTrue(comparable_experiments(experiment, experiment, metric, metric)['comparable'])
        for config in (None, {}, {'schedule': {'rounds': None}}):
            unknown = copy.deepcopy(experiment)
            unknown['data']['configuration'] = config
            comparison = comparable_experiments(unknown, unknown, metric, metric)
            self.assertFalse(comparison['comparable'])
            self.assertIn('configuration_unknown', comparison['differences'])
        changed = copy.deepcopy(experiment)
        changed['data']['input_revisions']['noise']['revision'] = '2'
        self.assertFalse(comparable_experiments(experiment, changed, metric, metric)['comparable'])
        changed['data']['statistics']['failures'] = 0
        changed['data']['statistics']['confidence_interval']['lower'] = 0
        changed['data']['statistics']['confidence_interval']['upper'] = 0
        with self.assertRaisesRegex(ValueError, 'Zero observed'):
            check_experiment(changed, metric)
        importance = copy.deepcopy(experiment)
        importance['data']['sampling'] = {'method': 'importance', 'target_distribution': 'target', 'proposal_distribution': 'proposal',
                                           'weights_asset': 'asset:weights', 'estimator': 'weighted', 'sufficient_statistics': 'asset:stats'}
        self.assertIsNone(check_experiment(importance, metric)['estimate'])


if __name__ == '__main__':
    unittest.main()
