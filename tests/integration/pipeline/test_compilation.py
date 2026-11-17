"""Explicit local compiler checks; ordinary tests never execute untrusted TeX."""

import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.preparation.contract import digest

from qecgraph.preparation import sandbox
from qecgraph.preparation.build import compile_tree
from qecgraph.preparation.pipeline import prepare_material
from qecgraph.preparation.contract import read_material
from qecgraph.source.package import SourceTree


@unittest.skipUnless(
    os.environ.get("QECGRAPH_TEST_TEX") == "1",
    "Set QECGRAPH_TEST_TEX=1 for isolated local TeX checks",
)
class LocalCompilerTests(unittest.TestCase):
    def test_repeated_reference_targets_are_ready_and_preserved_after_native_compile(self):
        raw = (
            rb"\documentclass{article}\begin{document}"
            rb"\begin{equation}x=1\label{dup}\end{equation}"
            rb"\begin{equation}x=2\label{dup}\end{equation}"
            rb"See \ref{dup}.\end{document}"
        )
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_bytes(raw)
            out = Path(temp) / "material"
            result = prepare_material(source, out)
            material = read_material(out)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(material["normalization"]["pdf_text"], "equal")
            target = material["document"]["cross_references"][0]["targets"][0]
            self.assertEqual(target["status"], "ambiguous")
            self.assertEqual(len(target["nodes"]), 2)
            self.assertEqual((out / "sources/main.tex").read_bytes(), raw)

    def test_explicit_support_is_consumed_before_system_packages(self):
        from qecgraph.preparation.build import tool

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "project").mkdir()
            support = root / "texmf/tex/generic/qecgraph"
            support.mkdir(parents=True)
            (support / "array.sty").write_text("% explicit support selection probe")
            result = sandbox.run(
                root,
                root / "project",
                [tool("kpsewhich"), "--progname=pdflatex", "array.sty"],
            )
            self.assertEqual(result["exit"], 0)
            self.assertIn(
                b"<build>/texmf/tex/generic/qecgraph/array.sty", result["log"]
            )
            (root / "project/array.sty").write_text("% author source takes precedence")
            result = sandbox.run(
                root,
                root / "project",
                [tool("kpsewhich"), "--progname=pdflatex", "array.sty"],
            )
            self.assertIn(b"./array.sty", result["log"])

    def test_harvmac_keeps_native_math_outline_and_compiled_bibliography(self):
        original = rb"""\input harvmac
\Title{Native}{A native source}
\newsec{Introduction}
\eqn\ifa{x=1.}
See \ifa. \ref\book{A. Author, A Book.}
\listrefs
\end
"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            source.mkdir()
            (source / "main.tex").write_bytes(original)
            result = prepare_material(source, root / "out")
            self.assertEqual(result["status"], "ready", result)
            material = read_material(root / "out")
            self.assertEqual(material["normalized_tex"].encode(), original)
            self.assertEqual(
                material["document"]["outline"][0]["title_tex"], "{Introduction}"
            )
            equations = [
                n
                for n in material["document"]["nodes"]
                if n.get("syntax") == "harvmac_eqn"
            ]
            self.assertEqual(equations[0]["math_tex"], "x=1.")
            self.assertEqual(material["references"]["bindings"][0]["key"], "book")
            self.assertEqual(
                material["references"]["bindings"][0]["display_tex"], "[1]"
            )
            self.assertEqual(material["normalization"]["pdf_text"], "equal")
            manifest = material["manifest"]
            files = {p: (root / "out" / p).read_bytes() for p in manifest["artifacts"]}
            from qecgraph.preparation.contract import validate_material, json_bytes

            document = material["document"]
            document["dialect"]["grammar_version"] += 1
            files["content.json"] = json_bytes(document)
            manifest["artifacts"] = {p: digest(raw) for p, raw in files.items()}
            files["manifest.json"] = json_bytes(manifest)
            with self.assertRaisesRegex(ValueError, "Harvmac grammar"):
                validate_material(files)

    def test_invalid_byte_projection_preserves_original_and_rejects_forged_spelling(
        self,
    ):
        from qecgraph.preparation.contract import validate_material, json_bytes

        original = (
            rb"\UseRawInputEncoding\documentclass{article}\begin{document}"
            b"Body.\\begin{thebibliography}{1}\\bibitem{k}Pages 1\xa8C--2."
            rb"\end{thebibliography}\end{document}"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            source.mkdir()
            (source / "main.tex").write_bytes(original)
            result = prepare_material(source, root / "out", entry="main.tex")
            self.assertEqual(result["status"], "ready", result)
            material = read_material(root / "out")
            self.assertIn("^^a8", material["entry_tex"])
            projected = [
                s
                for n in material["document"]["nodes"]
                for s in n["source_spans"]
                if s["layer"] == "projected"
            ]
            self.assertTrue(projected)
            self.assertTrue(
                all(
                    s["original_source"]["sha256"] == digest(original)
                    for s in projected
                )
            )
            manifest = material["manifest"]
            files = {p: (root / "out" / p).read_bytes() for p in manifest["artifacts"]}
            files["projected-sources/main.tex"] = files[
                "projected-sources/main.tex"
            ].replace(b"^^a8", b"^^a9")
            manifest["artifacts"] = {p: digest(raw) for p, raw in files.items()}
            files["manifest.json"] = json_bytes(manifest)
            with self.assertRaisesRegex(ValueError, "Projected source bytes"):
                validate_material(files)
            self.assertEqual((source / "main.tex").read_bytes(), original)

    def test_false_literal_branch_and_known_legacy_hook_round_trip(self):
        cls = rb"\NeedsTeXFormat{LaTeX2e}\ProvidesClass{quantumarticle}\LoadClass{article}\AtEndDocument{\@afterenddocumenthook}"
        original = rb"""\documentclass{quantumarticle}\begin{document}Visible.
\if 0
Inactive \end{now} \cite{absent}
\fi
End.\end{document}\end{now}"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            source.mkdir()
            (source / "main.tex").write_bytes(original)
            (source / "quantumarticle.cls").write_bytes(cls)
            with patch(
                "qecgraph.preparation.compatibility.QUANTUMARTICLE_42", digest(cls)
            ):
                result = prepare_material(source, root / "out", entry="main.tex")
            self.assertEqual(result["status"], "ready", result)
            material = read_material(root / "out")
            self.assertEqual(material["normalization"]["pdf_text"], "equal")
            self.assertTrue(material["document"]["inactive_ranges"])
            self.assertTrue(material["normalization"]["compatibility"])
            self.assertEqual((source / "main.tex").read_bytes(), original)
            self.assertEqual((source / "quantumarticle.cls").read_bytes(), cls)

    def test_runtime_guard_view_skips_missing_include_and_rejects_forged_choice(self):
        from qecgraph.preparation.contract import validate_material, json_bytes

        original = rb"""\ifx\mainflag\undefined
\documentclass{article}
\def\mainflag{}
\begin{document}
\fi
\ifdefined\mainflag
Visible $x$.
\else
\input{absent}\end{broken}\cite{ghost}
\fi
\end{document}"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            source.mkdir()
            (source / "main.tex").write_bytes(original)
            result = prepare_material(source, root / "out", entry="main.tex")
            self.assertEqual(result["status"], "ready", result)
            loaded = read_material(root / "out")
            self.assertEqual(loaded["document"]["citations"], [])
            self.assertEqual(len(loaded["document"]["observed_guards"]), 2)
            self.assertIn(r"\input{absent}", loaded["entry_tex"])
            self.assertIn(r"\iftrue", loaded["normalized_tex"])
            manifest = json.loads((root / "out/manifest.json").read_bytes())
            files = {p: (root / "out" / p).read_bytes() for p in manifest["artifacts"]}
            view = json.loads(files["build-view.json"])
            view["guards"][0]["selected"] = False
            files["build-view.json"] = json_bytes(view)
            document = loaded["document"]
            document["build_view_sha256"] = digest(files["build-view.json"])
            files["content.json"] = json_bytes(document)
            manifest["artifacts"] = {p: digest(raw) for p, raw in files.items()}
            files["manifest.json"] = json_bytes(manifest)
            with self.assertRaisesRegex(ValueError, "TeX log"):
                validate_material(files)
            self.assertEqual((source / "main.tex").read_bytes(), original)

    def test_source_class_declaration_and_aux_jointly_bind_box_labels(self):
        cls = rb"\NeedsTeXFormat{LaTeX2e}\ProvidesClass{boxed}\LoadClass{article}\RequirePackage{tcolorbox}\newtcolorbox[auto counter]{sourcebox}[1][]{#1}"
        original = rb"\documentclass{boxed}\begin{document}\begin{sourcebox}[label={box:source}]Body.\end{sourcebox}See \ref{box:source}.\end{document}"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            source.mkdir()
            (source / "main.tex").write_bytes(original)
            (source / "boxed.cls").write_bytes(cls)
            result = prepare_material(source, root / "out", entry="main.tex")
            self.assertEqual(result["status"], "ready", result)
            loaded = read_material(root / "out")
            declaration = loaded["document"]["environment_label_declarations"][0]
            self.assertEqual(declaration["origin"]["path"], "boxed.cls")
            self.assertEqual(declaration["origin"]["sha256"], digest(cls))
            self.assertEqual(
                loaded["document"]["labels"][0]["declaration"], declaration["origin"]
            )

    def test_nocite_wildcard_and_subdirectory_entry_keep_runtime_bibliography(self):
        original = rb"\documentclass{article}\begin{document}Body.\nocite{*}\bibliographystyle{plain}\bibliography{refs}\end{document}"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            (source / "sub").mkdir(parents=True)
            (source / "sub/main.tex").write_bytes(original)
            (source / "refs.bib").write_text(
                "@article{a,author={Ada Example},title={First},journal={Test},year={2020}}\n@article{b,author={Ben Example},title={Second},journal={Test},year={2021}}"
            )
            result = prepare_material(source, root / "out", entry="sub/main.tex")
            self.assertEqual(result["status"], "ready", result)
            loaded = read_material(root / "out")
            self.assertEqual(
                [r["key"] for r in loaded["references"]["bindings"]], ["a", "b"]
            )
            call = next(
                c
                for c in loaded["document"]["citations"]
                if c["origin"] == "compiled_nocite_wildcard"
            )
            self.assertEqual(call["keys"], ["a", "b"])
            self.assertEqual(loaded["normalization"]["pdf_text"], "equal")

    def test_custom_citation_and_bibtex_are_resolved_without_source_edits(self):
        original = rb"""\documentclass{article}
\newcommand{\citeRef}[1]{\cite{ref:#1}}
\begin{document}An upper bound $d\leq12$. See \citeRef0.
\bibliographystyle{plain}\bibliography{references}\end{document}
"""
        tree = SourceTree(
            "tex",
            {
                "main.tex": original,
                "references.bib": b"@article{ref:0,author={Ada Example},title={A compiler fixture},journal={Test},year={2020}}",
            },
        )
        with tempfile.TemporaryDirectory() as temp:
            build = compile_tree(tree, "main.tex", Path(temp))
            self.assertTrue(build.success, build.steps)
            aux = build.artifacts["files/main.aux"]
            self.assertIn(rb"\citation{ref:0}", aux)
            self.assertIn(rb"\bibcite{ref:0}", aux)
            self.assertEqual(tree.files["main.tex"], original)

    def test_sandbox_denies_external_files_network_and_inherited_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            secret = parent / "sentinel.txt"
            secret.write_text("test sentinel")
            work = parent / "allowed"
            work.mkdir()
            command = [
                "/bin/sh",
                "-c",
                'cat "$1"; touch "$2"; test -z "$OPENROUTER_API_KEY"',
                "probe",
                str(secret),
                str(parent / "forbidden"),
            ]
            result = sandbox.run(work, work, command)
            self.assertNotIn(b"test sentinel", result["log"])
            self.assertFalse((parent / "forbidden").exists())
            self.assertEqual(result["exit"], 0)
            network = sandbox.run(
                work,
                work,
                ["/usr/bin/curl", "-v", "--max-time", "2", "http://127.0.0.1:9"],
            )
            self.assertIn(b"Operation not permitted", network["log"])

    def test_normalized_latex_recompiles_with_the_same_visible_text_and_bibliography(
        self,
    ):
        original = rb"""\documentclass{article}
\newcommand{\citeRef}[1]{\cite{ref:#1}}
\begin{document}An upper bound $d\leq12$. See \citeRef0.
\bibliographystyle{plain}\bibliography{references}\end{document}
"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            source.mkdir()
            (source / "main.tex").write_bytes(original)
            (source / "references.bib").write_text(
                "@article{ref:0,author={Ada Example},title={A compiler fixture},journal={Test},year={2020}}"
            )
            out = root / "material"
            result = prepare_material(source, out, entry="main.tex")
            self.assertEqual(result["status"], "ready")
            loaded = read_material(out)
            self.assertIn(r"\(d\leq12\)", loaded["normalized_tex"])
            self.assertIn(r"\cite{ref:0}", loaded["normalized_tex"])
            self.assertIn(r"\bibitem{ref:0}", loaded["normalized_tex"])
            report = json.loads((out / "normalization.json").read_bytes())
            self.assertEqual(report["native_compile"], "complete")
            self.assertIn(report["pdf_text"], {"equal", "tool_unavailable"})
            self.assertEqual((source / "main.tex").read_bytes(), original)

    def test_revtex_deferred_bibliography_and_notes_keep_their_runtime_behavior(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            source.mkdir()
            (source / "main.tex").write_text(r"""\documentclass{revtex4-2}
\begin{document}\title{Fixture}\author{Ada Example}\maketitle
See \cite{x}.\footnote{A generated bibliography note.}
\bibliographystyle{apsrev4-2}\bibliography{refs}\end{document}""")
            (source / "refs.bib").write_text(
                "@article{x,author={Ada Example},title={A fixture},journal={Test},year={2020}}"
            )
            out = root / "material"
            prepare_material(source, out, entry="main.tex")
            report = json.loads((out / "normalization.json").read_bytes())
            self.assertTrue(report["complete"], report)
            self.assertNotIn("compiled_bibliography", report["transformations"])
            self.assertIn(r"\bibliography{refs}", (out / "normalized.tex").read_text())
