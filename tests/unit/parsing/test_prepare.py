from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest
from unittest import mock

from qecgraph.source.assembly import EntryCoordinates, assemble_files
from qecgraph.source.package import SourceTree
from qecgraph.source.prepare import (
    _coverage,
    _outside_dependencies,
    _uncovered_entry_prose,
    entry_candidates,
    prepare_source,
    write_outputs,
)


class PrepareTests(unittest.TestCase):
    def test_prepare_builds_section_tree_and_text(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{Introduction}\nText.\n"
                         b"\\subsection{Details}\nMore.\n"
                         b"\\end{document}\n"),
        })
        prepared = prepare_source(tree)
        self.assertEqual(prepared.entry, "main.tex")
        self.assertTrue(prepared.coverage["content_complete"])
        self.assertTrue(prepared.coverage["structure_complete"])
        self.assertTrue(prepared.coverage["document_complete"])
        document = prepared.document
        self.assertEqual(document["schema"], "qecgraph.document/2")
        self.assertEqual([section["title"] for section in document["sections"]],
                         ["Introduction", "Details"])
        self.assertEqual([section["level"] for section in document["sections"]], [1, 2])
        self.assertEqual(document["sections"][1]["parent_id"],
                         document["sections"][0]["id"])
        texts = [block["text"] for block in document["blocks"]]
        self.assertIn("Text.", texts)
        self.assertIn("More.", texts)

    def test_content_detection_accepts_an_extensionless_entry(self):
        tree = SourceTree("directory", {
            "tqecp": (b"\\documentstyle[11pt]{article}\n\\begin{document}\n"
                      b"\\section{Introduction}\nText.\n\\end{document}\n"),
        })
        self.assertEqual(entry_candidates(tree), ["tqecp"])
        prepared = prepare_source(tree)
        self.assertEqual(prepared.entry, "tqecp")
        self.assertEqual([section["title"] for section in prepared.document["sections"]],
                         ["Introduction"])
        self.assertTrue(prepared.coverage["content_complete"])

    def test_missing_preamble_dependency_does_not_lose_content(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\input{missing-preamble}\n"
                         b"\\begin{document}\n\\section{Body}\nText.\n\\end{document}\n"),
        })
        prepared = prepare_source(tree)
        self.assertTrue(prepared.coverage["content_complete"])
        self.assertTrue(prepared.coverage["structure_complete"])
        self.assertEqual(prepared.coverage["preamble_missing"], 1)
        self.assertIn("Text.", [block["text"] for block in prepared.document["blocks"]])

    def test_literal_document_end_does_not_truncate_included_tail(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\input{supp}\n\\end{document}\n"),
            "supp.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{First}\nBefore.\n"
                         b"\\begin{verbatim}\n\\end{document}\n\\end{verbatim}\n"
                         b"\\section{Second}\nACTUAL_TAIL.\n\\end{document}\n"),
        })
        prepared = prepare_source(tree, "main.tex")
        titles = [section["title"] for section in prepared.document["sections"]]
        self.assertEqual(titles, ["First", "Second"])
        texts = [block["text"] for block in prepared.document["blocks"]]
        self.assertIn("ACTUAL_TAIL.", texts)
        self.assertTrue(prepared.coverage["document_complete"])

    def test_import_keeps_the_imported_directory_context(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\import{chap/}{main.tex}\n\\end{document}\n"),
            "chap/main.tex": b"\\input{section.tex}\n",
            "chap/section.tex": b"CORRECT_CHAPTER.\n",
            "section.tex": b"UNRELATED_ROOT.\n",
        })
        prepared = prepare_source(tree, "main.tex")
        texts = [block["text"] for block in prepared.document["blocks"]]
        self.assertEqual(texts, ["CORRECT_CHAPTER."])
        self.assertTrue(prepared.coverage["document_complete"])

    def test_theorem_declared_in_the_entry_applies_to_an_included_file(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n"
                         b"\\newtheorem{specialthm}{Theorem}\n"
                         b"\\begin{document}\n\\input{frag}\n\\end{document}\n"),
            "frag.tex": (b"\\begin{specialthm}\\label{thm:one}\n"
                         b"IMPORTANT_THEOREM.\n\\end{specialthm}\n"),
        })
        prepared = prepare_source(tree)
        block = next(block for block in prepared.document["blocks"]
                     if block["kind"] == "theorem")
        self.assertEqual(block["environment"], "specialthm")
        self.assertEqual(block["source"]["path"], "frag.tex")
        self.assertIn("thm:one", block["labels"])
        self.assertIn("IMPORTANT_THEOREM.", block["text"])

    def test_included_theorem_body_stays_inside_its_theorem(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n"
                         b"\\newtheorem{theorem}{Theorem}\n"
                         b"\\begin{document}\n"
                         b"\\begin{theorem}\\input{body}\\end{theorem}\n"
                         b"\\end{document}\n"),
            "body.tex": b"INSIDE_THEOREM_BODY.\n",
        })
        prepared = prepare_source(tree)
        blocks = prepared.document["blocks"]
        self.assertEqual([block["kind"] for block in blocks], ["theorem"])
        self.assertEqual(blocks[0]["text"], "INSIDE_THEOREM_BODY.")
        self.assertTrue(blocks[0]["spans_include"])
        self.assertEqual([span["path"] for span in blocks[0]["source_spans"]],
                         ["main.tex", "body.tex", "main.tex"])

    def test_extensionless_fragment_reaches_the_document_model(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\\begin{document}"
                         b"\\section{Intro}\\input{fragment}\\end{document}"),
            "fragment": b"IMPORTANT_EXTENSIONLESS_BODY.\n",
        })
        prepared = prepare_source(tree, "main.tex")
        texts = [block["text"] for block in prepared.document["blocks"]]
        self.assertIn("IMPORTANT_EXTENSIONLESS_BODY.", texts)
        self.assertTrue(prepared.coverage["content_complete"])
        self.assertTrue(prepared.coverage["document_complete"])
        self.assertEqual(prepared.coverage["missing_dependencies"], 0)

    def test_child_comment_without_final_newline_keeps_parent_text(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\\begin{document}\\section{Intro}\n"
                         b"\\input{a}MUST_SURVIVE.\\end{document}"),
            "a.tex": b"PRECEDING_BODY.% trailing comment",
        })
        prepared = prepare_source(tree, "main.tex")
        texts = [block["text"] for block in prepared.document["blocks"]]
        self.assertTrue(any("MUST_SURVIVE." in text for text in texts))
        block = next(block for block in prepared.document["blocks"]
                     if "MUST_SURVIVE." in block["text"])
        self.assertEqual({span["path"] for span in block["source_spans"]},
                         {"a.tex", "main.tex"})
        self.assertTrue(prepared.coverage["document_complete"])
        self.assertIn(b"commentMUST_SURVIVE.", prepared.assembly.data)
        self.assertEqual(prepared.assembly.validate(tree.files), [])

    def test_iffalse_with_a_comment_keeps_the_else_branch(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{Intro}\n"
                         b"\\iffalse\n% disabled branch\n\\input{unused}\n"
                         b"\\else\n\\input{active}\n\\fi\n"
                         b"\\end{document}\n"),
            "unused.tex": b"NOT_ACTIVE.\n",
            "active.tex": b"ACTIVE_BODY.\n",
        })
        prepared = prepare_source(tree, "main.tex")
        texts = [block["text"] for block in prepared.document["blocks"]]
        self.assertTrue(any("ACTIVE_BODY." in text for text in texts))
        self.assertNotIn(b"NOT_ACTIVE.", prepared.assembly.data)
        self.assertTrue(prepared.coverage["document_complete"])

    def test_body_include_outside_entry_breaks_content_completeness(self):
        result = assemble_files({"main.tex": (
            b"\\documentclass{article}\\begin{document}Text.\\end{document}")},
            "main.tex")
        document = {"blocks": [{"entry": {"char_start": 40, "char_end": 45}}]}
        dependency = {"code": "include_not_in_entry", "path": "main.tex",
                      "region": "body"}
        body = _coverage(result, document, [], [dependency])
        self.assertFalse(body["content_complete"])
        self.assertIn("include_outside_entry", body["reasons"])
        self.assertEqual(body["outside_entry_dependencies"], 1)
        preamble = _coverage(result, document, [], [{**dependency,
                                                    "region": "preamble"}])
        self.assertTrue(preamble["content_complete"])
        self.assertEqual(preamble["outside_entry_dependencies"], 0)

    def test_outside_dependencies_record_body_or_preamble_region(self):
        result = assemble_files({"entry.tex": b"0123456789"}, "entry.tex")
        coords = EntryCoordinates(result)
        parsed = {"includes": [{"to": "x.tex",
                                "source": {"path": "entry.tex",
                                           "char_start": 8}}]}
        body = _outside_dependencies(parsed, "entry.tex", coords, 5,
                                     ["x.tex"], "main.tex")
        self.assertEqual([item["region"] for item in body], ["body"])
        preamble = _outside_dependencies(parsed, "entry.tex", coords, 9,
                                         ["x.tex"], "main.tex")
        self.assertEqual([item["region"] for item in preamble], ["preamble"])
        self.assertEqual(_outside_dependencies(
            parsed, "entry.tex", coords, 5, ["refs.bib"], "main.tex"), [])

    def test_iffalse_else_branch_is_assembled(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\\begin{document}\n"
                         b"\\section{Intro}\n"
                         b"\\iffalse\\input{unused}\\else\\input{active}\\fi\n"
                         b"\\end{document}\n"),
            "unused.tex": b"NOT_ACTIVE.\n",
            "active.tex": b"ACTIVE_BODY.\n",
        })
        prepared = prepare_source(tree, "main.tex")
        texts = [block["text"] for block in prepared.document["blocks"]]
        self.assertTrue(any("ACTIVE_BODY." in text for text in texts))
        self.assertNotIn(b"NOT_ACTIVE.", prepared.assembly.data)
        self.assertTrue(prepared.coverage["content_complete"])

    def test_include_inside_an_undecidable_conditional_is_partial(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\ifdefined\\flag\\input{yes}\\else\\input{no}\\fi\n"
                         b"\\end{document}\n"),
            "yes.tex": b"YES_BODY.\n",
            "no.tex": b"NO_BODY.\n",
        })
        prepared = prepare_source(tree)
        self.assertTrue(prepared.coverage["content_complete"])
        self.assertFalse(prepared.coverage["structure_complete"])
        self.assertIn("conditional_directives", prepared.coverage["reasons"])
        self.assertEqual(prepared.coverage["conditional_directives"], 1)

    def test_uncovered_body_prose_breaks_structure_completeness(self):
        text = (r"\documentclass{article}\begin{document}\section{A}"
                "Unrepresented prose."
                r"\begin{comment}Not content.\end{comment}"
                r"\vspace{1em}\label{x}\end{document}")
        covered = [{"entry": {"char_start": 0, "char_end": len(text)}}]
        self.assertEqual(_uncovered_entry_prose(text, covered), 0)
        section_end = text.index("}") + 1
        partial = [{"entry": {"char_start": 0, "char_end": section_end}}]
        self.assertGreater(_uncovered_entry_prose(text, partial), 0)
        only_literal = (r"\documentclass{article}\begin{document}\section{A}"
                        r"\begin{comment}Hidden.\end{comment}\end{document}")
        literal_blocks = [{"entry": {
            "char_start": 0,
            "char_end": only_literal.index(r"\begin{comment}")}}]
        self.assertEqual(_uncovered_entry_prose(only_literal, literal_blocks), 0)

    def test_path_macro_redefinition_keeps_source_order(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\newcommand{\\DIR}{one}\n"
                         b"\\begin{document}\n\\input{\\DIR/frag}\n"
                         b"\\renewcommand{\\DIR}{two}\n\\input{\\DIR/frag}\n"
                         b"\\end{document}\n"),
            "one/frag.tex": b"FIRST_BODY.\n",
            "two/frag.tex": b"SECOND_BODY.\n",
        })
        prepared = prepare_source(tree)
        self.assertEqual([block["text"] for block in prepared.document["blocks"]],
                         ["FIRST_BODY.", "SECOND_BODY."])
        self.assertTrue(prepared.coverage["document_complete"])

    def test_repeated_include_yields_one_block_per_occurrence(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{A}\n\\input{frag}\n"
                         b"\\section{B}\n\\input{frag}\n\\end{document}\n"),
            "frag.tex": b"REPEATED_CONTENT.\n",
        })
        prepared = prepare_source(tree)
        document = prepared.document
        self.assertEqual(prepared.assembly.text.count("REPEATED_CONTENT."), 2)
        paragraphs = [block for block in document["blocks"]
                      if block["kind"] == "paragraph"]
        self.assertEqual([block["text"] for block in paragraphs],
                         ["REPEATED_CONTENT.", "REPEATED_CONTENT."])
        self.assertEqual([block["source"]["path"] for block in paragraphs],
                         ["frag.tex", "frag.tex"])
        self.assertEqual(paragraphs[0]["source"]["char_start"],
                         paragraphs[1]["source"]["char_start"])
        self.assertNotEqual(paragraphs[0]["entry"]["char_start"],
                            paragraphs[1]["entry"]["char_start"])
        titles = {section["id"]: section["title"] for section in document["sections"]}
        self.assertEqual(titles[paragraphs[0]["section_id"]], "A")
        self.assertEqual(titles[paragraphs[1]["section_id"]], "B")

    def test_theorem_body_group_is_not_stripped_as_an_environment_argument(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n"
                         b"\\newtheorem{theorem}{Theorem}\n"
                         b"\\begin{document}\n"
                         b"\\begin{theorem}{IMPORTANT_ASSERTION} rest.\\end{theorem}\n"
                         b"\\begin{theorem}[Named] Titled.\\end{theorem}\n"
                         b"\\end{document}\n"),
        })
        prepared = prepare_source(tree)
        texts = [block["text"] for block in prepared.document["blocks"]]
        self.assertTrue(any("IMPORTANT_ASSERTION" in text for text in texts))
        self.assertIn("Titled.", texts)
        self.assertFalse(any("Named" in text for text in texts))

    def test_write_outputs_matches_the_document_schema(self):
        tree = SourceTree("directory", {
            "main.tex": (b"\\documentclass{article}\n\\begin{document}\n"
                         b"\\section{Body}\nText.\n\\end{document}\n"),
        })
        prepared = prepare_source(tree)
        with TemporaryDirectory() as temporary:
            out = Path(temporary)
            manifest = write_outputs(prepared, out, parser_version="test")
            self.assertEqual(manifest["schema"], "qecgraph.prepare/2")
            self.assertEqual(json.loads((out / "document.json").read_text())["schema"],
                             "qecgraph.document/2")
            for name in ("entry.tex", "source-map.json", "document.json",
                         "coverage.json", "diagnostics.json", "manifest.json"):
                self.assertTrue((out / name).is_file(), name)


    def _prepared(self, text="New text."):
        tree = SourceTree("directory", {
            "main.tex": ("\\documentclass{article}\\begin{document}"
                         + text + "\\end{document}").encode("utf-8"),
        })
        return prepare_source(tree)

    def test_write_outputs_refuses_unmanaged_directory(self):
        prepared = self._prepared()
        with TemporaryDirectory() as temporary:
            out = Path(temporary)
            canary = out / "entry.tex"
            canary.write_text("USER_ORIGINAL_CANARY", encoding="utf-8")
            with self.assertRaises(ValueError):
                write_outputs(prepared, out)
            self.assertEqual(canary.read_text(encoding="utf-8"),
                             "USER_ORIGINAL_CANARY")
            self.assertEqual([path.name for path in out.iterdir()], ["entry.tex"])
            manifest = write_outputs(prepared, out, overwrite=True)
            self.assertEqual(manifest["schema"], "qecgraph.prepare/2")
            self.assertIn("New text.", (out / "entry.tex").read_text(encoding="utf-8"))

    def test_write_outputs_replaces_a_managed_directory_whole(self):
        with TemporaryDirectory() as temporary:
            out = Path(temporary) / "prepared"
            write_outputs(self._prepared("First text."), out)
            stale = out / "stale.json"
            stale.write_text("{}", encoding="utf-8")
            manifest = write_outputs(self._prepared("Second text."), out)
            self.assertEqual(manifest["entry"], "main.tex")
            self.assertFalse(stale.exists())
            self.assertIn("Second text.",
                          (out / "entry.tex").read_text(encoding="utf-8"))

    def test_write_outputs_refuses_source_overlap_and_symlinks(self):
        prepared = self._prepared()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "main.tex").write_bytes(
                b"\\documentclass{article}\\begin{document}X.\\end{document}")
            with self.assertRaises(ValueError):
                write_outputs(prepared, source, source=source)
            with self.assertRaises(ValueError):
                write_outputs(prepared, source / "out", source=source)
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            link = root / "link"
            os.symlink(elsewhere, link)
            with self.assertRaises(ValueError):
                write_outputs(prepared, link)

    def test_failed_write_keeps_the_previous_complete_result(self):
        with TemporaryDirectory() as temporary:
            out = Path(temporary) / "prepared"
            write_outputs(self._prepared("First text."), out)
            before = {path.name: path.read_bytes() for path in out.iterdir()}
            with mock.patch("qecgraph.source.prepare._write_artifacts",
                            side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    write_outputs(self._prepared("Second text."), out)
            after = {path.name: path.read_bytes() for path in out.iterdir()}
            self.assertEqual(before, after)
            self.assertEqual([path.name for path in out.parent.iterdir()],
                             ["prepared"])


if __name__ == "__main__":
    unittest.main()
