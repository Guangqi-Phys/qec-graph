import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qecgraph.validators import DOMAIN_FIELDS
from qecgraph.validators.qec import basis, check_css, check_experiment, comparable_experiments, matrix_rows



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
