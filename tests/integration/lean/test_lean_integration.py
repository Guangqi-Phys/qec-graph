import shutil
import tempfile
import unittest
from pathlib import Path

from qecgraph import query
from qecgraph.corpus import project
from qecgraph.core.graph import read_json
from qecgraph.lean.integration import import_build, inspect_build
from qecgraph.registry import Registry
from qecgraph.review import apply, create_proposal, decide

from tests.support import ROOT
ARTIFACTS = ROOT / 'validation/lean-experimental/declaration-export'
EXAMPLE = ROOT / 'examples/lean'
THEOREM = 'lean:fixture:QEC.Binary.css_example_commutes'


class LeanIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = Registry(self.root / 'corpus')

    def test_historical_artifacts_are_auditable_but_never_current(self):
        with self.assertRaisesRegex(ValueError, 'stale'):
            import_build(self.registry.root, ARTIFACTS / 'report.json', project_id='fixture')
        result = import_build(self.registry.root, ARTIFACTS / 'report.json', project_id='fixture', historical=True)
        self.assertEqual(result['full_declarations'], 6)
        self.assertGreater(result['referenced_name_only'], 0)
        graph, _ = project(self.registry.root)
        shown = query.show(graph, THEOREM)
        self.assertEqual(shown['node']['build_binding']['effective_status'], 'stale')
        self.assertEqual(shown['node']['source']['path'], 'QEC/Binary.lean')
        self.assertTrue(shown['outgoing'])
        self.assertTrue(all(edge['status'] == 'stale' for edge in shown['outgoing']))
        self.assertEqual(query.dependencies(graph, THEOREM, include_candidates=True)['edges'], [])
        ctx = query.context(graph, THEOREM, include_candidates=True)
        self.assertNotIn('refs', ctx['nodes'][0]['record'])
        self.assertEqual(ctx['nodes'][0]['data']['type'], shown['node']['data']['type'])
        stub = next(node for node in graph.graph['nodes'] if node.get('data', {}).get('proof_progress') == 'referenced_name_only')
        self.assertIsNone(stub['data']['type'])
        self.assertIsNone(stub['data']['module'])

    def test_mapping_requires_bound_claim_and_complete_actual_type(self):
        claim = self.registry.add_record(read_json(EXAMPLE / 'claim.json'))
        mapping = read_json(EXAMPLE / 'mapping.json')
        mapping['source_refs'] = []
        for field, expected in [('expected_type_expr_sha256', 'type mismatch'),
                                ('expected_claim_content_sha256', 'claim revision/hash mismatch'),
                                ('semantic_review', 'cannot grant semantic review')]:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, expected):
                import_build(self.registry.root, ARTIFACTS / 'report.json', project_id='fixture', historical=True,
                             mappings=[{**mapping, field: 'mismatch'}])
            self.assertEqual(self.registry.read()[1], claim['registry_revision'])
        import_build(self.registry.root, ARTIFACTS / 'report.json', project_id='fixture', historical=True, mappings=[mapping])
        record = self.registry.record(mapping['id'])
        self.assertEqual(record['review']['status'], 'proposed')
        self.assertEqual(record['data']['semantic_review'], 'not_reviewed')
        self.assertEqual(record['data']['planned_dependencies'], ['def:boolean-dot'])
        self.assertEqual(self.registry.record(mapping['claim_id']), claim['record'])
        self.assertEqual(next(ref for ref in record['refs'] if ref['relation'] == 'formalizes')['status'], 'candidate')

        proposed = {key: value for key, value in record.items() if key != 'content_sha256'}
        proposed.update(revision='proposed-match', data={**record['data'], 'semantic_review': 'matched'})
        actor = {'id': 'ai-fixture', 'kind': 'ai'}
        proposal = create_proposal(self.registry.root, [{'record': proposed, 'expected_revision': record['revision'],
                                   'expected_content_sha256': record['content_sha256']}],
                                   actor=actor, rationale='Fixture for an unreviewed semantic claim')
        review = decide(self.registry.root, proposal['id'], actor=actor, decision='approve', rationale='Machine decision fixture')
        apply(self.registry.root, proposal['id'], review['id'])
        graph, _ = project(self.registry.root)
        binding = query.show(graph, mapping['id'])['node']['build_binding']
        self.assertEqual(binding['declared_semantic_review'], 'matched')
        self.assertEqual(binding['semantic_review'], 'not_reviewed')

    def test_build_only_and_altered_inputs_cannot_be_imported(self):
        with self.assertRaisesRegex(ValueError, 'actual validated build'):
            inspect_build(ROOT / 'validation/lean-experimental/fixed-build/report.json')
        altered = self.root / 'altered'
        shutil.copytree(ARTIFACTS, altered)
        (altered / 'inputs/QEC/Binary.lean').write_text('-- altered', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Archived Lean input changed'):
            inspect_build(altered / 'report.json')
        shutil.copyfile(ARTIFACTS / 'inputs/QEC/Binary.lean', altered / 'inputs/QEC/Binary.lean')
        (altered / 'export.stdout.txt').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'does not match the actual command stdout'):
            inspect_build(altered / 'report.json')


if __name__ == '__main__':
    unittest.main()
