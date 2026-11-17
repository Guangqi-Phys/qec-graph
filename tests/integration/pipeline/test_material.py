import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.preparation.build import Build
from qecgraph.preparation.contract import read_material
from qecgraph.preparation.pipeline import prepare_material


class MaterialPipelineTests(unittest.TestCase):
    def test_byte_projection_without_matching_pdf_text_stays_partial(self):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            raw = (
                rb"\documentclass{article}\begin{document}"
                + b"Text \xa8."
                + rb"\end{document}"
            )
            source.write_bytes(raw)

            def different(original, derived, report):
                report["pdf_text"] = "different"

            out = Path(temp) / "material"
            with patch(
                "qecgraph.preparation.projection._compare_pdf_text",
                side_effect=different,
            ):
                result = prepare_material(source, out, compiler=self.compiler)
            self.assertEqual(result["status"], "partial")
            material = read_material(out)
            self.assertFalse(material["source_projection"]["verified"])
            self.assertEqual(material["document"]["nodes"], [])
            self.assertEqual((out / "sources/main.tex").read_bytes(), raw)

    def test_duplicate_labels_are_prepared_without_claiming_unique_bindings(self):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text(
                r"\documentclass{article}\begin{document}"
                r"\section{Body}\label{dup}First.\label{dup}Second.\ref{dup}"
                r"\end{document}"
            )
            out = Path(temp) / "material"
            result = prepare_material(source, out, compiler=self.compiler)
            material = read_material(out)
            self.assertEqual(result["status"], "ready")
            caps = material["manifest"]["preparation_capabilities"]
            self.assertEqual(caps["body_syntax"], "complete")
            self.assertEqual(caps["cross_reference_bindings"], "partial")
            self.assertEqual(caps["cross_reference_preparation"], "complete")
            self.assertIn("cross_reference_ambiguous", material["manifest"]["warnings"])
            self.assertEqual(
                len(caps["unresolved_cross_references"][0]["candidates"]), 2
            )
            manifest = material["manifest"]
            manifest["preparation_capabilities"]["cross_reference_bindings"] = (
                "complete"
            )
            (out / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "capabilities"):
                read_material(out)

    def test_missing_reference_still_blocks_preparation_with_ambiguity_preserved(self):
        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text(
                r"\documentclass{article}\begin{document}"
                r"\label{dup}First.\label{dup}Second.\ref{dup}\ref{missing}"
                r"\end{document}"
            )
            out = Path(temp) / "material"
            result = prepare_material(source, out, compiler=self.compiler)
            material = read_material(out)
            self.assertEqual(result["status"], "partial")
            caps = material["manifest"]["preparation_capabilities"]
            self.assertEqual(caps["cross_reference_preparation"], "partial")
            self.assertEqual(
                [row["status"] for row in caps["unresolved_cross_references"]],
                ["ambiguous", "unresolved"],
            )
            self.assertEqual(
                [row["code"] for row in material["coverage"]["diagnostics"]],
                ["cross_reference_unresolved"],
            )
            manifest = material["manifest"]
            manifest["status"] = "ready"
            (out / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "unresolved cross-reference"):
                read_material(out)

    def test_reopening_rejects_dropped_candidates_even_with_refreshed_hashes(self):
        from qecgraph.preparation.contract import digest, json_bytes

        self.calls, self.succeeds = [], True
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text(
                r"\documentclass{article}\begin{document}"
                r"\label{dup}First.\label{dup}Second.\ref{dup}\end{document}"
            )
            out = Path(temp) / "material"
            prepare_material(source, out, compiler=self.compiler)
            material = read_material(out)
            document = material["document"]
            target = document["cross_references"][0]["targets"][0]
            target["nodes"] = target["nodes"][:1]
            target["status"] = "resolved"
            raw = json_bytes(document)
            (out / "content.json").write_bytes(raw)
            manifest = material["manifest"]
            manifest["artifacts"]["content.json"] = digest(raw)
            (out / "manifest.json").write_bytes(json_bytes(manifest))
            with self.assertRaisesRegex(ValueError, "Cross-reference candidates"):
                read_material(out)

    def test_reopen_compares_macro_include_arguments_in_json_form(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "main.tex").write_text(
                r"\documentclass{article}\newcommand{\PART}{part}"
                r"\begin{document}\input{\PART}\end{document}"
            )
            (source / "part.tex").write_text("Included body.")

            def compiler(tree, entry, work, **kwargs):
                tree.materialize(work / "project")
                return Build(
                    entry,
                    "pdflatex",
                    work,
                    success=True,
                    inputs=["main.tex", "part.tex"],
                )

            out = root / "material"
            prepare_material(source, out, compiler=compiler)
            loaded = read_material(out)
            self.assertIn("Included body.", loaded["entry_tex"])
            source_map = json.loads((out / "source-map.json").read_bytes())
            event = next(e for e in source_map["directives"] if e["kind"] == "input")
            self.assertEqual(event["expanded_args"], ["part"])

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

    def test_many_aux_labels_share_an_index_but_later_reads_revalidate_bytes(self):
        from qecgraph.preparation.contract import SourceIndex, digest, json_bytes

        labels = [f"label:{index}" for index in range(200)]
        aux = "".join(
            r"\newlabel{" + key + r"}{{1}{1}}" + "\n" for key in labels
        ).encode()
        body = "".join(r"\label{" + key + "}" for key in labels)
        raw = (
            r"\documentclass{article}\begin{document}"
            + body
            + "Unicode α."
            + r"\end{document}"
        ).encode()

        def compiler(tree, entry, root, **kwargs):
            tree.materialize(root / "project")
            (root / "project/main.aux").write_bytes(aux)
            return Build(
                entry,
                "pdflatex",
                root,
                success=True,
                inputs=[entry, "main.aux"],
                artifacts={"files/main.aux": aux},
            )

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_bytes(raw)
            out = Path(temp) / "material"
            prepare_material(source, out, compiler=compiler)
            with patch(
                "qecgraph.preparation.contract.SourceIndex", wraps=SourceIndex
            ) as indexes:
                material = read_material(out)
            self.assertEqual(len(material["references"]["observed_labels"]), 200)
            self.assertEqual(
                sum(call.args[0] == aux for call in indexes.call_args_list), 1
            )
            changed = aux + b"% changed after the first read\n"
            (out / "build/files/main.aux").write_bytes(changed)
            manifest = material["manifest"]
            manifest["artifacts"]["build/files/main.aux"] = digest(changed)
            (out / "manifest.json").write_bytes(json_bytes(manifest))
            with self.assertRaisesRegex(ValueError, "Compiled label observation"):
                read_material(out)
