"""Integration checks for the public splitter and its shared graph output."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from qecgraph import split_project
from qecgraph.cli import main as graph_main
from qecgraph.query import context, dependencies, show
from qecgraph.splitter import main as standalone_main
from qecgraph.store import load_graph, validate_snapshot


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEMO_SOURCE = PACKAGE_ROOT / "examples" / "paper"


def directory_hashes(path: Path) -> dict[str, str]:
    return {
        item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in path.rglob("*") if item.is_file()
    }


class SplitterIntegrationTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory(prefix="qecgraph-split-test-")
        self.addCleanup(workspace.cleanup)
        self.work = Path(workspace.name)
        self.paper = self.work / "paper"
        self.store = self.work / "split-output"
        self.entry = self.paper / "main.tex"

    def demo(self):
        shutil.copytree(DEMO_SOURCE, self.paper)

    def split(self, **kwargs):
        return split_project(self.entry, "split-fixture", self.store, self.paper, **kwargs)

    def invoke(self, main, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def arguments(self):
        return [str(self.entry), "--project-id", "split-fixture", "--out", str(self.store),
                "--project-root", str(self.paper)]

    def test_inventory_points_to_real_typed_fragments_and_exact_original_sources(self):
        self.demo()
        originals = {item.relative_to(self.paper).as_posix(): item.read_bytes()
                     for item in self.paper.rglob("*.tex")}
        result = self.split()
        categories = result["fragments_by_kind"]
        expected = {"section": 3, "definition": 2, "lemma": 1, "theorem": 2,
                    "proof": 3, "equation": 5, "table": 1, "figure": 1,
                    "remark": 1, "example": 1}
        for kind, count in expected.items():
            with self.subTest(kind=kind):
                self.assertEqual(categories[kind]["count"], count)
                self.assertTrue(Path(categories[kind]["directory"]).is_dir())
        self.assertEqual(result["fragment_count"], sum(c["count"] for c in categories.values()))
        for kind, category in categories.items():
            self.assertEqual(category["count"], len(category["fragments"]))
            for fragment in category["fragments"]:
                with self.subTest(fragment=fragment["id"]):
                    tex_path = Path(fragment["tex_file"])
                    record_path = Path(fragment["record_file"])
                    self.assertEqual(tex_path, Path(result["snapshot"]) / fragment["fragment_path"])
                    self.assertEqual(record_path, Path(result["snapshot"]) / fragment["record_path"])
                    node = json.loads(record_path.read_text(encoding="utf-8"))
                    self.assertEqual(node["id"], fragment["id"])
                    self.assertEqual(node["kind"], kind)
                    span = fragment["source"]
                    source = originals[span["path"]].decode("utf-8")
                    expected_bytes = source[span["char_start"]:span["char_end"]].encode("utf-8")
                    self.assertEqual(tex_path.read_bytes(), expected_bytes)
                    self.assertEqual(hashlib.sha256(expected_bytes).hexdigest(), fragment["content_sha256"])
        self.assertEqual({item["path"] for item in result["sources"]}, set(originals))
        for source in result["sources"]:
            self.assertEqual(Path(source["archived_file"]).read_bytes(), originals[source["path"]])
            self.assertEqual(source["sha256"], hashlib.sha256(originals[source["path"]]).hexdigest())
        self.assertTrue(validate_snapshot(Path(result["snapshot"]))["passed"])

    def test_split_output_reuses_graph_queries_and_keeps_data_as_source_claims(self):
        self.demo()
        result = self.split()
        graph, snapshot = load_graph(self.store)
        self.assertEqual(result["snapshot_id"], graph["snapshot_id"])
        self.assertEqual(snapshot, Path(result["snapshot"]))
        lemma = show(self.store, "lem:css-commutation")["node"]
        self.assertEqual(lemma["kind"], "lemma")
        self.assertTrue((snapshot / lemma["fragment_path"]).is_file())
        dep_result = dependencies(self.store, "lem:css-commutation")
        dep_labels = {label for node in dep_result["nodes"] for label in node["labels"]}
        self.assertIn("def:css", dep_labels)
        bundle = context(self.store, "thm:hgp-length")
        self.assertIn("proof:hgp-length", {label for node in bundle["nodes"] for label in node["labels"]})
        self.assertEqual(show(self.store, "tab:rep3")["node"]["kind"], "table")
        self.assertFalse(any(node["kind"] == "code_instance" for node in graph["nodes"]))
        self.assertFalse(any(node["verification_status"] == "verified" for node in graph["nodes"]))
        self.assertTrue(result["source_only"])
        self.assertEqual(result["fragment_semantics"]["mathematical_verification"], "not_performed")

    def test_environment_aliases_can_mix_with_literal_delimiters(self):
        self.paper.mkdir()
        equations = (
            r"\openEq\label{eq:open} x = 1 \end{equation}",
            r"\begin{equation}\label{eq:close} y = 2 \closeEq",
        )
        source = "\r\n".join((
            r"\newcommand{\openEq}{\begin{equation}}",
            r"\newcommand{\closeEq}[0]{\end{equation}}",
            r"\begin{proof} Unicode α",
            *equations,
            r"\end{proof}",
            r"\ifx\openEq\closeEq no expansion in a token comparison \fi",
            "",
        )).encode()
        self.entry.write_bytes(source)

        result = self.split()

        self.assertEqual(result["extraction_status"], "complete_for_supported_syntax")
        fragments = result["fragments_by_kind"]["equation"]["fragments"]
        self.assertEqual([item["labels"] for item in fragments], [["eq:open"], ["eq:close"]])
        for fragment, equation in zip(fragments, equations):
            span = fragment["source"]
            self.assertEqual(source.decode()[span["char_start"]:span["char_end"]], equation)
            self.assertEqual(Path(fragment["tex_file"]).read_bytes(), equation.encode())
        self.assertEqual(Path(result["sources"][0]["archived_file"]).read_bytes(), source)
        self.assertTrue(any(item["code"] == "conditionals_not_evaluated" for item in result["diagnostics"]))

    def test_included_supplement_uses_guard_declared_before_input(self):
        self.paper.mkdir()
        main = r"""\documentclass{article}
\begin{document}
\newcommand{\combined}{}
\input{supplement}
\section{After supplement}\label{sec:after}
\end{document}
"""
        supplement = r"""\ifdefined\combined
\else
\input{standalone-preamble}
\begin{document}
\section{Standalone only}\label{sec:standalone}
\fi
\section{Shared supplement}\label{sec:shared}
\ifdefined\combined
\else
\end{document}
\fi
"""
        self.entry.write_text(main, encoding="utf-8")
        (self.paper / "supplement.tex").write_text(supplement, encoding="utf-8")

        result = self.split()

        self.assertEqual(result["extraction_status"], "complete_for_supported_syntax")
        sections = {label: item["source"] for item in result["fragments_by_kind"]["section"]["fragments"]
                    for label in item["labels"]}
        self.assertEqual(set(sections), {"sec:shared", "sec:after"})
        self.assertEqual(sections["sec:shared"]["line_start"], 7)
        archived = {item["path"]: Path(item["archived_file"]).read_bytes() for item in result["sources"]}
        self.assertEqual(archived, {"main.tex": main.encode(), "supplement.tex": supplement.encode()})
        self.assertTrue(any(item["code"] == "conditional_branch_selected" for item in result["diagnostics"]))

        self.entry.write_text(main.replace(r"\newcommand{\combined}{}", ""), encoding="utf-8")
        unresolved = self.split()
        self.assertEqual(unresolved["extraction_status"], "partial")
        self.assertTrue(any(item["code"] == "missing_include" for item in unresolved["diagnostics"]))

    def test_repeated_split_reuses_the_snapshot_without_mutating_source_or_fragments(self):
        self.demo()
        original = directory_hashes(self.paper)
        first = self.split()
        snapshot = Path(first["snapshot"])
        archived = directory_hashes(snapshot)
        second = self.split()
        self.assertEqual(first, second)
        self.assertEqual(len(list((self.store / "snapshots").iterdir())), 1)
        self.assertEqual(directory_hashes(snapshot), archived)
        self.assertEqual(directory_hashes(self.paper), original)

    def test_foreign_output_directory_is_rejected_without_changing_its_contents(self):
        self.demo()
        self.store.mkdir()
        (self.store / "notes.txt").write_bytes(b"An unrelated user's file.\n")
        (self.store / "CURRENT.json").write_text('{"owner":"another-tool"}', encoding="utf-8")
        before = directory_hashes(self.store)
        code, stdout, stderr = self.invoke(graph_main, ["split", *self.arguments()])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("unrecognized nonempty directory", json.loads(stderr)["error"])
        self.assertEqual(directory_hashes(self.store), before)
        self.assertFalse((self.store / ".qecgraph-store.json").exists())

    def test_symlink_snapshot_directory_cannot_redirect_writes_to_an_external_directory(self):
        self.demo()
        external = self.work / "external"
        external.mkdir()
        (external / "sentinel.bin").write_bytes(b"\x00\xffmust stay unchanged")
        self.store.mkdir()
        (self.store / ".qecgraph-store.json").write_text('{"format":"qecgraph.store.v1"}', encoding="utf-8")
        try:
            (self.store / "snapshots").symlink_to(external, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Symlinks unavailable on this platform: {exc}")
        before = directory_hashes(external)
        with self.assertRaisesRegex(ValueError, "regular local directory"):
            self.split()
        self.assertEqual(directory_hashes(external), before)
        self.assertFalse((self.store / "CURRENT.json").exists())

    def test_partial_import_keeps_valid_fragments_and_both_entrypoints_return_two(self):
        self.paper.mkdir()
        source = (
            "% 中文 and CRLF are preserved.\r\n"
            "\\begin{lemma}\\label{lem:valid}A retained source statement.\\end{lemma}\r\n"
            "\\input{missing-chapter}\r\n"
        )
        self.entry.write_bytes(source.encode("utf-8"))
        code, stdout, stderr = self.invoke(graph_main, ["split", *self.arguments()])
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "")
        result = json.loads(stdout)
        self.assertEqual(result["extraction_status"], "partial")
        self.assertEqual(result["suggested_exit_code"], 2)
        self.assertEqual(result["fragments_by_kind"]["lemma"]["count"], 1)
        self.assertEqual(Path(result["sources"][0]["archived_file"]).read_bytes(), source.encode("utf-8"))
        self.assertTrue(any(item["code"] == "missing_include" for item in result["diagnostics"]))
        self.assertTrue(validate_snapshot(Path(result["snapshot"]))["passed"])
        alias_code, alias_stdout, alias_stderr = self.invoke(standalone_main, self.arguments())
        self.assertEqual(alias_code, 2)
        self.assertEqual(alias_stderr, "")
        self.assertEqual(json.loads(alias_stdout), result)

    def test_actual_module_entrypoints_produce_the_same_split_result(self):
        self.demo()
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
        commands = [
            [sys.executable, "-m", "qecgraph", "split", *self.arguments()],
            [sys.executable, "-m", "qecgraph.splitter", *self.arguments()],
        ]
        results = []
        for command in commands:
            process = subprocess.run(command, cwd=PACKAGE_ROOT, env=environment,
                                     capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stderr, "")
            results.append(json.loads(process.stdout))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["operation"], "split")

    def test_custom_environment_config_reaches_the_shared_parser(self):
        self.paper.mkdir()
        self.entry.write_text(
            "\\begin{myresult}\\label{lem:custom}A custom source block.\\end{myresult}\n",
            encoding="utf-8",
        )
        config = self.work / "parser.json"
        config.write_text('{"environment_map":{"myresult":"lemma"}}', encoding="utf-8")
        result = self.split(config_path=config)
        self.assertEqual(result["fragments_by_kind"]["lemma"]["count"], 1)
        fragment = result["fragments_by_kind"]["lemma"]["fragments"][0]
        self.assertEqual(fragment["labels"], ["lem:custom"])
        self.assertEqual(show(self.store, "lem:custom")["node"]["kind"], "lemma")


if __name__ == "__main__":
    unittest.main()
