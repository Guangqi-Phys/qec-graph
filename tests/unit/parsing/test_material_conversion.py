import unittest

from qecgraph.preparation.contract import SCHEMA, digest, json_bytes, validate_material
from qecgraph.preparation.convert import convert_source
from qecgraph.source.package import SourceTree


class MaterialConversionTests(unittest.TestCase):
    def test_generated_note_matching_uses_tex_protection_and_citation_spacing(self):
        raw = b"\\documentclass{revtex4-2}\\begin{document}\\footnote{Refs.~\\protect\\cite{a,%\n b}}\\end{document}"
        refs = {
            "bindings": [
                {"section": "0", "key": k, "status": "resolved"} for k in ["a", "b"]
            ]
            + [
                {
                    "section": "0",
                    "key": "Note1",
                    "status": "resolved",
                    "entries": [
                        {
                            "raw_tex": r"\bibitem{Note1}\bibinfo{note}{Refs.~\protect \cite {a,b}}",
                            "origin": {"path": "main.bbl", "layer": "compiled"},
                        }
                    ],
                }
            ]
        }
        _, doc, coverage = self.convert({"main.tex": raw}, refs)
        self.assertTrue(coverage["complete"], coverage)
        self.assertTrue(any(c.get("key") == "Note1" for c in doc["citations"]))

    def test_bibliography_unit_calls_and_generated_notes_keep_source_origins(self):
        raw = rb"\documentclass{revtex4-2}\begin{document}\begin{bibunit}\cite{k}\end{bibunit}\footnote{A literal note.}\end{document}"
        refs = {
            "scopes": [{"id": "bibunit:1", "kind": "bibunit", "ordinal": 1}],
            "bindings": [
                {"section": "bibunit:1", "key": "k", "status": "resolved"},
                {
                    "section": "0",
                    "key": "Note1",
                    "status": "resolved",
                    "entries": [
                        {
                            "raw_tex": r"\bibitem{Note1}\bibinfo{note}{A literal note.}",
                            "origin": {"path": "main.bbl", "layer": "compiled"},
                        }
                    ],
                },
            ],
        }
        _, doc, coverage = self.convert({"main.tex": raw}, refs)
        self.assertTrue(coverage["complete"], coverage)
        self.assertEqual(
            {(c["section"], c["key"]) for c in doc["citations"]},
            {("bibunit:1", "k"), ("0", "Note1")},
        )
        note = next(c for c in doc["citations"] if c["key"] == "Note1")
        a, b = note["source_spans"][0]["bytes"]
        self.assertEqual(raw[a:b], rb"\footnote{A literal note.}")

    def test_external_target_metadata_resolves_without_inventing_source_prose(self):
        raw = rb"\documentclass{article}\begin{document}\ref{supp:proof}\end{document}"
        refs = {
            "bindings": [],
            "external_labels": [
                {
                    "key": "supp:proof",
                    "scope": "external:supp",
                    "availability": "imported_aux_metadata",
                }
            ],
        }
        _, doc, coverage = self.convert({"main.tex": raw}, refs)
        self.assertTrue(coverage["complete"], coverage)
        target = doc["cross_references"][0]["targets"][0]
        self.assertEqual(target["nodes"], [])
        self.assertEqual(
            target["external_targets"][0]["availability"], "imported_aux_metadata"
        )

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

    def test_revtex_numeric_citations_and_merged_keys_have_literal_origins(self):
        raw = rb"\documentclass{revtex4-2}\begin{document}\onlinecite{a}\citenum{b}\cite{[{Theorem 1, page 2}]a,*c}\end{document}"
        refs = {"bindings": [{"section": "0", "key": key} for key in ["a", "b", "c"]]}
        _, doc, coverage = self.convert({"main.tex": raw}, refs)
        self.assertTrue(coverage["complete"], coverage)
        self.assertEqual({c["key"] for c in doc["citations"]}, {"a", "b", "c"})

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
