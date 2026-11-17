"""Explicit local compiler checks; ordinary tests never execute untrusted TeX."""

import os
import json
from pathlib import Path
import tempfile
import unittest

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
