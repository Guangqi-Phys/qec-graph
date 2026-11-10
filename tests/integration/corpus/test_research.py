import unittest
from copy import deepcopy

from qecgraph.graph import read_json
from qecgraph.research import adapt_synthetic, make_record, pauli_weight, prepare, ref, validate_bundle
from qecgraph.software import adapt_seed, bundled_seed
from qecgraph.validators import packaged_validator

from tests.support import FIXTURES


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.rows = adapt_synthetic(read_json(FIXTURES / 'performance_context.synthetic.json'))

    def test_fixture_does_not_invent_unsupported_values(self):
        rows = {r['kind']: r for r in self.rows}
        self.assertTrue(all(r['is_synthetic'] for r in self.rows))
        self.assertIsNone(rows['performance_point']['data']['value'])
        self.assertIsNone(rows['noise_model']['data']['idle'])
        self.assertNotIn('execution_run', rows)
        self.assertEqual(pauli_weight([1, 0, 1], [1, 1, 0]), 3)

    def test_packaged_schema_distinguishes_unknown_values_and_invalid_bindings(self):
        validator = packaged_validator('research.v1')
        validator.check_schema(validator.schema)
        for row in [*self.rows, *adapt_seed(bundled_seed())]:
            validator.validate(row)

        code = deepcopy(next(row for row in self.rows if row['kind'] == 'code_instance'))
        code['data']['k_logical'] = None
        self.assertTrue(validator.is_valid(code))
        del code['data']['k_logical']
        self.assertIn("'k_logical' is a required property", next(validator.iter_errors(code)).message)

        code = deepcopy(next(row for row in self.rows if row['kind'] == 'code_instance'))
        code['data']['presentation_refs'] = [{'id': 'presentation:fixture', 'revision': 'r1'}] * 2
        self.assertEqual(next(validator.iter_errors(code)).validator, 'uniqueItems')
        code['data']['presentation_refs'] = [{'id': 'presentation:fixture'}]
        self.assertFalse(validator.is_valid(code))
        code['kind'] = 'unknown_record_kind'
        self.assertEqual(next(validator.iter_errors(code)).json_path, '$.kind')

    def test_field_evidence_requires_provenance_and_resolves_the_value(self):
        validator = packaged_validator('research.v1')
        point = deepcopy(next(row for row in self.rows if row['kind'] == 'performance_point'))
        field = '/data/value'
        source = ref(self.rows[0])
        point['field_evidence'][field] = {'status': 'known', 'source_ref': source}
        self.assertFalse(validator.is_valid(point))
        point['field_evidence'][field]['method'] = 'fixture'
        self.assertTrue(validator.is_valid(point))
        with self.assertRaisesRegex(ValueError, 'Known value cannot be null'):
            prepare(point)

        point['field_evidence'][field] = {'status': 'not_reported', 'reason': 'Not stated in the checked scope',
                                          'source_ref': source, 'checked_scope': 'Table 1'}
        self.assertFalse(validator.is_valid(point))
        point['field_evidence'][field]['checked_at'] = '2026-11-09'
        self.assertEqual(prepare(point), point)
        point['field_evidence']['/data/invalid~3'] = {'status': 'unresolved'}
        self.assertFalse(validator.is_valid(point))

    def test_exact_revision_and_wrong_noise_are_not_interchangeable(self):
        rows = deepcopy(self.rows)
        noise = next(r for r in rows if r['kind'] == 'noise_model')
        newer = deepcopy(noise)
        newer['revision'] = 'r2'
        rows.append(newer)
        point_noise = next(r for r in rows if r['kind'] == 'noise_instantiation')
        point_noise['data']['model_ref'] = ref(newer)
        with self.assertRaisesRegex(ValueError, 'crosses experiment noise'):
            validate_bundle(rows)
        point_noise['data']['model_ref']['revision'] = 'nonexistent'
        with self.assertRaisesRegex(ValueError, 'Unresolved or wrong-type'):
            validate_bundle(rows)

    def test_no_usage_or_release_inferred_from_seed_algorithms(self):
        rows = adapt_seed(bundled_seed())
        self.assertEqual(sum(r['kind'] == 'software_project' for r in rows), 14)
        self.assertFalse({'software_usage', 'software_release'} & {r['kind'] for r in rows})
        source = ref(self.rows[0])
        with self.assertRaisesRegex(ValueError, 'do not establish use'):
            make_record('software_usage', 'bad', 'r1',
                        {'usage_kind': 'citation', 'project_ref': None, 'release_ref': None,
                         'experiment_ref': {'id': 'exp', 'revision': 'r1'}}, source=source, method='manual')

    def test_unknown_channels_and_counted_depth_are_independent(self):
        source = ref(self.rows[0])
        with self.assertRaisesRegex(ValueError, r'\$\.data\.idle'):
            make_record('noise_model', 'noise:bad', 'r1',
                        {'idle': False, 'loss': None, 'erasure': None, 'leakage': None},
                        source=source, method='fixture')
        with self.assertRaisesRegex(ValueError, 'requires a source locator'):
            make_record('noise_model', 'noise:bad', 'r1',
                        {'idle': {'consideration': 'excluded'}, 'loss': None, 'erasure': None, 'leakage': None},
                        source=source, method='fixture')
        with self.assertRaisesRegex(ValueError, r'\$\.data\.depth_metrics\[0\]\.unit'):
            make_record('circuit_protocol', 'circuit:bad', 'r1',
                        {'depth_metrics': [{'kind': 'tick_count', 'unit': 'ns', 'value': 4, 'definition': 'TICK'}]},
                        source=source, method='fixture')
        depth = {'kind': 'tick_count', 'unit': 'ticks', 'value': 4.0, 'definition': 'TICK'}
        with self.assertRaisesRegex(ValueError, 'Counted depth must use an integer'):
            make_record('circuit_protocol', 'circuit:bad', 'r1', {'depth_metrics': [depth]},
                        source=source, method='fixture')
        duration = {'kind': 'physical_duration', 'unit': 'ns', 'value': 4.5, 'definition': 'Elapsed duration'}
        accepted = make_record('circuit_protocol', 'circuit:duration', 'r1', {'depth_metrics': [duration]},
                               source=source, method='fixture')
        self.assertEqual(accepted['data']['depth_metrics'], [duration])

    def test_formula_with_unknown_seed_does_not_prove_reconstruction(self):
        source = ref(self.rows[0])
        with self.assertRaisesRegex(ValueError, r'\$\.data\.matrix_recipe'):
            make_record('construction', 'construction:partial', 'r1',
                        {'reconstruction_status': 'reconstructable',
                         'matrix_recipe': {'formula': 'H from seeds', 'seed_refs': None}}, source=source, method='fixture')

        with self.assertRaisesRegex(ValueError, r'\$\.data\.generator_asset_refs\[0\]'):
            make_record('code_presentation', 'presentation:bad', 'r1',
                        {'code_ref': None, 'check_weight_metrics': None, 'reconstruction_status': 'complete',
                         'generator_asset_refs': ['../human/notes/matrix.json']}, source=source, method='fixture')
        recipe = {'field': 'GF(2)', 'shape': [2, 2], 'index_convention': 'row and column from zero',
                  'bit_order': 'column order', 'formula': 'identity', 'version': '1', 'seed_refs': []}
        record = make_record('construction', 'construction:complete', 'r1',
                             {'reconstruction_status': 'complete', 'matrix_recipe': recipe},
                             source=source, method='fixture')
        self.assertEqual(record['data']['matrix_recipe'], recipe)
        with self.assertRaisesRegex(ValueError, 'Matrix dimensions must be integers'):
            make_record('construction', 'construction:bad', 'r1',
                        {'reconstruction_status': 'complete', 'matrix_recipe': {**recipe, 'shape': [2.0, 2]}},
                        source=source, method='fixture')

    def test_check_weight_metrics_require_ordered_statistics_and_exact_counts(self):
        source = ref(self.rows[0])
        weights = {'check_set_id': 'checks:demo', 'sector': 'X', 'scope': 'stabilizer',
                   'min': 1, 'max': 3, 'mean': 2.5, 'histogram': {'1': 1, '3': 3}}
        data = {'code_ref': None, 'check_weight_metrics': [weights]}
        record = make_record('code_presentation', 'presentation:weights', 'r1', data, source=source, method='fixture')
        self.assertEqual(record['data']['check_weight_metrics'], [weights])
        for changed, message in (({'min': 1.0}, 'min/max must be nonnegative integers'),
                                 ({'min': 4}, 'statistics disagree'),
                                 ({'mean': 4.5}, 'statistics disagree'),
                                 ({'histogram': {'1': 3.0}}, 'histogram requires nonnegative')):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, message):
                make_record('code_presentation', 'presentation:weights', 'r1',
                            {**data, 'check_weight_metrics': [{**weights, **changed}]}, source=source, method='fixture')

    def test_confidence_interval_requires_ordered_endpoints(self):
        point = next(row for row in self.rows if row['kind'] == 'performance_point')
        source = ref(self.rows[0])
        interval = {'method': 'fixture', 'lower': .8, 'upper': .2, 'level': .95}
        with self.assertRaisesRegex(ValueError, 'Confidence interval endpoints are out of order'):
            make_record('performance_point', 'point:interval', 'r1', {**point['data'], 'confidence_interval': interval},
                        source=source, method='fixture', synthetic=True)

    def test_domain_shapes_do_not_replace_numeric_consistency_checks(self):
        source = ref(self.rows[0])
        with self.assertRaisesRegex(ValueError, r'\$\.data\.upper_bound'):
            make_record('distance_claim', 'distance:fixture', 'r1',
                        {'subject_ref': None, 'metric_definition_ref': None, 'relation': 'upper_bound',
                         'lower_bound': None, 'upper_bound': 0}, source=source, method='fixture')
        with self.assertRaisesRegex(ValueError, 'Distance bound direction and values disagree'):
            make_record('distance_claim', 'distance:fixture', 'r1',
                        {'subject_ref': None, 'metric_definition_ref': None, 'relation': 'exact',
                         'lower_bound': 3, 'upper_bound': 5}, source=source, method='fixture')
        with self.assertRaisesRegex(ValueError, 'Invalid code parameter n_data'):
            make_record('code_instance', 'code:fixture', 'r1',
                        {'coding_domain': 'quantum', 'n_data': 5.0, 'k_logical': 1}, source=source, method='fixture')

    def test_refresh_adds_observations_without_overwriting_project_or_inventing_release(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from qecgraph.research_store import load_records, publish_records
        from qecgraph.software import _official_repo_url, refresh
        from qecgraph.workspace import Workspace
        self.assertIsNone(_official_repo_url('https://github.com.evil.example/quantumlib/Stim'))
        with TemporaryDirectory() as root:
            ws = Workspace(root)
            ws.init(no_ingest=True)
            original = adapt_seed(bundled_seed())
            publish_records(ws.registry, original)
            body = b'{"full_name":"quantumlib/Stim","private":false,"archived":false,"disabled":false}'
            with patch('qecgraph.software._fetch_metadata', return_value=body) as fetch:
                result = refresh(ws.registry, project_id='software:stim')
            fetch.assert_called_once_with('https://api.github.com/repos/quantumlib/Stim', 8)
            self.assertEqual(result['status'], 'observed')
            state, _ = ws.registry.read()
            rows = load_records(ws.registry, state)
            self.assertEqual(next(r for r in rows if r['id'] == 'software:stim'),
                             next(r for r in original if r['id'] == 'software:stim'))
            self.assertEqual(sum(r['kind'] == 'software_catalog_observation' for r in rows), 1)
            self.assertFalse(any(r['kind'] in {'software_release', 'software_usage'} for r in rows))
