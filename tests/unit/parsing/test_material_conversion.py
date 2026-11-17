import unittest

from qecgraph.preparation.contract import SCHEMA, digest, json_bytes, validate_material
from qecgraph.preparation.convert import convert_source
from qecgraph.source.package import SourceTree


class MaterialConversionTests(unittest.TestCase):
    def convert(self, files, references=None):
        tree = SourceTree("tex", files)
        assembly, document, coverage = convert_source(
            tree, "main.tex", references or {"bindings": []}
        )
        material = {
            "entry.tex": assembly.data,
            "content.json": json_bytes(document),
            **{"sources/" + p: b for p, b in files.items()},
        }
        material["manifest.json"] = json_bytes(
            {
                "schema": SCHEMA,
                "status": "partial",
                "artifacts": {p: digest(raw) for p, raw in material.items()},
            }
        )
        validate_material(material)
        return assembly, document, coverage

    def test_multifile_math_appendix_footnote_and_exact_unicode_source_are_preserved(
        self,
    ):
        main = rb"\documentclass{article}\begin{document}\section{Setup}\input{body}\appendix\section{Proof}Tail.\end{document}"
        body = "α paragraph.\n\nAn upper bound $d \\leq 12$\\footnote{Under fixed noise.}\n".encode()
        assembly, doc, coverage = self.convert({"main.tex": main, "body.tex": body})
        self.assertTrue(coverage["complete"], coverage)
        self.assertIn(body, assembly.data)
        self.assertEqual(
            [x["title_tex"] for x in doc["outline"]], ["{Setup}", "{Proof}"]
        )
        math = [n for n in doc["nodes"] if n["kind"] == "math"]
        self.assertEqual(math[0]["math_tex"], "$d \\leq 12$")
        self.assertTrue(any(n["name"] == "footnote" for n in doc["nodes"]))

    def test_table_cells_spans_and_figure_assets_are_syntax_not_scientific_records(
        self,
    ):
        raw = rb"""\documentclass{article}\begin{document}
\begin{table}\caption{Parameters, under noise $p$.}\begin{tabular}{cc}
\multicolumn{2}{c}{Header}\\ n & d\\ 10 & $\leq 2$\\
\end{tabular}\end{table}
\begin{figure}\includegraphics{plot}\caption{Logical error rate.}\end{figure}
\end{document}"""
        _, doc, coverage = self.convert({"main.tex": raw, "plot.png": b"image fixture"})
        self.assertTrue(coverage["complete"], coverage)
        table = next(n for n in doc["nodes"] if n["name"] == "tabular")
        self.assertEqual(table["rows"][0][0]["spans"]["columns"], 2)
        self.assertIn("\\leq 2", table["rows"][2][1]["tex"])
        self.assertTrue(doc["assets"][0]["call_nodes"])
        self.assertFalse(doc["capabilities"]["scientific_records"])

    def test_unknown_expanded_citation_location_and_conditional_remain_partial(self):
        raw = rb"\documentclass{article}\begin{document}\ifx\x\y Hidden\else Visible\fi \citeRef0\end{document}"
        _, _, coverage = self.convert(
            {"main.tex": raw}, {"bindings": [{"section": "0", "key": "ref:0"}]}
        )
        self.assertFalse(coverage["complete"])
        self.assertIn("conditional_view_not_mapped", coverage["reasons"])
        self.assertTrue(
            any(
                d["code"] == "expanded_citation_locations_unknown"
                for d in coverage["diagnostics"]
            )
        )

    def test_math_if_prefixes_and_opaque_bibliography_helpers_are_not_branches(self):
        raw = rb"""\documentclass{article}
\newcommand{\ifff}{if and only if}
\begin{document}$a\iff b$ and \ifff.
\providecommand{\helper}[1]{\ifnum#1>0 yes\else no\fi}
\end{document}"""
        _, _, coverage = self.convert({"main.tex": raw})
        self.assertTrue(coverage["complete"], coverage)

    def test_declaration_bodies_stay_opaque_and_literal_cite_wrapper_has_exact_origin(
        self,
    ):
        raw = rb"""\documentclass{article}
\newcommand{\be}{\begin{equation}}
\newcommand{\ee}{\end{equation}}
\newcommand{\citeRef}[1]{\thinspace\cite{ref:#1}}
\begin{document}See \citeRef0.\end{document}"""
        _, doc, coverage = self.convert(
            {"main.tex": raw}, {"bindings": [{"section": "0", "key": "ref:0"}]}
        )
        self.assertTrue(coverage["complete"], coverage)
        call = next(
            c
            for c in doc["citations"]
            if c["origin"] == "literal_wrapper_verified_by_aux"
        )
        self.assertEqual(call["keys"], ["ref:0"])
        a, b = call["source_spans"][0]["bytes"]
        self.assertEqual(raw[a:b], rb"\citeRef0")

    def test_missing_cross_reference_and_unparsed_tail_are_preserved_as_partial(self):
        raw = rb"\documentclass{article}\begin{document}See \cref{missing}.\end{document}} Tail"
        assembly, doc, coverage = self.convert({"main.tex": raw})
        self.assertFalse(coverage["complete"])
        self.assertEqual(assembly.data, raw)
        self.assertTrue(
            any(
                d["code"] == "cross_reference_unresolved"
                for d in coverage["diagnostics"]
            )
        )
