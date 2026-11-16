import base64
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from qecgraph.llm.client import LLMClient
from qecgraph.llm.prepare import normalize_input
from qecgraph.llm.providers.base import Completion
from qecgraph.llm.skills import load_skill
from qecgraph.source.normalization import apply_plan, load_for_preparation
from qecgraph.source.package import SourceTree, PackageError
from qecgraph.source.prepare import prepare_input, parse_prepared
from tests.unit.domain.test_ai_client import config
from tools.prepare_arxiv import main

TEX = b"\\documentclass{article}\n\\begin{document}\nBody.\n\\end{document}\n"


def plan(entry="main.tex", edits=None):
    return dict(
        status="ready", entry=entry, encodings=[], edits=edits or [], unresolved=[]
    )


def edit(old, new, **extra):
    return dict(
        path="main.tex",
        old=old,
        new=new,
        evidence=old,
        reason="Repair source syntax only.",
        **extra,
    )


class Provider:
    name = "fake"
    kind = "cli"

    def __init__(self, value):
        self.value = value
        self.messages = []

    def complete(self, messages, **kwargs):
        self.messages.append(messages)
        return Completion(json.dumps(self.value), "fake-model", {"cost": 0})


class PreparationBoundaryTests(unittest.TestCase):
    def apply(self, tree, value):
        return apply_plan(tree, value, load_skill("prepare_input").schema)

    def test_known_format_adapter_finishes_before_any_model_configuration_or_call(self):
        raw = TEX.replace(
            b"\\begin{document}",
            b"\\newcommand{\\nc}{\\providecommand}\n"
            b"\\nc{\\rnc}{\\renewcommand}\n\\begin{document}",
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_bytes(raw)
            out = Path(directory) / "prepared"
            with patch(
                "qecgraph.llm.config.load_ai_config",
                side_effect=AssertionError("unneeded model"),
            ):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        main(
                            [
                                str(source),
                                "--out",
                                str(out),
                                "--ai-prepare",
                                "--ai-config-root",
                                directory,
                            ]
                        ),
                        0,
                    )
            self.assertEqual(source.read_bytes(), raw)
            saved = json.loads((out / "normalization.json").read_text())
            self.assertEqual(saved["method"], "deterministic_format_adapter")
            self.assertNotIn("model", saved)

    def test_preparing_input_never_calls_parser_and_parser_accepts_the_handoff(self):
        tree = SourceTree("tex", {"main.tex": TEX})
        with patch(
            "qecgraph.source.prepared_parser.parse_project",
            side_effect=AssertionError("preparation parsed"),
        ):
            handoff = prepare_input(tree)
        self.assertEqual(handoff.assembly.data, TEX)
        self.assertTrue(parse_prepared(handoff, tree).coverage["complete"])
        tree.files["main.tex"] += b"changed"
        with self.assertRaisesRegex(ValueError, "does not match"):
            parse_prepared(handoff, tree)

    def test_ai_only_selects_input_and_never_runs_parser_or_extracts(self):
        tree = SourceTree("tex", {"main.tex": TEX})
        provider = Provider(plan())
        with patch(
            "qecgraph.source.prepared_parser.parse_project",
            side_effect=AssertionError("AI parsed"),
        ):
            normalized = normalize_input(
                tree, LLMClient(config(max_input_chars=200000), provider=provider)
            )
        self.assertEqual(normalized.tree.files, tree.files)
        self.assertEqual(normalized.entry, "main.tex")
        self.assertEqual(normalized.provenance["status"], "proposed")
        self.assertNotIn("blocks", normalized.provenance)

    def test_no_word_number_macro_or_comment_rewrite_can_be_accepted(self):
        tree = SourceTree("tex", {"main.tex": TEX})
        for old, new in [
            ("Body.", "Different."),
            ("Body.", "\\Body."),
            ("Body.", "%Body."),
            ("Body.", ""),
        ]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                self.apply(tree, plan(edits=[edit(old, new)]))
        with self.assertRaises(Exception):
            self.apply(tree, {**plan(), "blocks": []})

    def test_small_delimiter_repair_preserves_original_bytes(self):
        raw = TEX.replace(b"Body.", b"The $n is fixed.")
        tree = SourceTree("tex", {"main.tex": raw})
        n = self.apply(
            tree, plan(edits=[edit("The $n is fixed.", "The $n$ is fixed.")])
        )
        self.assertIn(b"The $n$ is fixed.", n.tree.files["main.tex"])
        self.assertEqual(tree.files["main.tex"], raw)
        self.assertEqual(
            base64.b64decode(
                n.provenance["original_files"]["main.tex"]["bytes_base64"]
            ),
            raw,
        )

    def test_ambiguous_and_overlapping_edits_are_rejected(self):
        tree = SourceTree("tex", {"main.tex": TEX.replace(b"Body.", b"Body.\nBody.")})
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.apply(tree, plan(edits=[edit("Body.", "{Body.}")]))
        value = plan(
            edits=[
                edit("Body.", "Body.}", occurrence=1),
                edit("Body.", "Body.}}", occurrence=1),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            self.apply(tree, value)

    def test_encoding_projection_is_explicit_and_original_is_retained(self):
        raw = TEX.replace(b"Body.", b"caf\xe9.")
        tree = SourceTree("tex", {"main.tex": raw})
        with self.assertRaises(UnicodeDecodeError):
            self.apply(tree, plan())
        value = plan()
        value["encodings"] = [{"path": "main.tex", "encoding": "latin1"}]
        n = self.apply(tree, value)
        self.assertIn("caf\xe9.", n.tree.files["main.tex"].decode())
        self.assertEqual(tree.files["main.tex"], raw)
        with self.assertRaises(UnicodeDecodeError):
            self.apply(tree, plan())

    def test_declaration_alias_conversion_keeps_arguments_and_literal_examples(self):
        definitions = (
            r"\newcommand{\nc}{\providecommand}"
            + "\n"
            + r"\nc{\rnc}{\renewcommand}"
            + "\n"
            + r"\nc{\bra}[1]{\langle#1|}"
            + "\n"
            + r"% \nc{comment}{not a declaration}"
            + "\n"
        )
        body = r"\begin{verbatim}\nc{example}{literal}\end{verbatim}"
        raw = TEX.replace(
            b"\\begin{document}", definitions.encode() + b"\\begin{document}"
        )
        raw = raw.replace(b"Body.", body.encode())
        n = self.apply(
            SourceTree("tex", {"main.tex": raw}),
            {**plan(), "declaration_aliases": ["main.tex"]},
        )
        normalized = n.tree.files["main.tex"]
        self.assertIn(b"\\providecommand{\\bra}[1]{\\langle#1|}", normalized)
        self.assertIn(body.encode(), normalized)
        self.assertIn(b"% \\nc{comment}{not a declaration}", normalized)

    def test_drawing_conversion_cannot_cross_the_original_picture_boundary(self):
        raw = TEX.replace(
            b"Body.",
            (
                r"\begin{tikzpicture}A\end{tikzpicture}"
                r"SCIENTIFIC TEXT\begin{tikzpicture}B\end{tikzpicture}"
            ).encode(),
        )
        tree = SourceTree("tex", {"main.tex": raw})
        with self.assertRaisesRegex(ValueError, "pair"):
            self.apply(
                tree,
                plan(
                    edits=[
                        edit(r"\begin{tikzpicture}", r"\begin{verbatim}", occurrence=1),
                        edit(r"\end{tikzpicture}", r"\end{verbatim}", occurrence=2),
                    ]
                ),
            )

    def test_normalization_maps_copied_text_to_original_bytes(self):
        raw = TEX.replace(b"Body.", "A café costs $n units.".encode())
        n = self.apply(
            SourceTree("tex", {"main.tex": raw}),
            plan(edits=[edit("A café costs $n units.", "A café costs $n$ units.")]),
        )
        text = n.tree.files["main.tex"].decode()
        spans = n.provenance["source_projections"]["main.tex"]["segments"]
        copied = []
        for span in spans:
            a, b = span["char_start"], span["char_end"]
            if span["original_bytes"] is not None:
                low, high = span["original_bytes"]
                self.assertEqual(text[a:b], raw[low:high].decode())
                copied.append(text[a:b])
        self.assertIn("A café costs $n", "".join(copied))
        self.assertEqual(spans[-1]["char_end"], len(text))

    def test_harvmac_conversion_preserves_formula_arguments_and_comment_bytes(self):
        raw = (
            r"\input harvmac"
            + "\n"
            + r"\Title{Paper}{Author}"
            + "\n"
            + r"\newsec{First}"
            + "\n"
            + r"\eqn\ifa{x^2 + \alpha = 0}"
            + "\n"
            + r"See \ifa. % \eqn\ghost{must remain a comment}"
            + "\n\\end\n"
        ).encode()
        tree = SourceTree("tex", {"main.tex": raw})
        n = self.apply(tree, {**plan(), "dialect": "harvmac"})
        self.assertIn(b"x^2 + \\alpha = 0", n.tree.files["main.tex"])
        self.assertIn(
            b"% \\eqn\\ghost{must remain a comment}", n.tree.files["main.tex"]
        )
        self.assertIn(b"\\ref{ifa}", n.tree.files["main.tex"])
        self.assertEqual(tree.files["main.tex"], raw)
        self.assertTrue(
            parse_prepared(prepare_input(n.tree), n.tree).coverage["complete"]
        )

    def test_scientific_condition_cannot_be_chosen_as_a_compilation_view(self):
        tree = SourceTree(
            "tex",
            {
                "main.tex": TEX.replace(
                    b"Body.", b"\\ifdefined\\result\nA.\\else B.\\fi"
                )
            },
        )
        with self.assertRaisesRegex(ValueError, "compilation-wrapper"):
            self.apply(tree, plan(edits=[edit("\\ifdefined\\result", "\\iftrue")]))

    def test_legacy_tar_footer_repair_keeps_member_bytes_and_strict_default(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo("main.tex")
            info.size = len(TEX)
            tar.addfile(info, io.BytesIO(TEX))
        short = buffer.getvalue()[:1024]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.tar"
            path.write_bytes(short)
            with self.assertRaises(PackageError):
                load_for_preparation(path)
            tree, record = load_for_preparation(path, repair_legacy_tar=True)
            self.assertEqual(tree.files["main.tex"], TEX)
            self.assertEqual(path.read_bytes(), short)
            self.assertEqual(record[0]["appended_bytes"], 1024)

    def test_ready_input_skips_ai_and_invalid_plan_keeps_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src = root / "paper.tex"
            out = root / "out"
            src.write_bytes(TEX)
            with patch(
                "qecgraph.llm.client.LLMClient",
                side_effect=AssertionError("unneeded AI"),
            ):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main([str(src), "--out", str(out)]), 0)
            old = {p.name: p.read_bytes() for p in out.iterdir()}
            src.write_bytes(TEX.replace(b"Body.", b"\\begin{proof}Body."))
            provider = Provider(
                {
                    **plan(),
                    "status": "needs_review",
                    "unresolved": ["Cannot safely repair."],
                }
            )
            c = LLMClient(config(max_input_chars=200000), provider=provider)
            with (
                patch("qecgraph.llm.config.load_ai_config", return_value=c.config),
                patch("qecgraph.llm.client.LLMClient", return_value=c),
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        main(
                            [
                                str(src),
                                "--out",
                                str(out),
                                "--ai-prepare",
                                "--ai-config-root",
                                str(root),
                            ]
                        ),
                        1,
                    )
            self.assertEqual(old, {p.name: p.read_bytes() for p in out.iterdir()})
