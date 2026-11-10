import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from qecgraph.graph import read_json
from qecgraph.migrations import migrate
from qecgraph.registry import Registry
from qecgraph.store import ingest

from tests.support import ROOT


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_legacy_catalog_keeps_ids_evidence_unknowns_and_managed_assets(self):
        starter = ROOT / 'legacy/knowledge_starter'
        source_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in starter.rglob('*.json')}
        report = migrate(starter / 'records', self.root / 'migration', source_root=starter)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(len(report['accepted']), 10)
        registry = Registry(self.root / 'corpus')
        imported = registry.import_migration(self.root / 'migration')
        record = registry.record('presentation:rep3-hgp:standard')
        matrix_uri = record['data']['matrices']['HX']
        self.assertEqual(registry.asset_bytes(matrix_uri), (starter / 'assets/matrices/HX.gf2.json').read_bytes())
        matrix_path = registry.root / 'assets' / matrix_uri.rsplit(':', 1)[-1]
        os.utime(matrix_path, (1_000_000_000, 1_000_000_000))
        before = matrix_path.stat()
        self.assertEqual(registry.import_migration(self.root / 'migration'), imported)
        self.assertEqual(matrix_path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(matrix_path.stat().st_ino, before.st_ino)
        self.assertIn('legacy_canonical_sha256', record['assets'][0])
        self.assertEqual(record['extensions']['legacy_record'], read_json(starter / 'records/presentation_rep3_hgp.json'))
        claim = registry.record('claim:rep3-hgp:distance')
        self.assertEqual(claim['data']['verification_level'], 'computed_exact')
        self.assertEqual(claim['review']['status'], 'imported')
        self.assertEqual(claim['provenance']['mathematical_recheck'], 'not_performed')
        formal = registry.record('formalization:rep3-hgp:distance')
        self.assertIsNone(formal['data']['lean_declaration'])
        self.assertEqual(formal['data']['proof_progress'], 'not_started')
        for path, digest in source_hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        # A relocated corpus resolves its own managed URIs, independent of the migration root.
        moved = self.root / 'relocated'
        registry.root.rename(moved)
        self.assertEqual(Registry(moved).asset_bytes(matrix_uri), (starter / 'assets/matrices/HX.gf2.json').read_bytes())

    def test_graph_and_sidecar_passthrough_are_byte_exact(self):
        result = ingest(ROOT / 'examples/paper/main.tex', 'migration-demo', self.root / 'store')
        for index, source in enumerate([Path(result['snapshot']) / 'graph.json', ROOT / 'examples/annotations.example.json']):
            value = read_json(source)
            value['unknown_extension'] = {'uninterpreted': True}
            input_path = self.root / f'input-{index}.json'
            input_path.write_text(json.dumps(value, ensure_ascii=False))
            out = self.root / f'migration-{index}'
            report = migrate(input_path, out)
            self.assertEqual(report['status'], 'passed')
            self.assertEqual((out / report['accepted'][0]['output_path']).read_bytes(), input_path.read_bytes())

    def test_import_rejects_malformed_reports_before_opening_the_registry(self):
        path = self.root / 'migration-report.json'
        registry = Registry(self.root / 'corpus')
        schema = {'schema_version': 'qecgraph.migration.v1', 'rejected': []}
        for report, reason in (
            ([], 'requires a migration report'),
            ({**schema, 'accepted': {}}, 'accepted array'),
            ({**schema, 'accepted': [None]}, r'accepted\[0\]'),
            ({**schema, 'accepted': [{'output_schema': 'qecgraph.record.v3'}]}, r'accepted\[0\]'),
        ):
            with self.subTest(report=report):
                path.write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, reason):
                    registry.import_migration(self.root)
                self.assertFalse(registry.root.exists())

    def test_unknown_schema_and_missing_external_asset_are_reported(self):
        source = self.root / 'future.json'
        source.write_text('{"schema_version":"future.v99","unknown":42}')
        report = migrate(source, self.root / 'future-out')
        self.assertEqual(report['status'], 'partial')
        self.assertIn('kept opaque', report['rejected'][0]['reason'])
        self.assertEqual((self.root / 'future-out' / report['rejected'][0]['original_path']).read_bytes(), source.read_bytes())
        legacy = ROOT / 'legacy/knowledge_starter/records/presentation_rep3_hgp.json'
        report = migrate(legacy, self.root / 'missing-assets')
        self.assertIn('explicit --source-root', report['rejected'][0]['reason'])
        with self.assertRaisesRegex(ValueError, 'no rejected'):
            Registry(self.root / 'corpus').import_migration(self.root / 'missing-assets')


if __name__ == '__main__':
    unittest.main()
