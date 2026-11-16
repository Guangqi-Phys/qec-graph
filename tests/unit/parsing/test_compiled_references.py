from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from qecgraph.preparation.references import adapt_references, group
from qecgraph.source.package import SourceTree


class CompiledReferenceTests(unittest.TestCase):
    def adapt(self, files, inputs):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tree = SourceTree("tex", files)
            tree.materialize(root / "project")
            build = SimpleNamespace(root=root, inputs=inputs, entry="main.tex")
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
