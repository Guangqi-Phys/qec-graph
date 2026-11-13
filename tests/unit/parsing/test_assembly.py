from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qecgraph.source.assembly import assemble_files, merge_blocks
from qecgraph.source.parser import parse_project


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
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, data in source.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            result = assemble_files(source, "main.tex")
            blocks_by_file = {}
            for name in ("main.tex", "a.tex"):
                parsed = parse_project(root / name, project_root=root)
                blocks_by_file[name] = [block for block in parsed["blocks"]
                                        if block["source"]["path"] == name]
            document = merge_blocks(result, blocks_by_file, source_tree_hash="0" * 64)
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
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.tex").write_bytes(source["main.tex"])
            result = assemble_files(source, "main.tex")
            parsed = parse_project(root / "main.tex", project_root=root)
            document = merge_blocks(result, {"main.tex": parsed["blocks"]},
                                    source_tree_hash="0" * 64)
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
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, data in source.items():
                (root / name).write_bytes(data)
            result = assemble_files(source, "main.tex")
            blocks_by_file = {}
            for name in ("main.tex", "b.tex"):
                parsed = parse_project(root / name, project_root=root)
                blocks_by_file[name] = [block for block in parsed["blocks"]
                                        if block["source"]["path"] == name]
            document = merge_blocks(result, blocks_by_file, source_tree_hash="0" * 64)
        section_b = next(block for block in document["blocks"]
                         if block["kind"] == "section" and block["title_tex"] == "B")
        for block in document["blocks"]:
            if block["source"]["path"] != "main.tex":
                continue
            self.assertFalse(block["entry"]["char_start"] < section_b["entry"]["char_start"]
                             < block["entry"]["char_end"])

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
