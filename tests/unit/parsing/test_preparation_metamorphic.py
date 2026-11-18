r"""Metamorphic tests (MT) for the compile-first preparation pipeline.

Covers §3.2 of the test engineering plan:
- MT-01: Comment injection invariance across outline, citations, labels, and
         cross-reference resolution.
- MT-02: Inactive branch (\if 0 ... \fi and post-\end{document} tail) mutation
         invariance.
- MT-03: Single-file vs multi-file \input factoring equivalence.
- MT-04: Unused .bib entry and @CONTROL addition invariance.
- MT-05: Positional macro redefinition locality (earlier calls unaffected by
         later \renewcommand or declaration aliases).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from qecgraph.preparation.convert import convert_source
from qecgraph.preparation.references import adapt_references
from qecgraph.source.package import SourceTree


class PreparationMetamorphicTests(unittest.TestCase):
    def _convert(self, files: dict[str, bytes], references=None):
        tree = SourceTree("tex", files)
        refs = references or {"mode": "classic", "bindings": [], "entries": []}
        return convert_source(tree, "main.tex", refs)

    def test_mt01_comment_injection_preserves_outline_citations_and_crossrefs(self):
        refs = {
            "mode": "classic",
            "bindings": [
                {"section": "0", "key": "k1", "status": "resolved"},
                {"section": "0", "key": "k2", "status": "resolved"},
            ],
            "entries": [],
        }
        baseline = (
            b"\\documentclass{article}\n"
            b"\\begin{document}\n"
            b"\\section{Introduction}\\label{sec:intro}\n"
            b"See \\cite{k1, k2} and Section~\\ref{sec:intro}.\n"
            b"\\subsection{Model}\\label{sec:model}\n"
            b"Equation~\\eqref{eq:main} in \\ref{sec:model}:\n"
            b"\\begin{equation}\\label{eq:main}d \\le 12\\end{equation}\n"
            b"\\end{document}\n"
        )
        mutated = (
            b"\\documentclass{article}% header comment \\cite{ghost}\n"
            b"\\begin{document}\n"
            b"\\section{Introduction}% comment \\label{fake}\n"
            b"\\label{sec:intro}\n"
            b"See \\cite{k1,% comment inside cite\n"
            b" k2} and Section~\\ref{sec:intro}% \\ref{missing}\n"
            b".\n"
            b"\\subsection{Model}\\label{sec:model}\n"
            b"Equation~\\eqref{eq:main} in \\ref{sec:model}:\n"
            b"\\begin{equation}\\label{eq:main}d \\le 12\\end{equation}\n"
            b"\\end{document}\n"
        )
        _, doc_base, cov_base = self._convert({"main.tex": baseline}, refs)
        _, doc_mut, cov_mut = self._convert({"main.tex": mutated}, refs)

        self.assertTrue(cov_base["complete"], cov_base)
        self.assertTrue(cov_mut["complete"], cov_mut)
        self.assertEqual(
            [(o["level"], o["title_tex"]) for o in doc_base["outline"]],
            [(o["level"], o["title_tex"]) for o in doc_mut["outline"]],
        )
        self.assertEqual(
            [(c["section"], c["key"]) for c in doc_base["citations"]],
            [(c["section"], c["key"]) for c in doc_mut["citations"]],
        )
        self.assertEqual(
            [lbl["keys"] for lbl in doc_base["labels"]],
            [lbl["keys"] for lbl in doc_mut["labels"]],
        )
        self.assertEqual(
            [
                [(t["key"], t["status"]) for t in r["targets"]]
                for r in doc_base["cross_references"]
            ],
            [
                [(t["key"], t["status"]) for t in r["targets"]]
                for r in doc_mut["cross_references"]
            ],
        )

    def test_mt02_inactive_branch_and_post_document_mutations_do_not_affect_active_view(
        self,
    ):
        baseline = (
            b"\\documentclass{article}\n"
            b"\\begin{document}\n"
            b"\\section{Active}\\label{sec:act}\n"
            b"Active body referencing \\ref{sec:act}.\n"
            b"\\if 0\n"
            b"Inactive placeholder.\n"
            b"\\fi\n"
            b"\\end{document}\n"
        )
        mutated = (
            b"\\documentclass{article}\n"
            b"\\begin{document}\n"
            b"\\section{Active}\\label{sec:act}\n"
            b"Active body referencing \\ref{sec:act}.\n"
            b"\\if 0\n"
            b"Inactive broken syntax \\cite{unbound_key} \\ref{missing_label} \\label{sec:act} \\end{nonexistent}\n"
            b"\\fi\n"
            b"\\end{document}\n"
            b"Post-document garbage \\cite{unbound2} \\ref{missing2} \\end{broken}\n"
        )
        _, doc_base, cov_base = self._convert({"main.tex": baseline})
        _, doc_mut, cov_mut = self._convert({"main.tex": mutated})

        self.assertTrue(cov_base["complete"], cov_base)
        self.assertTrue(cov_mut["complete"], cov_mut)
        self.assertTrue(doc_mut["syntax_complete"])
        self.assertEqual(doc_base["citations"], doc_mut["citations"])
        self.assertEqual(
            [lbl["keys"] for lbl in doc_base["labels"] if lbl["region"] == "body"],
            [lbl["keys"] for lbl in doc_mut["labels"] if lbl["region"] == "body"],
        )
        self.assertEqual(
            [o["title_tex"] for o in doc_base["outline"]],
            [o["title_tex"] for o in doc_mut["outline"]],
        )

    def test_mt03_include_factoring_equivalence_between_single_and_multifile_trees(self):
        refs = {
            "mode": "classic",
            "bindings": [{"section": "0", "key": "kitaev2003", "status": "resolved"}],
            "entries": [],
        }
        sec1 = (
            b"\\section{Stabilizer Formalism}\\label{sec:stab}\n"
            b"We consider a code with distance $d \\ge 3$ \\cite{kitaev2003}.\n"
        )
        sec2 = (
            b"\\subsection{Logical Operators}\\label{sec:log}\n"
            b"As shown in Section~\\ref{sec:stab}, the logical weight is bounded.\n"
        )
        single = {
            "main.tex": (
                b"\\documentclass{article}\n"
                b"\\begin{document}\n" + sec1 + sec2 + b"\\end{document}\n"
            )
        }
        factored = {
            "main.tex": (
                b"\\documentclass{article}\n"
                b"\\begin{document}\n"
                b"\\input{chapters/sec1}"
                b"\\input{chapters/sec2}"
                b"\\end{document}\n"
            ),
            "chapters/sec1.tex": sec1,
            "chapters/sec2.tex": sec2,
        }
        asm_single, doc_single, cov_single = self._convert(single, refs)
        asm_factored, doc_factored, cov_factored = self._convert(factored, refs)

        self.assertTrue(cov_single["complete"])
        self.assertTrue(cov_factored["complete"])
        self.assertEqual(asm_single.data, asm_factored.data)
        self.assertEqual(
            [(o["level"], o["title_tex"]) for o in doc_single["outline"]],
            [(o["level"], o["title_tex"]) for o in doc_factored["outline"]],
        )
        self.assertEqual(
            [c["key"] for c in doc_single["citations"]],
            [c["key"] for c in doc_factored["citations"]],
        )
        self.assertEqual(
            [
                [(t["key"], t["status"]) for t in r["targets"]]
                for r in doc_single["cross_references"]
            ],
            [
                [(t["key"], t["status"]) for t in r["targets"]]
                for r in doc_factored["cross_references"]
            ],
        )

    def test_mt04_unused_bib_entries_and_control_records_preserve_active_bindings(self):
        base_files = {
            "main.tex": b"\\documentclass{article}\\begin{document}\\cite{used}\\end{document}",
            "main.aux": b"\\citation{used}\n\\bibcite{used}{1}\n",
            "main.bbl": b"\\begin{thebibliography}{1}\n\\bibitem{used}Used entry.\n\\end{thebibliography}\n",
            "refs.bib": b"@article{used, title={Used title}, year={2024}}\n",
        }
        expanded_files = {
            **base_files,
            "main.aux": b"\\citation{REVTEX41Control}\n\\citation{used}\n\\bibcite{used}{1}\n",
            "refs.bib": (
                b"@CONTROL{REVTEX41Control,pages=\"1\"}\n"
                b"@article{used, title={Used title}, year={2024}}\n"
                b"@article{unused1, title={Unused A}, year={2020}}\n"
                b"@book{unused2, title={Unused B}, year={2021}}\n"
            ),
        }

        def run_adapt(files):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                tree = SourceTree("tex", files)
                tree.materialize(root / "project")
                build = SimpleNamespace(
                    root=root,
                    inputs=["main.tex", "main.aux", "main.bbl"],
                    outputs=[],
                    entry="main.tex",
                )
                return adapt_references(build, tree)

        res_base = run_adapt(base_files)
        res_exp = run_adapt(expanded_files)

        self.assertTrue(res_base["complete"])
        self.assertTrue(res_exp["complete"])
        self.assertEqual(res_base["bindings"], res_exp["bindings"])
        self.assertEqual(res_exp["excluded_control_keys"], ["REVTEX41Control"])
        self.assertEqual(
            [e["key"] for e in res_exp["original_bib_entries"]],
            ["used", "unused1", "unused2"],
        )

    def test_mt05_positional_macro_redefinition_locality_invariant(self):
        prefix = (
            b"\\documentclass{article}\n"
            b"\\newcommand{\\op}[1]{#1}\n"
            b"\\begin{document}\n"
            b"First call \\op{A}{B}.\n"
        )
        suffix_v1 = (
            b"\\renewcommand{\\op}[2]{#1+#2}\n"
            b"Second call \\op{C}{D}.\n"
            b"\\end{document}\n"
        )
        suffix_v2 = (
            b"\\newcommand{\\alias}{\\renewcommand}\n"
            b"\\alias{\\op}[3]{#1+#2+#3}\n"
            b"Second call \\op{C}{D}{E}.\n"
            b"\\end{document}\n"
        )
        _, doc_v1, cov_v1 = self._convert({"main.tex": prefix + suffix_v1})
        _, doc_v2, cov_v2 = self._convert({"main.tex": prefix + suffix_v2})

        self.assertTrue(cov_v1["complete"])
        self.assertTrue(cov_v2["complete"])
        calls_v1 = [n for n in doc_v1["nodes"] if n["name"] == "op"]
        calls_v2 = [n for n in doc_v2["nodes"] if n["name"] == "op"]
        # First call before the redefinition point must have identical arguments in both runs
        self.assertEqual(calls_v1[0]["arguments"], ["{A}"])
        self.assertEqual(calls_v2[0]["arguments"], ["{A}"])
        # Second call after the redefinition reflects the respective new arity
        self.assertEqual(calls_v1[1]["arguments"], ["{C}", "{D}"])
        self.assertEqual(calls_v2[1]["arguments"], ["{C}", "{D}", "{E}"])


if __name__ == "__main__":
    unittest.main()
