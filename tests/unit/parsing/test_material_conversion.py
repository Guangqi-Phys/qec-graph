import unittest

from qecgraph.preparation.contract import SCHEMA, digest, json_bytes, validate_material
from qecgraph.preparation.convert import convert_source
from qecgraph.source.package import SourceTree


class MaterialConversionTests(unittest.TestCase):
    def convert(self, files, references=None):
        tree = SourceTree("tex", files)
        assembly, document, coverage = convert_source(tree, "main.tex", references or {"bindings": []})
        material = {"entry.tex": assembly.data, "content.json": json_bytes(document),
                    **{"sources/" + p: b for p, b in files.items()}}
        material["manifest.json"] = json_bytes({"schema": SCHEMA, "status": "partial",
                "artifacts": {p: digest(raw) for p, raw in material.items()}})
        validate_material(material)
        return assembly, document, coverage

    def test_multifile_math_appendix_footnote_and_exact_unicode_source_are_preserved(self):
        main = br"\documentclass{article}\begin{document}\section{Setup}\input{body}\appendix\section{Proof}Tail.\end{document}"
        body = "α paragraph.\n\nAn upper bound $d \\leq 12$\\footnote{Under fixed noise.}\n".encode()
        assembly, doc, coverage = self.convert({"main.tex": main, "body.tex": body})
        self.assertTrue(coverage["complete"], coverage)
        self.assertIn(body, assembly.data)
        self.assertEqual([x["title_tex"] for x in doc["outline"]], ["{Setup}", "{Proof}"])
        math = [n for n in doc["nodes"] if n["kind"] == "math"]
        self.assertEqual(math[0]["math_tex"], "$d \\leq 12$")
        self.assertTrue(any(n["name"] == "footnote" for n in doc["nodes"]))

    def test_table_cells_spans_and_figure_assets_are_syntax_not_scientific_records(self):
        raw = br"""\documentclass{article}\begin{document}
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
        raw = br"\documentclass{article}\begin{document}\ifx\x\y Hidden\else Visible\fi \citeRef0\end{document}"
        _, _, coverage = self.convert({"main.tex": raw}, {"bindings": [{"section": "0", "key": "ref:0"}]})
        self.assertFalse(coverage["complete"])
        self.assertIn("conditional_view_not_mapped", coverage["reasons"])
        self.assertTrue(any(d["code"] == "expanded_citation_locations_unknown" for d in coverage["diagnostics"]))
