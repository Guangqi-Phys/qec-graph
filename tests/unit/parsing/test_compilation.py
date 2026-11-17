from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from qecgraph.preparation.compatibility import initial_compile
from qecgraph.preparation.contract import digest

from qecgraph.preparation.build import compile_tree, select_engine, _trusted_dependency
from qecgraph.source.package import SourceTree


class CompilationTests(unittest.TestCase):
    def test_legacy_hook_retry_is_hash_bound_and_keeps_failed_log(self):
        raw = b"fixture class"
        tree = SourceTree(
            "tex",
            {"main.tex": rb"\documentclass{quantumarticle}", "quantumarticle.cls": raw},
        )
        for expected_hash, retried in [(digest(raw), True), ("other", False)]:
            build = SimpleNamespace(
                entry="main.tex",
                engine="pdflatex",
                root=Path("/tmp"),
                artifacts={},
                steps=[],
                compatibility=[],
            )
            commands = []

            def runner(work, cwd, command, **options):
                commands.append(list(command))
                return {
                    "exit": 1 if len(commands) == 1 else 0,
                    "timeout": False,
                    "log": rb"Undefined control sequence. \@afterenddocumenthook",
                }

            args = ["pdflatex", "main.tex"]
            with patch(
                "qecgraph.preparation.compatibility.QUANTUMARTICLE_42", expected_hash
            ):
                success = initial_compile(build, tree, args, stdin=None, runner=runner)
            self.assertEqual(success, retried)
            self.assertEqual(len(commands), 2 if retried else 1)
            self.assertIn("logs/tex-0.log", build.artifacts)
            if retried:
                self.assertIn("-jobname=main", args)
                self.assertIn("logs/tex-compatibility-0.log", build.artifacts)
                self.assertFalse(build.compatibility[0]["source_edits"])

    def fake(self, work, cwd, command, **options):
        self.commands.append(command)
        if "-recorder" in command:
            self.assertEqual((cwd / "main.tex").read_bytes(), self.original)
            (cwd / "main.pdf").write_bytes(b"new PDF")
            (cwd / "main.aux").write_text(self.aux)
            (cwd / "main.fls").write_text("INPUT ./main.aux\nOUTPUT main.pdf\n")
        return {"exit": 0, "timeout": False, "seconds": 0, "log": b"tool log"}

    def compile(self, extra=None):
        self.commands = []
        self.original = b"\\documentclass{article}\\begin{document}Text.\\end{document}"
        tree = SourceTree("tex", {"main.tex": self.original, **(extra or {})})
        with (
            tempfile.TemporaryDirectory() as temp,
            patch(
                "qecgraph.preparation.build.tool", side_effect=lambda n: "/trusted/" + n
            ),
        ):
            return compile_tree(tree, "main.tex", Path(temp), runner=self.fake)

    def test_compile_precedes_any_conversion_and_preserves_supplied_bbl(self):
        self.aux = r"\citation{k}\bibdata{partial}"
        result = self.compile({"main.bbl": b"author supplied bibliography"})
        self.assertTrue(result.success)
        self.assertFalse(any(c[0].endswith("bibtex") for c in self.commands))
        self.assertEqual(result.inputs, ["main.aux"])

    def test_an_unrelated_bbl_does_not_suppress_bibtex(self):
        self.aux = r"\citation{k}\bibdata{references}"
        self.compile({"supplement.bbl": b"other bibliography"})
        self.assertTrue(any(c[0].endswith("bibtex") for c in self.commands))

    def test_inline_references_do_not_trigger_bibtex_from_control_files(self):
        self.aux = r"\citation{k}\bibstyle{apsrev4-2}\bibcite{k}{1}"
        self.compile({"mainNotes.bib": b"@CONTROL{REVTEX42Control}"})
        self.assertFalse(any(c[0].endswith("bibtex") for c in self.commands))

    def test_arxiv_engine_is_allowlisted_and_comments_do_not_select_plain_tex(self):
        tree = SourceTree(
            "tex", {"m.tex": b"% \\input harvmac\n\\documentclass{article}"}
        )
        self.assertEqual(select_engine(tree, "m.tex"), "pdflatex")
        tree.files["00README.json"] = b'{"process":{"compiler":"xelatex"}}'
        self.assertEqual(select_engine(tree, "m.tex"), "xelatex")
        with self.assertRaises(ValueError):
            select_engine(tree, "m.tex", "pdflatex -shell-escape")

    def test_forged_recorder_cannot_make_parent_read_user_files(self):
        self.assertFalse(
            _trusted_dependency(Path("/Users/user/.ssh/id_rsa"), Path("/tmp/build"))
        )
        self.assertFalse(
            _trusted_dependency(Path("/private/tmp/other"), Path("/tmp/build"))
        )
        self.assertTrue(
            _trusted_dependency(
                Path("/usr/local/texlive/2026/a.sty"), Path("/tmp/build")
            )
        )
