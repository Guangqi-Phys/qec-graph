import unittest

from qecgraph.core.graph import read_json
from qecgraph.lean import audit_export

from tests.support import ROOT


class LeanExportTests(unittest.TestCase):
    def setUp(self):
        self.export = read_json(ROOT / 'tests/fixtures/lean/declaration-export/export.json')
        self.policy = read_json(ROOT / 'lean/axiom-policy.json')
        self.targets = read_json(ROOT / 'lean/targets.json')

    def test_real_full_type_module_location_and_actual_proof_dependencies(self):
        declarations = {item['name']: item for item in self.export['declarations']}
        general = declarations['QEC.Binary.dot_commutes']
        expression, binders = general['type_expr'], []
        while expression['kind'] == 'forall':
            binders.append(expression['binder'])
            expression = expression['body']
        self.assertEqual(binders, ['n', 'v', 'w'])
        self.assertEqual(general['module'], 'QEC.Binary')
        self.assertTrue(all(item['module'] == 'Init' for item in general['imports']))
        self.assertGreater(general['source_range']['line_start'], 0)
        self.assertFalse(general['type_has_metavariables'])
        sample = declarations['QEC.Binary.css_example_commutes']
        self.assertIn('QEC.Binary.dot', sample['type_constants_direct'])
        self.assertNotIn('QEC.Binary.dot_commutes', sample['proof_constants_transitive'])
        self.assertFalse(sample['dependencies_filtered'])

    def test_real_propext_is_reported_and_zero_policy_rejection_is_preserved(self):
        audit = audit_export(self.export, self.policy, self.targets)
        self.assertEqual(audit['status'], 'allowed')
        self.assertEqual(audit['axioms_observed'], ['propext'])
        self.assertEqual(audit['semantic_review'], 'not_reviewed')
        rejected = read_json(ROOT / 'validation/lean-experimental/zero-axiom-policy/audit.json')
        self.assertEqual(rejected['status'], 'rejected')
        self.assertTrue(any('propext' in issue.get('axioms', []) for issue in rejected['issues']))
        fixed = read_json(ROOT / 'validation/lean-experimental/fixed-build/report.json')
        self.assertEqual(fixed['status'], 'build_passed')
        self.assertFalse(fixed['git']['project_worktree_dirty'])
        self.assertEqual(fixed['declaration_export'], 'not_performed')

    def test_build_of_another_target_is_not_sufficient(self):
        targets = {'schema_version': 'qecgraph.lean-targets', 'required_declarations': {
            'QEC.Missing.target': {'kind': 'theorem', 'module': 'QEC.Missing'}}}
        audit = audit_export(self.export, self.policy, targets)
        self.assertEqual(audit['status'], 'rejected')
        self.assertIn('missing_or_wrong_target', {issue['code'] for issue in audit['issues']})


if __name__ == '__main__':
    unittest.main()
