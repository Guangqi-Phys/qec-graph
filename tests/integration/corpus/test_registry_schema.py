import tempfile
import unittest
from pathlib import Path

from qecgraph.core.graph import canonical, hash_text
from qecgraph.core.transactions import ManagedDataError, atomic_json
from qecgraph.registry import Registry, empty_state


class RegistrySchemaTests(unittest.TestCase):
    def test_hashed_invalid_states_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Registry(directory)
            for field, value in (('materials', []), ('versions', {'x': {}}),
                                 ('format_version', 1), ('works', None)):
                with self.subTest(field=field):
                    state = {**empty_state('workspace:test'), field: value}
                    digest = hash_text(canonical(state))
                    atomic_json(Path(directory) / 'states' / (digest + '.json'), state)
                    with self.assertRaises(ManagedDataError):
                        registry.read(digest)

    def test_missing_version_and_legacy_corpus_fields_are_rejected_on_read_and_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Registry(directory)
            state = empty_state('workspace:test')
            legacy = {key: value for key, value in state.items() if key != 'format_version'}
            for invalid in (legacy, {**state, 'corpus_id': 'corpus:old', 'records': {}, 'links': []}):
                digest = hash_text(canonical(invalid))
                atomic_json(Path(directory) / 'states' / (digest + '.json'), invalid)
                with self.assertRaises(ManagedDataError):
                    registry.read(digest, verify=False)
                with self.assertRaises(ManagedDataError):
                    registry.prepare_publication(invalid)

    def test_nested_ai_artifacts_have_a_publishable_shape(self):
        digest = 'a' * 64
        with tempfile.TemporaryDirectory() as directory:
            registry = Registry(directory)
            for malformed in (
                {'status': 'complete', 'written': ['not a binding'], 'errors': []},
                {'status': 'pending', 'written': [], 'errors': [{'skill': 'extract_data'}]},
            ):
                with self.subTest(malformed=malformed):
                    state = {**empty_state('workspace:test'), 'materials': {digest: {
                        'archive_sha256': digest, 'status': 'archived_only', 'processing_completed': False,
                        'ai_extraction': malformed,
                    }}}
                    with self.assertRaises(ManagedDataError):
                        registry.prepare_publication(state)


    def test_normalization_requires_a_complete_source_map_binding(self):
        digest = 'a' * 64
        with tempfile.TemporaryDirectory() as directory:
            registry = Registry(directory)
            state = {**empty_state('workspace:test'), 'materials': {digest: {
                'archive_sha256': digest, 'status': 'archived_only', 'processing_completed': False,
                'normalization_id': 'incomplete',
            }}}
            with self.assertRaises(ManagedDataError):
                registry.prepare_publication(state)

    def test_publication_rejects_malformed_material_diagnostics_and_generated_bindings(self):
        digest = 'a' * 64
        with tempfile.TemporaryDirectory() as directory:
            registry = Registry(directory)
            state = empty_state('workspace:test')
            for invalid in (
                {'materials': {digest: {'archive_sha256': digest, 'status': 'parse_failed',
                                          'processing_completed': False, 'diagnostics': [{'severity': 'bad'}]}}},
                {'generated_research': {'paper': {'source_snapshot_id': digest, 'bindings': [None]}}},
            ):
                with self.subTest(invalid=invalid), self.assertRaises(ManagedDataError):
                    registry.prepare_publication({**state, **invalid})
