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
                                 ('format_version', 2), ('works', None)):
                with self.subTest(field=field):
                    state = {**empty_state(), field: value}
                    digest = hash_text(canonical(state))
                    atomic_json(Path(directory) / 'states' / (digest + '.json'), state)
                    with self.assertRaises(ManagedDataError):
                        registry.read(digest)

    def test_legacy_read_preserves_hash_and_next_write_upgrades(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Registry(directory)
            legacy = empty_state()
            legacy.pop('format_version')
            digest = hash_text(canonical(legacy))
            path = Path(directory) / 'states' / (digest + '.json')
            atomic_json(path, legacy)
            before = path.read_bytes()
            state, read_digest = registry.read(digest)
            self.assertEqual(read_digest, digest)
            self.assertNotIn('format_version', state)
            new_digest = registry.prepare_publication(state)
            self.assertEqual(registry.read(new_digest)[0]['format_version'], 1)
            self.assertEqual(path.read_bytes(), before)
