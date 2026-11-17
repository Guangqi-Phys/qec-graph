"""Known native dialect grammar must not erase ambiguity or guess unknown versions."""

from types import SimpleNamespace
import unittest

from qecgraph.preparation.convert import convert_source
from qecgraph.preparation.entries import select_build_entry
from qecgraph.preparation.harvmac import identify, HARVMAC_SHA256
from qecgraph.preparation.harvmac_refs import _payload, _range_keys
from qecgraph.source.package import SourceTree


class HarvmacPreparationTests(unittest.TestCase):
    def test_entry_sniff_handles_original_invalid_bytes_and_plain_input(self):
        raw = rb"\documentclass{article}\begin{document}" + b"\xa8" + rb"\end{document}"
        tree = SourceTree("tex", {"main.tex": raw})
        self.assertEqual(select_build_entry(tree), "main.tex")
        self.assertEqual(tree.files["main.tex"], raw)
        self.assertEqual(
            select_build_entry(SourceTree("tex", {"old.tex": b"\\input harvmac\n"})),
            "old.tex",
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            select_build_entry(
                SourceTree(
                    "tex",
                    {"a.tex": b"\\input harvmac\n", "b.tex": b"\\input harvmac\n"},
                )
            )

    def test_unknown_dependency_and_shadowed_core_grammar_remain_unsupported(self):
        tree = SourceTree("tex", {"main.tex": b"\\input harvmac\n"})
        build = SimpleNamespace(
            engine="etex",
            entry="main.tex",
            inputs=["main.tex"],
            dependencies=[{"path": "/texlive/harvmac.tex", "sha256": "0" * 64}],
        )
        self.assertIsNone(identify(build, tree))
        build.dependencies[0]["sha256"] = HARVMAC_SHA256
        self.assertIsNotNone(identify(build, tree))
        tree.files["main.tex"] += b"\\def\\eqn#1{Changed}"
        self.assertIsNone(identify(build, tree))

    def test_duplicate_equations_stay_ambiguous_and_formula_bytes_are_preserved(self):
        raw = rb"""\input harvmac
\Title{ID}{Title}
\newsec{Body}
\eqn\ifa{x=1.}
\eqn\ifa{x=2.}
See \ifa.
\end
"""
        tree = SourceTree("tex", {"main.tex": raw})
        refs = {"bindings": [], "external_labels": [], "observed_labels": []}
        assembly, document, coverage = convert_source(
            tree, "main.tex", refs, used_files=["main.tex"], dialect={"name": "harvmac"}
        )
        self.assertEqual(assembly.data, raw)
        self.assertFalse(coverage["complete"])
        self.assertEqual(
            document["cross_references"][0]["targets"][0]["status"], "ambiguous"
        )
        self.assertEqual(len(document["cross_references"][0]["targets"][0]["nodes"]), 2)
        self.assertEqual(
            [
                n["math_tex"]
                for n in document["nodes"]
                if n.get("syntax") == "harvmac_eqn"
            ],
            ["x=1.", "x=2."],
        )

    def test_bibliography_comparison_preserves_word_and_control_token_boundaries(self):
        self.assertEqual(
            _payload(r"A. Author, \pl{1}."), _payload(r"A. Author, \pl {1}.")
        )
        self.assertNotEqual(_payload("John AB"), _payload("JohnA B"))
        self.assertNotEqual(_payload(r"\pl abc"), _payload(r"\plabc"))

    def test_citation_range_requires_a_unique_complete_compiled_number_sequence(self):
        bindings = {
            k: {"status": "resolved", "display_tex": f"[{i}]"}
            for i, k in enumerate(("a", "b", "c"), 1)
        }
        self.assertEqual(_range_keys("a", "c", bindings), ["a", "b", "c"])
        del bindings["b"]
        self.assertIsNone(_range_keys("a", "c", bindings))
