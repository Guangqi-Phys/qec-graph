import unittest

from qecgraph.preparation.entries import select_build_entry
from qecgraph.source.package import SourceTree


def _tex(title: str = "", authors: tuple[str, ...] = (), body: str = "Body.") -> bytes:
    front = f"\\title{{{title}}}\n" if title else ""
    front += "".join(f"\\author{{{author}}}\n" for author in authors)
    return (
        "\\documentclass{article}\n"
        + front
        + "\\begin{document}\n"
        + body
        + "\n\\end{document}\n"
    ).encode()


class PreparationEntryTests(unittest.TestCase):
    def test_content_detection_accepts_an_extensionless_entry(self):
        tree = SourceTree(
            "directory",
            {
                "tqecp": (
                    b"\\documentstyle[11pt]{article}\n\\begin{document}\n"
                    b"\\section{Introduction}\nText.\n\\end{document}\n"
                ),
            },
        )
        self.assertEqual(select_build_entry(tree), "tqecp")

    def test_supplement_title_selects_the_main_document(self):
        tree = SourceTree(
            "directory",
            {
                "main.tex": _tex("Quantum memory", ("Ada Lovelace",)),
                "supplement.tex": _tex(
                    "Supplementary information for Quantum memory", ("Ada Lovelace",)
                ),
            },
        )
        self.assertEqual(select_build_entry(tree), "main.tex")

    def test_macro_title_and_last_supplement_title_are_compared_literally(self):
        main = (
            b"\\documentclass{article}\n\\begin{document}\n"
            b"\\title{\\puttitle}\n\\author{Ada Lovelace}\n"
            b"Text.\n\\end{document}\n"
        )
        supplement = (
            b"\\documentclass{article}\n\\begin{document}\n"
            b"\\title{\\puttitle}\n"
            b"\\title{Supplemental Information for: \\puttitle}\n"
            b"\\author{Ada Lovelace}\nText.\n\\end{document}\n"
        )
        tree = SourceTree("directory", {"main.tex": main, "supplement.tex": supplement})
        self.assertEqual(select_build_entry(tree), "main.tex")

    def test_titled_candidate_wins_over_untitled_fragment(self):
        tree = SourceTree(
            "directory",
            {
                "main.tex": _tex("Quantum memory", ("Ada Lovelace",)),
                "appendix.tex": _tex(body="Additional derivation."),
            },
        )
        self.assertEqual(select_build_entry(tree), "main.tex")

    def test_commented_title_does_not_make_a_fragment_look_like_the_paper(self):
        fragment = (
            b"\\documentclass{article}\n% \\title{Commented template}\n"
            b"\\author{Ada Lovelace}\n\\begin{document}\nNotes.\n"
            b"\\end{document}\n"
        )
        tree = SourceTree(
            "directory",
            {
                "main.tex": _tex("Quantum memory", ("Ada Lovelace",)),
                "notes.tex": fragment,
            },
        )
        self.assertEqual(select_build_entry(tree), "main.tex")

    def test_identical_candidate_bytes_are_one_document(self):
        text = _tex("Quantum memory", ("Ada Lovelace",))
        tree = SourceTree(
            "directory",
            {
                "main.tex": text,
                "main-copy.tex": text,
            },
        )
        self.assertEqual(select_build_entry(tree), "main.tex")

    def test_identical_wrappers_with_different_relative_inputs_stay_ambiguous(self):
        text = _tex("Quantum memory", ("Ada Lovelace",), r"\input{body}")
        tree = SourceTree(
            "directory",
            {
                "main.tex": text,
                "copies/main.tex": text,
                "body.tex": b"First paper.",
                "copies/body.tex": b"Different paper.",
            },
        )
        with self.assertRaisesRegex(ValueError, "multiple TeX entry candidates"):
            select_build_entry(tree)

    def test_similar_title_pair_does_not_hide_an_independent_document(self):
        tree = SourceTree(
            "directory",
            {
                "main.tex": _tex(
                    "The Variational Quantum Eigensolver: a review of methods and best practices",
                    ("Ada Lovelace", "Alan Turing"),
                ),
                "wrapper.tex": _tex(
                    "The Variational Quantum Eigensolver: a review of recent research and best practices",
                    ("A B",),
                ),
                "independent.tex": _tex("Causal inference for all", ("Grace Hopper",)),
            },
        )
        with self.assertRaisesRegex(ValueError, "multiple TeX entry candidates"):
            select_build_entry(tree)

    def test_title_similarity_does_not_merge_a_transitive_chain(self):
        # Adjacent pairs match at 5/6, but the endpoints match at only 2/3.
        tree = SourceTree(
            "directory",
            {
                "first.tex": _tex(
                    "a" * 10 + "b" * 10 + "c" * 10, ("Ada", "Alan", "Grace")
                ),
                "bridge.tex": _tex(
                    "a" * 10 + "b" * 10 + "d" * 5 + "c" * 5, ("Ada", "Alan")
                ),
                "last.tex": _tex(
                    "a" * 10 + "e" * 5 + "b" * 5 + "d" * 5 + "c" * 5, ("Ada",)
                ),
            },
        )
        with self.assertRaisesRegex(ValueError, "multiple TeX entry candidates"):
            select_build_entry(tree)

    def test_near_identical_compile_variant_with_more_authors_is_main(self):
        tree = SourceTree(
            "directory",
            {
                "main.tex": _tex(
                    "The Variational Quantum Eigensolver: a review of methods and best practices",
                    ("Ada Lovelace", "Alan Turing", "Grace Hopper"),
                ),
                "wrapper.tex": _tex(
                    "The Variational Quantum Eigensolver: a review of recent research and best practices",
                    ("A B",),
                ),
            },
        )
        self.assertEqual(select_build_entry(tree), "main.tex")

    def test_same_title_with_different_author_counts_stays_ambiguous(self):
        tree = SourceTree(
            "directory",
            {
                "paper.tex": _tex("Quantum memory", ("Ada Lovelace",)),
                "copy.tex": _tex("Quantum memory", ("Ada Lovelace", "Alan Turing")),
            },
        )
        with self.assertRaisesRegex(ValueError, "multiple TeX entry candidates"):
            select_build_entry(tree)

    def test_unrelated_documents_stay_ambiguous(self):
        tree = SourceTree(
            "directory",
            {
                "paper.tex": _tex("Quantum error correction", ("Ada Lovelace",)),
                "other.tex": _tex("Causal inference for all", ("Alan Turing",)),
            },
        )
        with self.assertRaisesRegex(ValueError, "multiple TeX entry candidates"):
            select_build_entry(tree)

    def test_supplement_word_without_containment_stays_ambiguous(self):
        tree = SourceTree(
            "directory",
            {
                "main.tex": _tex("Dietary Supplement Use in Adults", ("Ada Lovelace",)),
                "supplement.tex": _tex("Supplemental methods", ("Alan Turing",)),
            },
        )
        with self.assertRaisesRegex(ValueError, "multiple TeX entry candidates"):
            select_build_entry(tree)
