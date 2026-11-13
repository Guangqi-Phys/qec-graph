from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from qecgraph.source.package import SourceTree
from qecgraph.source.prepare import (
    entry_candidates,
    prepare_source,
    write_outputs,
)


class PrepareTests(unittest.TestCase):
    def test_prepare_builds_section_tree_and_text(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{Introduction}\nText.\n"
                         b"\\subsection{Details}\nMore.\n"
                         b"\\end{document}\n"),
        })
        prepared = prepare_source(tree)
        self.assertEqual(prepared.entry, "main.tex")
        self.assertTrue(prepared.coverage["content_complete"])
        self.assertTrue(prepared.coverage["structure_complete"])
        self.assertTrue(prepared.coverage["document_complete"])
        document = prepared.document
        self.assertEqual(document["schema"], "qecgraph.document/2")
        self.assertEqual([section["title"] for section in document["sections"]],
                         ["Introduction", "Details"])
        self.assertEqual([section["level"] for section in document["sections"]], [1, 2])
        self.assertEqual(document["sections"][1]["parent_id"],
                         document["sections"][0]["id"])
        texts = [block["text"] for block in document["blocks"]]
        self.assertIn("Text.", texts)
        self.assertIn("More.", texts)

    def test_content_detection_accepts_an_extensionless_entry(self):
        tree = SourceTree("directory", {
            "tqecp": (b"\\documentstyle[11pt]{article}\n\\begin{document}\n"
                      b"\\section{Introduction}\nText.\n\\end{document}\n"),
        })
        self.assertEqual(entry_candidates(tree), ["tqecp"])
        prepared = prepare_source(tree)
        self.assertEqual(prepared.entry, "tqecp")
        self.assertEqual([section["title"] for section in prepared.document["sections"]],
                         ["Introduction"])
        self.assertTrue(prepared.coverage["content_complete"])

    def test_missing_preamble_dependency_does_not_lose_content(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\input{missing-preamble}\n"
                         b"\\begin{document}\n\\section{Body}\nText.\n\\end{document}\n"),
        })
        prepared = prepare_source(tree)
        self.assertTrue(prepared.coverage["content_complete"])
        self.assertTrue(prepared.coverage["structure_complete"])
        self.assertEqual(prepared.coverage["preamble_missing"], 1)
        self.assertIn("Text.", [block["text"] for block in prepared.document["blocks"]])

    def test_write_outputs_matches_the_document_schema(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{Body}\nText.\n\\end{document}\n"),
        })
        prepared = prepare_source(tree)
        with TemporaryDirectory() as temporary:
            out = Path(temporary)
            manifest = write_outputs(prepared, out, parser_version="test")
            self.assertEqual(manifest["schema"], "qecgraph.prepare/2")
            self.assertEqual(json.loads((out / "document.json").read_text())["schema"],
                             "qecgraph.document/2")
            for name in ("entry.tex", "source-map.json", "document.json",
                         "coverage.json", "diagnostics.json", "manifest.json"):
                self.assertTrue((out / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
