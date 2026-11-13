import json
import tempfile
import unittest
from pathlib import Path

from qecgraph.core.graph import read_json
from qecgraph.store import current_snapshot, ingest


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

    def test_bad_proof_endpoint_rejected_without_publishing(self):
        entry = self.root / 'main.tex'
        entry.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{a}A.\end{lemma}')
        store = self.root / 'store'
        ingest(entry, 'typed', store)
        previous = current_snapshot(store)
        sidecar = self.root / 'sidecar.json'
        sidecar.write_text(json.dumps({'schema': 'qecgraph.annotations', 'edges': [
            {'source': 'label:a', 'target': 'label:a', 'relation': 'proof_of'}]}))
        with self.assertRaisesRegex(ValueError, 'Invalid proof_of endpoint'):
            ingest(entry, 'typed', store, annotations_path=sidecar)
        self.assertEqual(current_snapshot(store), previous)


if __name__ == '__main__':
    unittest.main()
