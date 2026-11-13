from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qecgraph.source.assembly import assemble_files, document_bounds, merge_blocks
from qecgraph.source.parser import parse_project


def _parse_assembled(source, entry="main.tex"):
    """Parse the assembled entry the way prepare does, then merge it."""
    result = assemble_files(source, entry)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "entry.tex"
        path.write_bytes(result.data)
        parsed = parse_project(path, project_root=root)
    return result, parsed["blocks"]


class AssembleTests(unittest.TestCase):
    def test_input_and_subfile_are_copied_byte_faithfully(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{Main}\n\\input{a}\n\\subfile{b}\n\\end{document}\n"),
            "a.tex": b"\\section{A}\\label{sec:a} A text.\n",
            "b.tex": (b"\\documentclass[../main]{subfiles}\n\\begin{document}\n"
                      b"\\section{B}\nB text.\n\\end{document}\n"),
        }
        result = assemble_files(source, "main.tex")
        self.assertIn(b"\\section{Main}", result.data)
        self.assertIn(b"\\section{A}", result.data)
        self.assertIn(b"\\section{B}", result.data)
        self.assertEqual(result.data.count(b"\\documentclass"), 1)
        self.assertEqual(result.data.count(b"\\begin{document}"), 1)
        self.assertEqual(result.validate(source), [])
        coverage = result.coverage()
        self.assertTrue(coverage["complete"])
        self.assertEqual(coverage["outcomes"], {"resolved": 2})
        self.assertEqual({event.kind for event in result.events}, {"input", "subfile"})
        targets = {event.target for event in result.events}
        self.assertEqual(targets, {"a.tex", "b.tex"})

    def test_comments_verbatim_filecontents_and_macro_bodies_are_not_expanded(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n"
                         b"% \\input{commented}\n"
                         b"\\begin{filecontents}{x.bib}\n@book{k, title={T}}\n\\end{filecontents}\n"
                         b"\\newcommand{\\foo}{\\input{in-macro}}\n"
                         b"\\begin{document}\n"
                         b"\\begin{verbatim}\n\\input{verbatim}\n\\end{verbatim}\n"
                         b"Text.\n\\end{document}\n"),
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual(result.events, [])
        self.assertEqual(result.data, source["main.tex"])
        self.assertTrue(result.coverage()["complete"])

    def test_dynamic_missing_and_escaping_paths_stay_in_entry(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\input{\\dynamic}\n\\input{missing}\n\\input{../outside}\n"
                         b"\\end{document}\n"),
        }
        result = assemble_files(source, "main.tex")
        outcomes = [event.outcome for event in result.events]
        self.assertEqual(outcomes, ["dynamic_path", "missing", "outside_root"])
        self.assertIn(b"\\input{\\dynamic}", result.data)
        self.assertFalse(result.coverage()["complete"])
        self.assertEqual(result.validate(source), [])

    def test_import_and_subimport_resolve_relative_paths(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\import{sub/}{a}\n\\subimport{chap/}{b}\n\\end{document}\n"),
            "sub/a.tex": b"A.\n",
            "chap/b.tex": b"B.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.outcome for event in result.events], ["resolved", "resolved"])
        self.assertIn(b"A.", result.data)
        self.assertIn(b"B.", result.data)
        self.assertTrue(result.coverage()["complete"])

    def test_complete_document_input_is_stripped_and_flagged(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\input{supplement}\n\\end{document}\n"),
            "supplement.tex": (b"\\documentclass{article}\n\\newcommand{\\x}{X}\n"
                               b"\\begin{document}\n\\section{Supplement}\nText.\n"
                               b"\\end{document}\n"),
        }
        result = assemble_files(source, "main.tex")
        event, = result.events
        self.assertEqual(event.outcome, "resolved")
        self.assertTrue(event.stripped_document)
        self.assertTrue(event.preamble_dropped)
        self.assertEqual(result.data.count(b"\\documentclass"), 1)
        self.assertEqual(result.data.count(b"\\begin{document}"), 1)
        self.assertIn(b"\\section{Supplement}", result.data)
        coverage = result.coverage()
        self.assertTrue(coverage["complete"])
        self.assertEqual(coverage["preamble_dropped"], 1)

    def test_merge_blocks_maps_entry_spans_and_keeps_nesting(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{Main}\n\\input{a}\n\\end{document}\n"),
            "a.tex": (b"\\section{A}\\label{sec:a}\n"
                      b"\\begin{theorem}\\label{thm:a} Statement.\\end{theorem}\n"),
        }
        result, blocks = _parse_assembled(source)
        document = merge_blocks(result, blocks, source_tree_hash="0" * 64,
                                files=source)
        self.assertEqual(document["schema"], "qecgraph.document/2")
        titles = [section["title"] for section in document["sections"]]
        self.assertEqual(titles, ["Main", "A"])
        self.assertEqual([section["level"] for section in document["sections"]], [1, 1])
        self.assertEqual(document["sections"][0]["block_ids"], ["block-1"])
        theorem_block = next(block for block in document["blocks"] if block["kind"] == "theorem")
        self.assertEqual(theorem_block["text"], "Statement.")
        self.assertEqual(theorem_block["section_id"], document["sections"][1]["id"])
        theorem = next(block for block in document["blocks"] if block["kind"] == "theorem")
        section = next(block for block in document["blocks"]
                       if block["kind"] == "section" and block["title_tex"] == "A")
        self.assertEqual(theorem["parent_key"], section["key"])
        self.assertEqual(theorem["source"]["path"], "a.tex")
        self.assertIn("\\begin{theorem}",
                      result.text[theorem["entry"]["char_start"]:theorem["entry"]["char_end"]])

    def test_section_levels_numbering_appendix_and_section_membership(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{Main}\nText.\n"
                         b"\\subsection{Sub}\nSub text.\n"
                         b"% \\appendix\n"
                         b"\\section*{Unnumbered}\nMore.\n"
                         b"\\appendix\n\\section{Appendix}\nApp text.\n"
                         b"\\end{document}\n"),
        }
        result, blocks = _parse_assembled(source)
        document = merge_blocks(result, blocks, source_tree_hash="0" * 64,
                                files=source)
        self.assertEqual([section["level"] for section in document["sections"]],
                         [1, 2, 1, 1])
        self.assertEqual([section["parent_id"] for section in document["sections"]],
                         [None, "s1", None, None])
        self.assertEqual([section["numbered"] for section in document["sections"]],
                         [True, True, False, True])
        self.assertEqual([section["appendix"] for section in document["sections"]],
                         [False, False, False, True])
        self.assertEqual([section["command"] for section in document["sections"]],
                         ["section", "subsection", "section", "section"])
        appendix = document["sections"][-1]
        self.assertIn("App text.", [block["text"] for block in document["blocks"]
                                    if block["section_id"] == appendix["id"]])

    def test_path_macro_state_follows_source_order(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\newcommand{\\DIR}{one}\n"
                         b"\\begin{document}\n\\input{\\DIR/frag}\n"
                         b"\\renewcommand{\\DIR}{two}\n\\input{\\DIR/frag}\n"
                         b"\\end{document}\n"),
            "one/frag.tex": b"FIRST_BODY.\n",
            "two/frag.tex": b"SECOND_BODY.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.target for event in result.events],
                         ["one/frag.tex", "two/frag.tex"])
        self.assertEqual([event.expanded_args for event in result.events],
                         [("one/frag",), ("two/frag",)])
        self.assertLess(result.data.index(b"FIRST_BODY."),
                        result.data.index(b"SECOND_BODY."))
        self.assertTrue(result.coverage()["complete"])

    def test_path_macro_definition_inside_a_group_does_not_leak(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\newcommand{\\DIR}{one}\n"
                         b"\\begin{document}\n"
                         b"{\\renewcommand{\\DIR}{two}\\input{\\DIR/frag}}\n"
                         b"\\input{\\DIR/frag}\n\\end{document}\n"),
            "one/frag.tex": b"ONE_BODY.\n",
            "two/frag.tex": b"TWO_BODY.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.target for event in result.events],
                         ["two/frag.tex", "one/frag.tex"])
        self.assertLess(result.data.index(b"TWO_BODY."),
                        result.data.index(b"ONE_BODY."))

    def test_path_macro_in_inactive_conditional_is_not_learned(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\newcommand{\\DIR}{one}\n"
                         b"\\begin{document}\n\\input{\\DIR/frag}\n"
                         b"\\iffalse\\renewcommand{\\DIR}{two}\\fi\n"
                         b"\\input{\\DIR/frag}\n\\end{document}\n"),
            "one/frag.tex": b"ONE_BODY.\n",
            "two/frag.tex": b"TWO_BODY.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.target for event in result.events],
                         ["one/frag.tex", "one/frag.tex"])
        self.assertNotIn(b"TWO_BODY.", result.data)

    def test_non_literal_redefinition_makes_a_path_uncertain(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\newcommand{\\DIR}{one}\n"
                         b"\\newcommand{\\OTHER}{two}\n\\begin{document}\n"
                         b"\\renewcommand{\\DIR}{\\OTHER}\n"
                         b"\\input{\\DIR/frag}\n\\end{document}\n"),
            "one/frag.tex": b"STALE_ONE.\n",
            "two/frag.tex": b"CORRECT_TWO.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.outcome for event in result.events],
                         ["uncertain_path"])
        self.assertIsNone(result.events[0].target)
        self.assertIn(b"\\input{\\DIR/frag}", result.data)
        self.assertNotIn(b"STALE_ONE.", result.data)
        self.assertFalse(result.coverage()["complete"])

    def test_empty_redefinition_resolves_the_empty_path(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\newcommand{\\PREFIX}{old}\n"
                         b"\\begin{document}\n\\renewcommand{\\PREFIX}{}\n"
                         b"\\input{\\PREFIX-frag}\n\\end{document}\n"),
            "old-frag.tex": b"STALE_OLD.\n",
            "-frag.tex": b"CORRECT_EMPTY.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.target for event in result.events], ["-frag.tex"])
        self.assertIn(b"CORRECT_EMPTY.", result.data)
        self.assertNotIn(b"STALE_OLD.", result.data)
        self.assertTrue(result.coverage()["complete"])

    def test_definition_in_an_undecidable_conditional_does_not_leak(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\ifdefined\\flag\\newcommand{\\DIR}{two}"
                         b"\\input{\\DIR/frag}\\fi\n"
                         b"\\input{\\DIR/frag}\n\\end{document}\n"),
            "two/frag.tex": b"TWO_BODY.\n",
            "one/frag.tex": b"ONE_BODY.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.outcome for event in result.events],
                         ["resolved", "uncertain_path"])
        self.assertEqual(result.events[0].target, "two/frag.tex")
        self.assertIsNone(result.events[1].target)
        self.assertIn(b"TWO_BODY.", result.data)
        self.assertNotIn(b"ONE_BODY.", result.data)

    def test_equal_conditional_branches_keep_a_definite_path(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\newcommand{\\DIR}{one}\n"
                         b"\\begin{document}\n"
                         b"\\ifdefined\\flag\\renewcommand{\\DIR}{two}"
                         b"\\else\\renewcommand{\\DIR}{two}\\fi\n"
                         b"\\input{\\DIR/frag}\n\\end{document}\n"),
            "one/frag.tex": b"ONE_BODY.\n",
            "two/frag.tex": b"TWO_BODY.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.target for event in result.events], ["two/frag.tex"])
        self.assertTrue(result.coverage()["complete"])

    def test_gdef_overrides_a_local_definition(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\newcommand{\\DIR}{one}\n"
                         b"\\begin{document}\n"
                         b"{\\renewcommand{\\DIR}{two}\\gdef\\DIR{three}"
                         b"\\input{\\DIR/frag}}\n"
                         b"\\input{\\DIR/frag}\n\\end{document}\n"),
            "one/frag.tex": b"ONE_BODY.\n",
            "two/frag.tex": b"TWO_BODY.\n",
            "three/frag.tex": b"THREE_BODY.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.target for event in result.events],
                         ["three/frag.tex", "three/frag.tex"])

    def test_begingroup_scopes_a_path_definition(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\newcommand{\\DIR}{one}\n"
                         b"\\begin{document}\n\\begingroup\n"
                         b"\\renewcommand{\\DIR}{two}\\input{\\DIR/frag}\n"
                         b"\\endgroup\n\\input{\\DIR/frag}\n"
                         b"\\end{document}\n"),
            "one/frag.tex": b"ONE_BODY.\n",
            "two/frag.tex": b"TWO_BODY.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.target for event in result.events],
                         ["two/frag.tex", "one/frag.tex"])

    def test_path_macro_used_before_its_definition_stays_dynamic(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\input{\\DIR/frag}\n\\newcommand{\\DIR}{one}\n"
                         b"\\input{\\DIR/frag}\n\\end{document}\n"),
            "one/frag.tex": b"ONE_BODY.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.outcome for event in result.events],
                         ["dynamic_path", "resolved"])
        self.assertIn(b"\\input{\\DIR/frag}", result.data)
        self.assertFalse(result.coverage()["complete"])

    def test_literal_zero_argument_macro_resolves_an_input_path(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\input{pre}\n\\input{\\Root/body}\n\\end{document}\n"),
            "pre.tex": b"\\newcommand{\\Root}{.}\n",
            "body.tex": b"Body.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertEqual([event.outcome for event in result.events], ["resolved", "resolved"])
        self.assertIn(b"Body.", result.data)
        self.assertTrue(result.coverage()["complete"])
        body_event = result.events[1]
        self.assertEqual(body_event.expanded_args, ("./body",))
        self.assertEqual(body_event.target, "body.tex")

    def test_paragraph_spanning_subfile_is_split_at_the_replace_point(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{Main}\nBefore.\n\\subfile{b}\nAfter.\n\\end{document}\n"),
            "b.tex": (b"\\documentclass[../main]{subfiles}\n\\begin{document}\n"
                      b"\\section{B}\nB text.\n\\end{document}\n"),
        }
        result, blocks = _parse_assembled(source)
        document = merge_blocks(result, blocks, source_tree_hash="0" * 64,
                                files=source)
        section_b = next(block for block in document["blocks"]
                         if block["kind"] == "section" and block["title_tex"] == "B")
        for block in document["blocks"]:
            if block["source"]["path"] != "main.tex":
                continue
            self.assertFalse(block["entry"]["char_start"] < section_b["entry"]["char_start"]
                             < block["entry"]["char_end"])

    def test_import_context_applies_to_nested_inputs(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\import{chap/}{main.tex}\n"
                         b"\\input{section.tex}\n\\end{document}\n"),
            "chap/main.tex": b"\\input{section.tex}\n",
            "chap/section.tex": b"CORRECT_CHAPTER.\n",
            "section.tex": b"UNRELATED_ROOT.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertIn(b"CORRECT_CHAPTER.", result.data)
        self.assertIn(b"UNRELATED_ROOT.", result.data)
        nested = [event for event in result.events
                  if event.path == "chap/main.tex"]
        self.assertEqual([event.target for event in nested], ["chap/section.tex"])
        root = [event for event in result.events if event.path == "main.tex"]
        self.assertEqual([event.kind for event in root], ["import", "input"])
        self.assertEqual([event.target for event in root], ["chap/main.tex", "section.tex"])
        self.assertEqual(result.validate(source), [])

    def test_subimport_resolves_relative_to_the_imported_directory(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\import{chap/}{main}\n\\end{document}\n"),
            "chap/main.tex": b"\\subimport{sec/}{section}\n",
            "chap/sec/section.tex": b"SUBIMPORTED.\n",
        }
        result = assemble_files(source, "main.tex")
        self.assertIn(b"SUBIMPORTED.", result.data)
        self.assertEqual([event.outcome for event in result.events],
                         ["resolved", "resolved"])

    def test_math_iff_does_not_open_a_conditional(self):
        text = ("\\documentclass{article}\n\\begin{document}\n"
                "$A \\iff B$ and $C \\iff D$.\n\\end{document}\n")
        begin, body, end = document_bounds(text)
        self.assertIsNotNone(begin)
        self.assertIsNotNone(body)
        self.assertIsNotNone(end)
        self.assertTrue(text[end:].startswith("\\end{document}"))

    def test_document_bounds_ignore_declarations_and_inactive_branches(self):
        text = ("\\documentclass{article}\n\\begin{document}\nA.\n"
                "\\newcommand{\\finish}{\\end{document}}\n"
                "\\iffalse\\end{document}\\fi\nB.\n\\end{document}\n")
        begin, body, end = document_bounds(text)
        self.assertIsNotNone(begin)
        self.assertIsNotNone(body)
        self.assertIsNotNone(end)
        self.assertIn("B.", text[body:end])
        self.assertTrue(text[end:].startswith("\\end{document}"))

    def test_literal_document_end_does_not_truncate_included_tail(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\input{supp}\n\\end{document}\n"),
            "supp.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{First}\nBefore.\n"
                         b"\\verb|\\end{document}|\n"
                         b"\\begin{verbatim}\n\\end{document}\n\\end{verbatim}\n"
                         b"\\section{Second}\nACTUAL_TAIL.\n\\end{document}\n"),
        }
        result = assemble_files(source, "main.tex")
        self.assertIn(b"\\section{Second}", result.data)
        self.assertIn(b"ACTUAL_TAIL.", result.data)
        self.assertIn(b"\\verb|\\end{document}|", result.data)
        self.assertEqual(result.data.count(b"\\begin{document}"), 1)
        event, = result.events
        self.assertEqual(event.outcome, "resolved")
        self.assertTrue(event.stripped_document)
        second = result.data.index(b"\\section{Second}")
        tail = result.data.index(b"ACTUAL_TAIL.")
        self.assertLess(result.data.index(b"\\end{verbatim}"), second)
        self.assertLess(second, tail)
        self.assertEqual(result.validate(source), [])


if __name__ == "__main__":
    unittest.main()

    def test_missing_preamble_include_is_a_dependency_not_content_loss(self):
        source = {
            "main.tex": (b"\\documentclass{article}\n\\input{missing-preamble}\n"
                         b"\\begin{document}\n\\section{Body}\nText.\n\\end{document}\n"),
        }
        result = assemble_files(source, "main.tex")
        event, = result.events
        self.assertEqual((event.outcome, event.region), ("missing", "preamble"))
        coverage = result.coverage()
        self.assertTrue(coverage["complete"])
        self.assertEqual(coverage["preamble_missing"], 1)
