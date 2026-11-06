import json
import tempfile
import unittest
from pathlib import Path

from qecgraph.graph import read_json
from qecgraph.migrations import migrate
from qecgraph.records import prepare_record
from qecgraph.registry import Registry
from qecgraph.store import current_snapshot, ingest
from qecgraph.corpus import execute


def claim(identifier='claim:typed'):
    return {'schema_version': 'qecgraph.record.v3', 'id': identifier, 'kind': 'claim',
            'revision': '1', 'title': 'Typed claim',
            'data': {'statement': 'A statement.', 'hypotheses': [], 'quantifiers': []}}


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_strict_json_rejects_duplicate_keys_nonfinite_and_overflow(self):
        path = self.root / 'input.json'
        for raw in ('{"id":1,"id":2}', '{"value":NaN}', '{"value":Infinity}', '{"value":1e9999}'):
            path.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                read_json(path)

    def test_domain_fields_and_unknowns_are_explicit(self):
        value = claim()
        del value['data']['quantifiers']
        with self.assertRaisesRegex(ValueError, 'quantifiers'):
            prepare_record(value)
        value['data']['quantifiers'] = None
        with self.assertRaisesRegex(ValueError, 'unknown_reason'):
            prepare_record(value)
        value['data']['unknown_reason'] = 'Not yet normalized'
        self.assertEqual(prepare_record(value)['review']['status'], 'proposed')
        value['invented_top_level_field'] = True
        with self.assertRaisesRegex(ValueError, 'Additional properties'):
            prepare_record(value)

    def test_bad_proof_endpoint_rejected_without_publishing(self):
        entry = self.root / 'main.tex'
        entry.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{a}A.\end{lemma}')
        store = self.root / 'store'
        ingest(entry, 'typed', store)
        previous = current_snapshot(store)
        sidecar = self.root / 'sidecar.json'
        sidecar.write_text(json.dumps({'schema_version': 'qecgraph.annotations.v1', 'edges': [
            {'source': 'label:a', 'target': 'label:a', 'relation': 'proof_of'}]}))
        with self.assertRaisesRegex(ValueError, 'Invalid proof_of endpoint'):
            ingest(entry, 'typed', store, annotations_path=sidecar)
        self.assertEqual(current_snapshot(store), previous)

    def test_unresolved_reference_is_visible_and_fails_strict_validation(self):
        registry = Registry(self.root / 'corpus')
        value = claim()
        value['refs'] = [{'relation': 'depends_on_declared', 'target': 'claim:missing'}]
        registry.add_record(value)
        issues = registry.validate()['issues']
        self.assertEqual(issues[0]['code'], 'unresolved_reference')
        self.assertEqual(execute(registry.root, 'context', value['id'])['diagnostics'][0]['code'], 'unresolved_reference')

    def test_v2_is_read_losslessly_and_explicitly_migrated_to_new_revision(self):
        old = claim()
        old['schema_version'] = 'qecgraph.record.v2'
        old['data'] = {'statement': 'Legacy incomplete claim'}
        original = prepare_record(old, allow_legacy=True)
        with self.assertRaisesRegex(ValueError, 'explicit migration'):
            prepare_record(original)
        path = self.root / 'old.json'
        path.write_text(json.dumps(original))
        report = migrate(path, self.root / 'migration')
        self.assertEqual(report['status'], 'passed')
        converted = read_json(self.root / 'migration' / report['accepted'][0]['output_path'])
        self.assertEqual(converted['schema_version'], 'qecgraph.record.v3')
        self.assertEqual(converted['id'], original['id'])
        self.assertNotEqual(converted['revision'], original['revision'])
        self.assertEqual(converted['extensions']['pre_validation_record'], original)
        self.assertIsNone(converted['data']['quantifiers'])


if __name__ == '__main__':
    unittest.main()
