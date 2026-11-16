import copy
import json
import unittest

from qecgraph.preparation.contract import (
    digest,
    json_bytes,
    safe_path,
    validate_material,
)


class MaterialContractTests(unittest.TestCase):
    def material(self):
        raw = "α\nText $d \\leq 12$.".encode()
        text = raw.decode()
        span = {
            "path": "main.tex",
            "sha256": digest(raw),
            "encoding": "utf-8",
            "chars": [0, len(text)],
            "bytes": [0, len(raw)],
            "lines": [1, 2],
        }
        doc = {
            "roots": ["node:0"],
            "nodes": [
                {
                    "id": "node:0",
                    "range": [0, len(text)],
                    "parent": None,
                    "children": [],
                    "source_spans": [span],
                }
            ],
        }
        files = {
            "entry.tex": raw,
            "sources/main.tex": raw,
            "content.json": json_bytes(doc),
        }
        return files

    def finish(self, files):
        files["manifest.json"] = json_bytes(
            {
                "schema": "qecgraph.prepare/3",
                "status": "partial",
                "artifacts": {
                    name: digest(raw)
                    for name, raw in files.items()
                    if name != "manifest.json"
                },
            }
        )
        return files

    def test_original_codepoints_bytes_and_lines_are_independently_checked(self):
        files = self.finish(self.material())
        self.assertTrue(validate_material(files)["source_fidelity"])
        broken = copy.deepcopy(files)
        doc = json.loads(broken["content.json"])
        doc["nodes"][0]["source_spans"][0]["bytes"][1] -= 1
        broken["content.json"] = json_bytes(doc)
        with self.assertRaisesRegex(ValueError, "byte/codepoint"):
            validate_material(self.finish(broken))

    def test_preserving_hashes_does_not_hide_missing_text_or_parent_cycles(self):
        files = self.material()
        doc = json.loads(files["content.json"])
        doc["roots"] = []
        files["content.json"] = json_bytes(doc)
        with self.assertRaisesRegex(ValueError, "tail"):
            validate_material(self.finish(files))

    def test_material_paths_cannot_escape(self):
        for name in ("../key", "/etc/passwd", "sources/../key", "a//b", "a\\b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_path(name)
