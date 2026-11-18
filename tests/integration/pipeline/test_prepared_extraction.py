from pathlib import Path
import tempfile
import unittest

from qecgraph.preparation.artifacts import digest, json_bytes
from qecgraph.preparation.execution import Build
from qecgraph.preparation.pipeline import prepare_material
from qecgraph.prepared_extraction import PreparedSource, extract_source
from tools.extract_prepared import main
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO


class PreparedExtractionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        sources = self.root / "sources"
        sources.mkdir()
        self.main = (
            "\\documentclass{article}\n\\title{Source α}\\author{Ada Example}\n"
            "\\newtheorem{lemma}{Lemma}\n\\begin{document}\n\\section{Scope}\n"
            "Before input \\input{body} after input.\n\n"
            "\\label{key}One.\\label{key}Two.\\ref{key}\n\\end{document}\n"
        )
        self.body = (
            "inside input.\n\n\\begin{lemma}A statement with $[[7,1,3]]$.\\end{lemma}\n"
            "\\begin{figure}\\caption{Authored caption.}\\end{figure}\n"
            "\\begin{tabular}{cc}Header & Value\\\\ Item & 3\\end{tabular}\n"
        )
        (sources / "main.tex").write_text(self.main)
        (sources / "body.tex").write_text(self.body)
        self.material = self.root / "material"
        prepare_material(
            sources, self.material, entry="main.tex", compiler=self.compile
        )

    @staticmethod
    def compile(tree, entry, root, **kwargs):
        tree.materialize(root / "project")
        return Build(entry, "pdflatex", root, success=True, inputs=list(tree.files))

    def test_extracts_program_items_and_preserves_all_reference_candidates(self):
        source = PreparedSource(self.material)
        result = extract_source(source)
        self.assertEqual(result["input"]["status"], "ready")
        self.assertEqual(result["semantic"], {})
        extracted = result["source"]
        self.assertEqual(
            extracted["cross_references"], source.document["cross_references"]
        )
        target = extracted["cross_references"][0]["targets"][0]
        self.assertEqual((target["status"], len(target["nodes"])), ("ambiguous", 2))
        self.assertEqual(extracted["bibliography"], source.material["references"])

        units = {row["kind"]: row for row in extracted["units"]}
        self.assertIn("Source α", units["title"]["latex"])
        self.assertIn("[[7,1,3]]", units["formula"]["latex"])
        self.assertIn("Value", str(units["table"]["data"]["rows"]))
        self.assertIn("Authored caption.", units["caption"]["latex"])
        self.assertEqual(
            units["code_parameters_mention"]["data"]["status"], "candidate"
        )
        self.assertEqual(units["statement"]["source_spans"][0]["path"], "body.tex")
        for row in extracted["units"]:
            start, end = row["entry_range"]
            self.assertEqual(row["latex"], source.text[start:end])
            self.assertEqual(row["source_spans"], source.spans(start, end))

    def test_entry_ranges_resolve_multiple_original_files(self):
        source = PreparedSource(self.material)
        start = source.text.index("Before input")
        end = source.text.index("inside input") + len("inside input")
        spans = source.spans(start, end)
        self.assertEqual([span["path"] for span in spans], ["main.tex", "body.tex"])
        parts = []
        for span in spans:
            file = (self.material / "sources" / span["path"]).read_bytes()
            self.assertEqual(span["sha256"], digest(file))
            first, last = span["bytes"]
            parts.append(file[first:last].decode())
        self.assertEqual("".join(parts), source.text[start:end])

    def test_cli_verifies_saved_output_and_rejects_writes_into_material(self):
        out = self.root / "extraction.json"
        args = [str(self.material), "--out", str(out)]
        original = (self.material / "manifest.json").read_bytes()
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(args), 0)
            self.assertEqual(main([*args, "--check"]), 0)
            out.write_bytes(json_bytes({}))
            self.assertEqual(main([*args, "--check"]), 1)
            self.assertEqual(
                main([str(self.material), "--out", str(self.material / "extra")]), 1
            )
        self.assertEqual((self.material / "manifest.json").read_bytes(), original)
        self.assertFalse((self.material / "extra").exists())
