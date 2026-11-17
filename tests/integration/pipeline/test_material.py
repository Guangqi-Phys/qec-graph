import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.preparation.build import Build
from qecgraph.preparation.contract import read_material
from qecgraph.preparation.pipeline import prepare_material


class MaterialPipelineTests(unittest.TestCase):
    def compiler(self, tree, entry, root, **kwargs):
        self.calls.append("compile")
        tree.materialize(root / "project")
        return Build(entry, "pdflatex", root, success=self.succeeds, inputs=[entry])

    def test_material_handoff_reopens_and_partial_attempt_keeps_previous_ready(self):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            source = parent / "main.tex"
            original = rb"\documentclass{article}\begin{document}\section{Scope}An upper bound $d\leq12$.\end{document}"
            source.write_bytes(original)
            out = parent / "material"
            result = prepare_material(source, out, compiler=self.compiler)
            self.assertEqual(result["status"], "ready")
            loaded = read_material(out)
            self.assertTrue(loaded["validation"]["source_fidelity"])
            self.assertTrue(loaded["coverage"]["complete"])
            math = next(n for n in loaded["document"]["nodes"] if n["kind"] == "math")
            start, end = math["range"]
            self.assertEqual(loaded["entry_tex"][start:end], r"$d\leq12$")
            self.assertIn(r"\(d\leq12\)", loaded["normalized_tex"])
            self.assertEqual((out / "original.package").read_bytes(), original)
            previous = (out / "manifest.json").read_bytes()
            self.succeeds = False
            failed = prepare_material(source, out, compiler=self.compiler)
            self.assertEqual(failed["status"], "partial")
            self.assertTrue(failed["previous_retained"])
            self.assertEqual((out / "manifest.json").read_bytes(), previous)
            self.assertTrue(Path(failed["out"]).joinpath("sources/main.tex").exists())
            self.assertEqual(self.calls, ["compile", "compile", "compile"])

    def test_failing_compile_never_runs_body_conversion_or_a_model(self):
        self.calls, self.succeeds = [], False
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text(
                r"\documentclass{article}\begin{document}Body.\end{document}"
            )
            with patch(
                "qecgraph.preparation.pipeline.convert_source",
                side_effect=AssertionError("must compile first"),
            ):
                result = prepare_material(
                    source, Path(temp) / "out", compiler=self.compiler
                )
            self.assertEqual(result["status"], "partial")
            manifest = json.loads((Path(temp) / "out/manifest.json").read_bytes())
            self.assertEqual(manifest["model_calls"], 0)

    def test_tampered_asset_and_unknown_schema_are_rejected_on_reopen(self):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text(
                r"\documentclass{article}\begin{document}Body.\end{document}"
            )
            out = Path(temp) / "out"
            prepare_material(source, out, compiler=self.compiler)
            (out / "sources/main.tex").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "hash|changed"):
                read_material(out)

    def test_original_package_is_captured_once_before_the_build(self):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "main.tex"
            original = (
                rb"\documentclass{article}\begin{document}Original.\end{document}"
            )
            source.write_bytes(original)

            def compiler(tree, entry, folder, **options):
                result = self.compiler(tree, entry, folder, **options)
                source.write_bytes(b"Replaced while compilation was running")
                return result

            out = root / "material"
            prepare_material(source, out, compiler=compiler)
            self.assertEqual((out / "original.package").read_bytes(), original)
            self.assertEqual((out / "sources/main.tex").read_bytes(), original)
            self.assertTrue(read_material(out)["validation"]["source_fidelity"])

    def test_derived_compiler_exception_does_not_erase_successful_source_conversion(
        self,
    ):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_bytes(
                rb"\documentclass{article}\begin{document}Body.\end{document}"
            )

            def compiler(tree, entry, root, **options):
                if self.calls:
                    raise ValueError("Derived compiler failed")
                return self.compiler(tree, entry, root, **options)

            result = prepare_material(
                source, Path(temp) / "material", compiler=compiler
            )
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["stages"]["conversion"], "complete")
            self.assertEqual(result["stages"]["normalized_latex"], "partial")

    def test_preparation_does_not_call_scientific_parser_or_model(self):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_bytes(
                rb"\documentclass{article}\begin{document}Text.\end{document}"
            )
            with (
                patch(
                    "qecgraph.source.parser.parse_project",
                    side_effect=AssertionError("scientific parser called"),
                ),
                patch(
                    "qecgraph.llm.client.LLMClient.complete_json",
                    side_effect=AssertionError("model called"),
                ),
            ):
                result = prepare_material(
                    source, Path(temp) / "out", compiler=self.compiler
                )
            self.assertEqual(result["status"], "ready")

    def test_failed_normalized_compile_is_partial_and_keeps_the_original_material(self):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            original = rb"\documentclass{article}\begin{document}$x$.\end{document}"
            source.write_bytes(original)

            def compiler(tree, entry, root, **options):
                self.succeeds = not self.calls
                return self.compiler(tree, entry, root, **options)

            out = Path(temp) / "material"
            result = prepare_material(source, out, compiler=compiler)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["stages"]["compile"], "complete")
            self.assertEqual(result["stages"]["normalized_latex"], "partial")
            self.assertEqual((out / "sources/main.tex").read_bytes(), original)
            self.assertTrue(read_material(out)["validation"]["source_fidelity"])

    def test_ready_manifest_lists_non_blocking_observations(self):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "main.tex"
            source.write_bytes(
                rb"\documentclass{article}\begin{document}"
                rb"\label{dup}One.\label{dup}Two.\end{document}"
            )
            out = root / "material"
            result = prepare_material(source, out, compiler=self.compiler)
            self.assertEqual(result["status"], "ready")
            manifest = json.loads((out / "manifest.json").read_bytes())
            self.assertIn("duplicate_labels", manifest["warnings"])
