import unittest
from copy import deepcopy
from pathlib import Path

from qecgraph.graph import read_json
from qecgraph.research import adapt_synthetic, make_record, pauli_weight, ref, validate_bundle
from qecgraph.software import adapt_seed, bundled_seed

DESIGN = Path(__file__).resolve().parents[1] / 'docs/rfc-002'


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.rows = adapt_synthetic(read_json(DESIGN / 'examples/performance_context.synthetic.json'))

    def test_fixture_does_not_invent_unsupported_values(self):
        rows = {r['kind']: r for r in self.rows}
        self.assertTrue(all(r['is_synthetic'] for r in self.rows))
        self.assertIsNone(rows['performance_point']['data']['value'])
        self.assertIsNone(rows['noise_model']['data']['idle'])
        self.assertNotIn('execution_run', rows)
        self.assertEqual(pauli_weight([1, 0, 1], [1, 1, 0]), 3)

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
        seed = read_json(DESIGN / 'software_catalog.seed.json')
        self.assertEqual(bundled_seed(), seed)
        rows = adapt_seed(seed)
        self.assertEqual(sum(r['kind'] == 'software_project' for r in rows), 14)
        self.assertFalse({'software_usage', 'software_release'} & {r['kind'] for r in rows})
        source = ref(self.rows[0])
        with self.assertRaisesRegex(ValueError, 'do not establish use'):
            make_record('software_usage', 'bad', 'r1',
                        {'usage_kind': 'citation', 'project_ref': None, 'release_ref': None,
                         'experiment_ref': {'id': 'exp', 'revision': 'r1'}}, source=source, method='manual')

    def test_unknown_channels_and_counted_depth_are_independent(self):
        source = ref(self.rows[0])
        with self.assertRaisesRegex(ValueError, 'must be included, excluded or null'):
            make_record('noise_model', 'noise:bad', 'r1',
                        {'idle': False, 'loss': None, 'erasure': None, 'leakage': None},
                        source=source, method='fixture')
        with self.assertRaisesRegex(ValueError, 'requires a source locator'):
            make_record('noise_model', 'noise:bad', 'r1',
                        {'idle': {'consideration': 'excluded'}, 'loss': None, 'erasure': None, 'leakage': None},
                        source=source, method='fixture')
        with self.assertRaisesRegex(ValueError, 'Depth kind'):
            make_record('circuit_protocol', 'circuit:bad', 'r1',
                        {'depth_metrics': [{'kind': 'tick_count', 'unit': 'ns', 'value': 4, 'definition': 'TICK'}]},
                        source=source, method='fixture')

    def test_formula_with_unknown_seed_does_not_prove_reconstruction(self):
        source = ref(self.rows[0])
        with self.assertRaisesRegex(ValueError, 'complete matrix recipe'):
            make_record('construction', 'construction:partial', 'r1',
                        {'reconstruction_status': 'reconstructable',
                         'matrix_recipe': {'formula': 'H from seeds', 'seed_refs': None}}, source=source, method='fixture')
