import copy
import unittest

from qecgraph.preparation.convert import convert_source
from qecgraph.preparation.normalized import normalize_latex, validate_normalized
from qecgraph.source.package import SourceTree


class NormalizedLatexTests(unittest.TestCase):
    def test_incomplete_syntax_keeps_the_lossless_view_without_format_edits(self):
        source = r"\documentclass{article}\begin{document}$x$\end{document}}"
        _, normalized, _, report, _, _ = self.prepare(source)
        self.assertEqual(normalized, source)
        self.assertEqual(report["transformations"], {})
        self.assertEqual(report["syntax_parse"], "partial")

    def test_multibib_keeps_its_bibliography_calls(self):
        source = r"\documentclass{article}\usepackage{multibib}\begin{document}\bibliography{refs}\end{document}"
        refs = {"mode": "classic", "bindings": []}
        tree = SourceTree("tex", {"main.tex": source.encode()})
        assembly, document, _ = convert_source(tree, "main.tex", refs)
        bbl = (
            "build/files/main.bbl",
            rb"\begin{thebibliography}{1}\bibitem{x}Title.\end{thebibliography}",
        )
        raw, _, report = normalize_latex(assembly.text, document, refs, bbl)
        self.assertIn(rb"\bibliography{refs}", raw)
        self.assertNotIn("compiled_bibliography", report["transformations"])

    def prepare(self, source, references=None):
        references = references or {"bindings": []}
        tree = SourceTree("tex", {"main.tex": source.encode()})
        assembly, document, _ = convert_source(tree, "main.tex", references)
        normalized, mapping, report = normalize_latex(
            assembly.text, document, references
        )
        return assembly.text, normalized.decode(), mapping, report, document, references

    def test_math_content_unicode_and_unknown_macros_survive_surface_normalization(
        self,
    ):
        source = r"\documentclass{article}\begin{document}α $d\leq12$ $$x_1+x_2$$ \unknown{payload}\end{document}"
        text, normalized, mapping, report, document, references = self.prepare(source)
        self.assertIn(r"α \(d\leq12\) \[x_1+x_2\] \unknown{payload}", normalized)
        self.assertEqual(report["transformations"], {"math_delimiter": 4})
        self.assertTrue(
            validate_normalized(text, normalized, mapping, document, references)
        )
        changed = normalized.replace(r"\leq12", r"\geq12")
        forged = copy.deepcopy(mapping)
        from qecgraph.preparation.contract import digest

        forged["output_sha256"] = digest(changed.encode())
        with self.assertRaisesRegex(ValueError, "content"):
            validate_normalized(text, changed, forged, document, references)

    def test_only_runtime_bound_wrapper_expands_and_keeps_its_author_formatting(self):
        source = r"""\documentclass{article}
\newcommand{\citeRef}[1]{\thinspace\cite{ref:#1}}
\begin{document}See \citeRef0.\end{document}"""
        refs = {"bindings": [{"section": "0", "key": "ref:0", "status": "resolved"}]}
        _, normalized, mapping, report, _, _ = self.prepare(source, refs)
        self.assertIn(r"See \thinspace\cite{ref:0}.", normalized)
        self.assertIn("citation_wrapper", report["transformations"])
        edit = next(
            s for s in mapping["segments"] if s["operation"] == "citation_wrapper"
        )
        self.assertTrue(edit["definition_node"])
        _, unbound, _, report, _, _ = self.prepare(source)
        self.assertIn(r"See \citeRef0.", unbound)
        self.assertNotIn("citation_wrapper", report["transformations"])

    def test_mapping_rejects_missing_tail_and_fake_operations(self):
        text, normalized, mapping, _, document, refs = self.prepare(
            r"\documentclass{article}\begin{document}$x$ Tail.\end{document}"
        )
        mapping["segments"].pop()
        with self.assertRaisesRegex(ValueError, "tail"):
            validate_normalized(text, normalized, mapping, document, refs)

    def test_definition_math_and_verbatim_payload_are_not_rewritten(self):
        source = r"""\documentclass{article}\newcommand{\example}{$x$}
\begin{document}\begin{verbatim}$x$\end{verbatim}\end{document}"""
        _, normalized, _, report, _, _ = self.prepare(source)
        self.assertEqual(normalized, source)
        self.assertEqual(report["transformations"], {})

    def test_math_in_unknown_macro_arguments_keeps_its_original_delimiters(self):
        source = r"\documentclass{article}\begin{document}\Procedure{Step}{$x$} then $y$.\end{document}"
        _, normalized, _, _, _, _ = self.prepare(source)
        self.assertIn(r"\Procedure{Step}{$x$} then \(y\)", normalized)

    def test_compiled_bibliography_is_inlined_with_a_derived_origin(self):
        source = r"\documentclass{article}\begin{document}Body.\bibliography{refs}\end{document}"
        refs = {"mode": "classic", "bindings": []}
        tree = SourceTree("tex", {"main.tex": source.encode()})
        assembly, document, _ = convert_source(tree, "main.tex", refs)
        bbl = (
            "build/files/main.bbl",
            rb"\begin{thebibliography}{1}\bibitem{x}Author. Title.\end{thebibliography}",
        )
        raw, mapping, _ = normalize_latex(assembly.text, document, refs, bbl)
        normalized = raw.decode()
        self.assertNotIn(r"\bibliography{refs}", normalized)
        self.assertIn(r"\bibitem{x}Author. Title.", normalized)
        self.assertEqual(mapping["bibliography"]["path"], bbl[0])
        revtex = source.replace("{article}", "{revtex4-2}")
        revtree = SourceTree("tex", {"main.tex": revtex.encode()})
        revasm, revdoc, _ = convert_source(revtree, "main.tex", refs)
        retained, _, _ = normalize_latex(revasm.text, revdoc, refs, bbl)
        self.assertIn(rb"\bibliography{refs}", retained)
        self.assertTrue(
            validate_normalized(source, normalized, mapping, document, refs, bbl)
        )
        with self.assertRaisesRegex(ValueError, "provenance"):
            validate_normalized(
                source,
                normalized,
                mapping,
                document,
                refs,
                (bbl[0], bbl[1].replace(b"Title", b"Other")),
            )
