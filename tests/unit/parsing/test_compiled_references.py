from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from qecgraph.preparation.references import adapt_references, group
from qecgraph.source.package import SourceTree


class CompiledReferenceTests(unittest.TestCase):
    def test_external_aux_is_not_merged_into_primary_citations_or_labels(self):
        result = self.adapt(
            {
                "main.tex": rb"\externaldocument{supp_aux}",
                "main.aux": rb"\citation{k}\bibcite{k}{1}",
                "supp_aux.aux": rb"\citation{foreign}\bibcite{k}{99}\newlabel{sec:supp}{{A}{2}}",
                "main.bbl": rb"\bibitem{k}Primary reference.",
            },
            ["main.tex", "main.aux", "main.bbl", "supp_aux.aux"],
        )
        self.assertTrue(result["complete"], result)
        self.assertEqual(
            [(b["section"], b["key"]) for b in result["bindings"]], [("0", "k")]
        )
        self.assertEqual(
            result["external_labels"][0]["availability"], "imported_aux_metadata"
        )

    def test_bibunits_and_multibib_keep_repeated_keys_in_distinct_namespaces(self):
        for source, names, expected in [
            (rb"\usepackage{bibunits}", ["bu1", "bu2"], {"bibunit:1", "bibunit:2"}),
            (
                rb"\usepackage{multibib}\newcites{meth}{Methods}",
                ["main", "meth"],
                {"0", "multibib:meth"},
            ),
        ]:
            with self.subTest(names=names):
                files = {"main.tex": source, "main.aux": b""}
                for i, name in enumerate(names):
                    files[name + ".aux"] = (
                        r"\citation{k}\bibcite{k}{%d}" % (i + 1)
                    ).encode()
                    files[name + ".bbl"] = rb"\bibitem{k}Reference."
                result = self.adapt(files, list(files))
                self.assertTrue(result["complete"], result)
                self.assertEqual({b["section"] for b in result["bindings"]}, expected)

    def test_nocite_wildcard_expands_observed_entries_and_does_not_pass_vacuously(self):
        files = {
            "main.aux": rb"\citation{*}\bibcite{a}{1}\bibcite{b}{2}",
            "main.bbl": rb"\bibitem{a}First.\bibitem{b}Second.",
        }
        result = self.adapt(files, list(files))
        self.assertTrue(result["complete"], result)
        self.assertEqual([b["key"] for b in result["bindings"]], ["a", "b"])
        self.assertEqual(result["wildcard_sections"], ["0"])
        empty = self.adapt({"main.aux": rb"\citation{*}\bibdata{absent}"}, ["main.aux"])
        self.assertFalse(empty["complete"])
        self.assertEqual(
            empty["diagnostics"][0]["code"], "wildcard_bibliography_unobserved"
        )

    def test_biblatex_wildcard_respects_refsection(self):
        files = {
            "main.bcf": b'<bcf:controlfile xmlns:bcf="test"><bcf:section number="1"><bcf:citekey>*</bcf:citekey></bcf:section></bcf:controlfile>',
            "main.bbl": rb"\refsection{1}\entry{a}{article}{}A\endentry\endrefsection\refsection{2}\entry{b}{article}{}B\endentry\endrefsection",
        }
        result = self.adapt(files, ["main.bbl"])
        self.assertTrue(result["complete"], result)
        self.assertEqual(
            [(b["section"], b["key"]) for b in result["bindings"]], [("1", "a")]
        )

    def test_inline_bibliography_can_bind_a_unique_nonprimary_scope(self):
        files = {
            "main.tex": rb"\usepackage{bibunits}\begin{bibunit}\bibitem{a}First.\end{bibunit}",
            "main.aux": b"",
            "bu1.aux": rb"\citation{a}\bibcite{a}{1}",
        }
        result = self.adapt(files, list(files))
        self.assertTrue(result["complete"], result)
        self.assertEqual(result["bindings"][0]["section"], "bibunit:1")
        self.assertEqual(
            result["bindings"][0]["entries"][0]["origin"]["path"], "main.tex"
        )
        files["bu2.aux"] = rb"\citation{a}\bibcite{a}{2}"
        ambiguous = self.adapt(files, list(files))
        self.assertFalse(ambiguous["complete"])
        self.assertEqual(
            ambiguous["diagnostics"][0]["code"], "inline_bibliography_scope_ambiguous"
        )

    def test_rejected_biblatex_bbl_keeps_structure_and_blocks_complete_binding(self):
        files = {
            "main.bcf": b'<bcf:controlfile xmlns:bcf="test"><bcf:section number="0"><bcf:citekey>k</bcf:citekey></bcf:section></bcf:controlfile>',
            "main.bbl": rb"\refsection{0}\entry{k}{article}{}Literal entry.\endentry\endrefsection",
        }
        prefix = b"Package biblatex Warning: File '"
        bbl = b"a" * (79 - len(prefix) - len(b".bbl' is wr")) + b".bbl"
        log = (
            prefix + bbl + b"' is wr\nong format version - expected 3.3.\n\n"
            b"LaTeX Warning: Citation 'k' on page 1 undefined on input line 8.\n"
            b"LaTeX Warning: Empty bibliography on input line 9.\n"
        )
        result = self.adapt(files, ["main.bbl"], log=log)
        self.assertTrue(result["structure_complete"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["runtime"]["status"], "incompatible_bbl")
        self.assertEqual(result["runtime"]["incompatible_bbl_files"], [bbl.decode()])
        self.assertEqual(result["runtime"]["undefined_keys"], ["k"])
        self.assertIn("Literal entry.", result["bindings"][0]["entries"][0]["raw_tex"])
        # A filtered bibliography can legitimately be empty.
        filtered = self.adapt(
            files,
            ["main.bbl"],
            log=b"LaTeX Warning: Empty bibliography on input line 9.\n",
        )
        self.assertTrue(filtered["complete"])

    def adapt(self, files, inputs, log=None):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tree = SourceTree("tex", files)
            tree.materialize(root / "project")
            build = SimpleNamespace(
                root=root,
                inputs=inputs,
                entry="main.tex",
                artifacts={"files/main.log": log} if log is not None else {},
            )
            return adapt_references(build, tree)

    def test_balanced_author_label_and_unconsumed_aux_do_not_corrupt_identity(self):
        result = self.adapt(
            {
                "main.aux": rb"\citation{k}\bibcite{k}{{1}{2020}{{Author}}{{}}}",
                "main.bbl": rb"\begin{thebibliography}{1}\bibitem[{{Author}(2020)}]{k}Title.\end{thebibliography}",
                "unused.aux": rb"\citation{missing}",
            },
            ["main.aux", "main.bbl"],
        )
        self.assertTrue(result["complete"])
        self.assertEqual([r["key"] for r in result["bindings"]], ["k"])
        self.assertIn("Title.", result["bindings"][0]["entries"][0]["raw_tex"])

    def test_biblatex_sections_and_sort_lists_keep_scope_and_reject_local_duplicates(
        self,
    ):
        bcf = b'<bcf:controlfile xmlns:bcf="test"><bcf:section number="1"><bcf:citekey>k</bcf:citekey></bcf:section><bcf:section number="2"><bcf:citekey>k</bcf:citekey></bcf:section></bcf:controlfile>'
        bbl = rb"\refsection{1}\datalist[entry]{a}\entry{k}{article}{}A\endentry\enddatalist\datalist[entry]{b}\entry{k}{article}{}A\endentry\enddatalist\endrefsection"
        result = self.adapt({"main.bcf": bcf, "main.bbl": bbl}, ["main.bbl"])
        self.assertFalse(result["complete"])
        self.assertEqual(
            [r["status"] for r in result["bindings"]], ["resolved", "unresolved"]
        )
        repeated = bbl.replace(
            rb"A\endentry", rb"A\endentry\entry{k}{article}{}B\endentry", 1
        )
        result = self.adapt({"main.bcf": bcf, "main.bbl": repeated}, ["main.bbl"])
        self.assertEqual(result["bindings"][0]["status"], "ambiguous")

    def test_external_bib_is_retained_without_promoting_unused_entries(self):
        result = self.adapt(
            {
                "main.aux": rb"\citation{k}\bibcite{k}{1}",
                "main.tex": rb"\bibitem{k}Actual reference.",
                "refs.bib": b"@article{unused,title={Only in database}}",
            },
            ["main.aux", "main.tex"],
        )
        self.assertTrue(result["complete"])
        self.assertEqual(result["original_bib_entries"][0]["key"], "unused")
        self.assertEqual(len(result["bindings"]), 1)

    def test_tex_argument_comments_and_nested_braces_preserve_offsets(self):
        value = " {a{b}% ignore }\n c}tail"
        arg = group(value, 0)
        self.assertEqual(value[arg[2] : arg[3]], "{" + arg[0] + "}")

    def test_acm_bibitem_comment_before_key_keeps_the_entry_and_original_span(self):
        raw = b"\\begin{thebibliography}{1}\n\\bibitem[Author(2025)]% comment\n {key}\nTitle.\\end{thebibliography}"
        result = self.adapt(
            {"main.aux": rb"\citation{key}\bibcite{key}{1}", "main.bbl": raw},
            ["main.aux", "main.bbl"],
        )
        self.assertTrue(result["complete"], result)
        entry = result["entries"][0]
        a, b = entry["origin"]["bytes"]
        self.assertEqual(raw[a:b].decode(), entry["raw_tex"])
