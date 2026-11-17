import unittest

from qecgraph.preparation.build_view import _instrument, _observations
from qecgraph.preparation.guard_syntax import candidates, scan_views
from qecgraph.preparation.convert import convert_source
from qecgraph.preparation.normalized import normalize_latex
from qecgraph.source.package import SourceTree


class BuildViewTests(unittest.TestCase):
    def view(self, raw, selected=True, verified=True):
        guards = candidates("main.tex", raw)
        self.assertEqual(len(guards), 1)
        guards[0].update(
            status="observed",
            selected=selected,
            observations=["T" if selected else "F"],
        )
        return {"guards": guards, "verified": verified}

    def test_inactive_include_and_malformed_prose_stay_in_original_but_not_active_view(
        self,
    ):
        raw = rb"""\documentclass{article}\def\mainflag{}\begin{document}
\ifdefined\mainflag
\input{active}
\else
\input{absent}\end{broken}\label{ghost}\cite{missing}
\fi
\ref{live}\end{document}"""
        tree = SourceTree(
            "tex", {"main.tex": raw, "active.tex": rb"\label{live}Active $x$."}
        )
        assembly, doc, coverage = convert_source(
            tree, "main.tex", {"bindings": []}, build_view=self.view(raw)
        )
        self.assertTrue(coverage["complete"], coverage)
        self.assertIn(rb"\input{absent}\end{broken}", assembly.data)
        self.assertEqual([r["keys"] for r in doc["labels"]], [["live"]])
        self.assertEqual(doc["citations"], [])
        self.assertTrue(assembly.validate(tree.files) == [])
        normalized, _, report = normalize_latex(assembly.text, doc, {"bindings": []})
        self.assertIn(rb"\iftrue", normalized)
        self.assertIn(rb"\input{absent}", normalized)
        self.assertEqual(report["syntax_parse"], "complete")

    def test_unverified_or_context_dependent_markers_cannot_choose_a_branch(self):
        raw = b"\\ifdefined\\flag\nTrue\n\\else\nFalse\n\\fi"
        view = self.view(raw, verified=False)
        self.assertEqual(scan_views(SourceTree("tex", {"main.tex": raw}), view), {})
        view.update(marker_prefix="QECGRAPH-VIEW-0123456789abcdef-", verified=True)
        _observations(
            view,
            "QECGRAPH-VIEW-0123456789abcdef-g0:T\nQECGRAPH-VIEW-0123456789abcdef-g0:F\n",
        )
        self.assertIsNone(view["guards"][0]["selected"])
        self.assertEqual(view["guards"][0]["status"], "context_dependent")
        self.assertEqual(scan_views(SourceTree("tex", {"main.tex": raw}), view), {})

    def test_markers_are_full_lines_and_only_allowed_insertions_change_the_copy(self):
        raw = b"\\ifx\\a\\b\nTrue\n\\fi\n"
        tree = SourceTree("tex", {"main.tex": raw})
        guards = candidates("main.tex", raw)
        prefix = "QECGRAPH-VIEW-0123456789abcdef-"
        files, changed = _instrument(tree, guards, prefix)
        self.assertEqual(tree.files["main.tex"], raw)
        self.assertEqual(changed["main.tex"], files["main.tex"])
        self.assertIn(rb"\else\immediate\write16", changed["main.tex"])
        view = {"guards": guards, "marker_prefix": prefix, "verified": True}
        _observations(view, "Echo " + prefix + "g0:F\n" + prefix + "g0:T\n")
        self.assertTrue(view["guards"][0]["selected"])
        self.assertEqual(view["guards"][0]["observations"], ["T"])

    def test_recorder_excluded_include_does_not_become_active_source(self):
        raw = rb"\documentclass{article}\begin{document}\input{unused}Visible.\end{document}"
        tree = SourceTree(
            "tex",
            {"main.tex": raw, "unused.tex": rb"\label{uncompiled}Uncompiled prose."},
        )
        assembly, doc, coverage = convert_source(
            tree, "main.tex", {"bindings": []}, used_files=["main.tex"]
        )
        self.assertFalse(coverage["complete"])
        self.assertIn("unresolved_directives", coverage["reasons"])
        self.assertNotIn(b"Uncompiled prose", assembly.data)
        self.assertEqual(doc["labels"], [])
        self.assertEqual(assembly.events[0].outcome, "not_consumed")

    def test_unsupported_operands_and_inline_guards_are_not_instrumented(self):
        for raw in [
            rb"\ifdefined\flag T\else F\fi",
            rb"\ifnum0=1 T\fi",
            rb"\newcommand{\example}{\ifdefined\flag T\fi}",
        ]:
            self.assertEqual(candidates("main.tex", raw), [])
