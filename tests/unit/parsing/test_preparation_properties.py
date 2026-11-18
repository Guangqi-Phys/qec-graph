"""Property-based tests (PBT) for the compile-first preparation pipeline.

Covers §3.1 of the test engineering plan:
- PBT-01: Full source tiling, strict parent-child interval containment, and
          byte-exact reconstruction across randomized nested LaTeX trees.
- PBT-02: Multi-file include splicing with separator insertion
          (EntryCoordinates) preserving exact per-file byte/char/line spans.
- PBT-03: Normalized LaTeX bijective segment tiling and exact inverse
          reconstruction back to entry.tex.
- PBT-04: SourceIndex UTF-8 multi-byte codepoint/byte/line invariant across
          1..4 byte Unicode sequences and LF/CRLF line endings.
"""

from __future__ import annotations

import random
import unittest

from qecgraph.preparation.contract import (
    SourceIndex,
    validate_material,
)
from qecgraph.preparation.convert import convert_source
from qecgraph.preparation.normalized import normalize_latex, validate_normalized
from qecgraph.source.package import SourceTree
from tests.unit.parsing.material_fixture import partial_material


def _build_bundle(files: dict[str, bytes], entry: str = "main.tex", references=None):
    tree = SourceTree("tex", files)
    refs = references or {"mode": "classic", "bindings": [], "entries": []}
    assembly, document, coverage = convert_source(tree, entry, refs)
    bundle = partial_material(
        tree, entry, assembly.data, document, coverage=coverage, references=refs
    )
    return tree, assembly, document, coverage, bundle


class PreparationPropertyTests(unittest.TestCase):
    def test_pbt01_randomized_syntax_trees_tile_entry_and_reconstruct_bytes(self):
        rng = random.Random(20261117)
        atoms = [
            "Plain ASCII text. ",
            "Unicode αβγδε and operator $d \\leq 12$. ",
            "$$E_0 = \\hbar \\omega$$\n",
            "\\textbf{bold $\\ket{\\psi}$ text} ",
            "\\begin{theorem}[Main]\\label{thm:1}For all $n \\ge 1$, $k/n > 0$.\\end{theorem}\n",
            "\\begin{tabular}{cc}a & $b$\\\\ 1 & 2\\end{tabular}\n",
            "\\begin{tikzpicture}\\draw (0,0) -- (1,1);\\end{tikzpicture}\n",
            "% comment with UTF-8 Ω and $math$\n",
            "\\unknownmacro{arg1}[opt]{arg2} ",
        ]
        headings = ["\\section{One}\n", "\\subsection{Two}\n", "\\paragraph{Three}\n"]

        for seed_iter in range(25):
            with self.subTest(iteration=seed_iter):
                pieces = ["\\documentclass{article}\n\\begin{document}\n"]
                for _ in range(rng.randint(4, 12)):
                    if rng.random() < 0.3:
                        pieces.append(rng.choice(headings))
                    pieces.append(rng.choice(atoms))
                if seed_iter % 5 == 0:
                    # Inject an unmatched closing brace to exercise opaque fallback tiling.
                    pieces.append("Malformed tail } after text.\n")
                pieces.append("\\end{document}\n")
                if seed_iter % 3 == 0:
                    pieces.append("Trailing post-document notes \\end{now}\n")

                raw = "".join(pieces).encode("utf-8")
                _, assembly, document, _, bundle = _build_bundle({"main.tex": raw})
                check = validate_material(bundle)
                self.assertTrue(check["source_fidelity"])

                by_id = {n["id"]: n for n in document["nodes"]}
                entry_text = assembly.text
                # Root tiling invariant: roots partition [0, len(entry_text))
                root_Pieces = []
                cursor = 0
                for root_id in document["roots"]:
                    root_node = by_id[root_id]
                    self.assertIsNone(root_node["parent"])
                    self.assertEqual(root_node["range"][0], cursor)
                    cursor = root_node["range"][1]
                    reconstructed = b"".join(
                        raw[s["bytes"][0] : s["bytes"][1]]
                        for s in root_node["source_spans"]
                    ).decode("utf-8")
                    self.assertEqual(
                        reconstructed,
                        entry_text[root_node["range"][0] : root_node["range"][1]],
                    )
                    root_Pieces.append(reconstructed)
                self.assertEqual(cursor, len(entry_text))
                self.assertEqual("".join(root_Pieces).encode("utf-8"), raw)

    def test_pbt02_multifile_include_splicing_preserves_exact_source_coordinates(self):
        rng = random.Random(20261118)
        endings = [
            "% trailing comment without newline",
            "\\relax",
            "word",
            "αβγ\n",
            "$x+y$",
        ]
        for iteration in range(20):
            with self.subTest(iteration=iteration):
                frag_a = (
                    f"\\section{{A-{iteration}}}\n"
                    f"First fragment {rng.choice(['α', 'β', 'Ω'])} "
                    f"\\input{{sub/frag_b}} "
                    f"{rng.choice(endings)}"
                ).encode("utf-8")
                frag_b = (
                    f"Second fragment $k_{iteration} \\le d$ and {rng.choice(endings)}"
                ).encode("utf-8")
                main = (
                    "\\documentclass{article}\n"
                    "\\newcommand{\\pathmacro}{frag_a}\n"
                    "\\begin{document}\n"
                    "Before include. \\input{\\pathmacro}After include.\n"
                    "\\end{document}\n"
                ).encode("utf-8")
                files = {
                    "main.tex": main,
                    "frag_a.tex": frag_a,
                    "sub/frag_b.tex": frag_b,
                }
                _, assembly, document, _, bundle = _build_bundle(files)
                self.assertEqual(assembly.validate(files), [])
                self.assertTrue(validate_material(bundle)["source_fidelity"])

                for node in document["nodes"]:
                    start, end = node["range"]
                    from_sources = "".join(
                        files[span["path"]][span["bytes"][0] : span["bytes"][1]].decode(
                            "utf-8"
                        )
                        for span in node["source_spans"]
                    )
                    self.assertEqual(from_sources, assembly.text[start:end])

    def test_pbt03_normalized_latex_bijective_tiling_and_inverse_reconstruction(self):
        rng = random.Random(20261119)
        snippets = [
            "Inline $a_1 + b_2 = c_3$ math. ",
            "Display $$\\sum_{i=1}^n x_i$$ formula. ",
            "Macro argument \\textbf{keep $x$ inside} and {group $y$ inside}. ",
            "\\begin{verbatim}literal $z$ and \\citeRef0\\end{verbatim}\n",
            "Citation wrapper \\citeRef0 and \\citeRef{1}. ",
            "Unicode text λ, μ, ν. ",
        ]
        refs = {
            "mode": "classic",
            "bindings": [
                {"section": "0", "key": "ref:0", "status": "resolved"},
                {"section": "0", "key": "ref:1", "status": "resolved"},
            ],
            "entries": [],
        }
        bbl = (
            "build/files/main.bbl",
            b"\\begin{thebibliography}{9}\n\\bibitem{ref:0}A.\n\\bibitem{ref:1}B.\n\\end{thebibliography}",
        )
        for iteration in range(20):
            with self.subTest(iteration=iteration):
                body = "".join(rng.choices(snippets, k=6))
                source = (
                    "\\documentclass{article}\n"
                    "\\newcommand{\\citeRef}[1]{\\cite{ref:#1}}\n"
                    "\\begin{document}\n"
                    f"{body}\n"
                    "\\bibliography{refs}\n"
                    "\\end{document}\n"
                ).encode("utf-8")
                tree = SourceTree("tex", {"main.tex": source})
                assembly, document, _ = convert_source(tree, "main.tex", refs)
                norm_bytes, mapping, report = normalize_latex(
                    assembly.text, document, refs, bbl
                )
                norm_text = norm_bytes.decode("utf-8")
                self.assertEqual(report["syntax_parse"], "complete")
                self.assertTrue(
                    validate_normalized(
                        assembly.text, norm_text, mapping, document, refs, bbl
                    )
                )
                # Inverse reconstruction property: replacing every segment's output
                # with its input_range slice from entry.tex restores entry.tex.
                restored = "".join(
                    assembly.text[seg["input_range"][0] : seg["input_range"][1]]
                    for seg in mapping["segments"]
                )
                self.assertEqual(restored, assembly.text)
                rebuilt_norm = "".join(
                    norm_text[seg["output_range"][0] : seg["output_range"][1]]
                    for seg in mapping["segments"]
                )
                self.assertEqual(rebuilt_norm, norm_text)

    def test_pbt04_source_index_utf8_multibyte_and_line_invariants(self):
        rng = random.Random(20261120)
        alphabet = [
            "a",
            "Z",
            "\n",
            "\r\n",
            "é",
            "ß",
            "α",
            "Ω",
            "—",
            "∀",
            "⊗",
            "𝕏",
            "🧮",
        ]
        for iteration in range(30):
            with self.subTest(iteration=iteration):
                text = "".join(rng.choices(alphabet, k=120))
                if not text:
                    continue
                raw = text.encode("utf-8")
                index = SourceIndex(raw, "utf-8")
                for _ in range(20):
                    a = rng.randint(0, len(text) - 1)
                    b = rng.randint(a + 1, len(text))
                    span = index.span("test.tex", a, b)
                    low, high = span["bytes"]
                    self.assertEqual(raw[low:high].decode("utf-8"), text[a:b])
                    self.assertGreaterEqual(span["lines"][0], 1)
                    self.assertGreaterEqual(span["lines"][1], span["lines"][0])
                    expected_start_line = text.count("\n", 0, a) + 1
                    expected_end_line = text.count("\n", 0, b - 1) + 1
                    self.assertEqual(
                        span["lines"], [expected_start_line, expected_end_line]
                    )


if __name__ == "__main__":
    unittest.main()
