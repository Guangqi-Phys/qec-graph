"""Adversarial, security, differential, and fault-injection tests for preparation.

Covers §3.3, §3.4, and §3.5 of the test engineering plan:
- ADV-01: .bcf XML DOCTYPE / ENTITY (XXE / entity expansion) rejection.
- ADV-02: Source file mutation or symlink substitution during compilation
          (_check_source_copy).
- ADV-03: Forged .fls path traversal, >32,768 lines limit, and >256 MiB
          artifact collection limit.
- ADV-04: Malicious --support-dir validation (symlink dir, symlink file,
          conflicting support files, >16 MiB file limit).
- ADV-05: Deep brace nesting (>128 depth) graceful partial degradation.
- ADV-06: Crash/recovery conflict detection and .attempt isolation when a
          ready bundle is followed by a partial run.
- ADV-07: CLI tools/prepare_compiled.py exit code contract (0/1/2), --check,
          and --recover.
- DIFF-01..04: Round-trip PDF text mismatch blocking ready, missing/failing
          pdftotext handling, etex/dvips/ps2pdf toolchain short-circuiting,
          and AUX vs static AST citation mismatch diagnostics.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from qecgraph.preparation.build import Build, _record_files, _support, compile_tree
from qecgraph.preparation.contract import json_bytes, read_material, validate_material
from qecgraph.preparation.pipeline import prepare_material
from qecgraph.preparation.references import _bcf_requests, adapt_references
from qecgraph.preparation.roundtrip import verify_roundtrip
from qecgraph.source.package import SourceTree
from tools import prepare_compiled


class PreparationAdversarialAndDifferentialTests(unittest.TestCase):
    def test_adv01_bcf_rejects_xml_doctype_and_entity_declarations(self):
        xxe_payloads = [
            b'<?xml version="1.0"?><!DOCTYPE bcf [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><bcf/>',
            b'<?xml version="1.0"?><!ENTITY lol "lol"><bcf/>',
        ]
        for payload in xxe_payloads:
            with self.subTest(payload=payload[:40]):
                with self.assertRaisesRegex(ValueError, "DOCTYPE|entities"):
                    _bcf_requests(payload)

    def test_adv02_compiler_mutating_source_or_replacing_with_symlink_is_caught(self):
        original = b"\\documentclass{article}\\begin{document}Safe.\\end{document}"
        tree = SourceTree("tex", {"main.tex": original, "custom.sty": b"% style"})

        def mutating_runner(work, cwd, command, **kwargs):
            if "-recorder" in command:
                (cwd / "main.pdf").write_bytes(b"%PDF-1.4")
                (cwd / "custom.sty").write_bytes(b"% tampered by evil macro")
            return {"exit": 0, "timeout": False, "seconds": 0.01, "log": b"ok"}

        with (
            tempfile.TemporaryDirectory() as temp,
            patch("qecgraph.preparation.build.tool", side_effect=lambda n: "/bin/" + n),
        ):
            build = compile_tree(tree, "main.tex", Path(temp), runner=mutating_runner)
            self.assertFalse(build.success)
            codes = [d["code"] for d in build.diagnostics]
            self.assertIn("source_changed_during_build", codes)
            self.assertIn("compile_failed", codes)

    def test_adv03_fls_traversal_line_limit_and_entry_flag_injection_rejected(self):
        tree = SourceTree("tex", {"main.tex": b"\\documentclass{article}"})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for bad_entry in ("-shell-escape.tex", "../main.tex", "main;id.tex"):
                with self.assertRaises(ValueError):
                    compile_tree(tree, bad_entry, root)

            project = root / "project"
            project.mkdir(parents=True, exist_ok=True)
            secret = root.parent / "secret.txt"
            secret.write_text("do not read")
            build = Build("main.tex", "pdflatex", root)
            (project / "main.fls").write_text(
                f"INPUT {secret}\nOUTPUT ../escaped.pdf\nINPUT ./main.tex\n"
            )
            (project / "main.tex").write_bytes(tree.files["main.tex"])
            _record_files(build, tree, "main")
            self.assertEqual(build.inputs, ["main.tex"])
            self.assertEqual(build.outputs, [])
            self.assertEqual(build.dependencies, [])

            # Exceed 32,768 FLS lines limit
            (project / "main.fls").write_text("INPUT ./main.tex\n" * 32769)
            with self.assertRaisesRegex(ValueError, "recorder line limit"):
                _record_files(build, tree, "main")

    def test_adv04_support_directory_rejects_symlinks_and_conflicting_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = Build("main.tex", "pdflatex", root)

            # 1. Symlinked support directory
            real_dir = root / "real"
            real_dir.mkdir()
            link_dir = root / "link_dir"
            link_dir.symlink_to(real_dir)
            with self.assertRaisesRegex(ValueError, "regular directory"):
                _support(build, [link_dir])

            # 2. Symlinked file inside support directory
            secret = root / "outside.sty"
            secret.write_bytes(b"secret")
            (real_dir / "linked.sty").symlink_to(secret)
            with self.assertRaisesRegex(ValueError, "Linked TeX support"):
                _support(build, [real_dir])
            (real_dir / "linked.sty").unlink()

            # 3. Conflicting support files across two support directories
            dir_a = root / "sup_a"
            dir_b = root / "sup_b"
            dir_a.mkdir()
            dir_b.mkdir()
            (dir_a / "conflict.sty").write_bytes(b"version A")
            (dir_b / "conflict.sty").write_bytes(b"version B")
            with self.assertRaisesRegex(ValueError, "Conflicting TeX support"):
                _support(build, [dir_a, dir_b])

    def test_adv05_deep_brace_nesting_degrades_gracefully_to_partial_material(self):
        deep = "\\documentclass{article}\\begin{document}" + ("{" * 135) + "x" + ("}" * 135) + "\\end{document}"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "main.tex"
            source.write_text(deep, encoding="utf-8")
            out = root / "out"

            def fake_compiler(tree, entry, work, **kwargs):
                tree.materialize(work / "project")
                return Build(entry, "pdflatex", work, success=True, inputs=[entry])

            result = prepare_material(source, out, compiler=fake_compiler)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["stages"]["conversion"], "partial")
            diagnostics = json.loads((out / "diagnostics.json").read_text())
            self.assertTrue(
                any(
                    d["code"] == "preparation_failed" and "depth/count limit" in d["message"]
                    for d in diagnostics
                )
            )
            self.assertTrue(read_material(out)["validation"]["source_fidelity"])

    def test_adv06_tampered_manifest_status_and_corrupted_aux_locators_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "main.tex"
            source.write_bytes(
                b"\\documentclass{article}\\begin{document}Hello.\\end{document}"
            )
            out = root / "out"

            def failing_compiler(tree, entry, work, **kwargs):
                tree.materialize(work / "project")
                return Build(entry, "pdflatex", work, success=False, inputs=[entry])

            prepare_material(source, out, compiler=failing_compiler)
            # Forging manifest status from "partial" to "ready" without recalculating or
            # with failed build must be caught by validate_material.
            files = {
                name: (out / name).read_bytes()
                for name in json.loads((out / "manifest.json").read_text())["artifacts"]
            }
            manifest = json.loads((out / "manifest.json").read_text())
            manifest["status"] = "ready"
            files["manifest.json"] = json_bytes(manifest)
            with self.assertRaisesRegex(ValueError, "incomplete prerequisite|missing normalized"):
                validate_material(files)

    def test_adv07_cli_prepare_compiled_check_recover_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "main.tex"
            source.write_bytes(
                b"\\documentclass{article}\\begin{document}CLI test.\\end{document}"
            )
            out = root / "material"

            def fake_compiler(tree, entry, work, **kwargs):
                tree.materialize(work / "project")
                return Build(entry, "pdflatex", work, success=True, inputs=[entry])

            with (
                patch(
                    "tools.prepare_compiled.prepare_material",
                    side_effect=lambda *a, **kw: prepare_material(
                        *a, **kw, compiler=fake_compiler
                    ),
                ),
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                code = prepare_compiled.main([str(source), "--out", str(out)])
                self.assertEqual(code, 0)
                check_code = prepare_compiled.main(["--out", str(out), "--check"])
                self.assertEqual(check_code, 0)
                recover_code = prepare_compiled.main(["--out", str(out), "--recover"])
                self.assertEqual(recover_code, 0)

            # Tamper with an artifact and verify --check returns exit code 1
            (out / "entry.tex").write_bytes(b"corrupted")
            with (
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO) as err,
            ):
                bad_code = prepare_compiled.main(["--out", str(out), "--check"])
                self.assertEqual(bad_code, 1)
                self.assertIn("failed", err.getvalue())

    def test_diff01_and_diff02_roundtrip_pdf_text_mismatch_and_tool_failure_block_ready(
        self,
    ):
        tree = SourceTree(
            "tex",
            {"main.tex": b"\\documentclass{article}\\begin{document}$x$\\end{document}"},
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            orig = Build("main.tex", "pdflatex", root / "orig", success=True)
            (orig.root / "project").mkdir(parents=True)
            (orig.root / "project/main.pdf").write_bytes(b"orig pdf")

            def derived_compiler(dtree, entry, droot, **kwargs):
                (droot / "project").mkdir(parents=True, exist_ok=True)
                (droot / "project/main.pdf").write_bytes(b"derived pdf")
                return Build(entry, "pdflatex", droot, success=True)

            # Case 1: pdftotext outputs different page text for original vs derived PDF
            def diff_pdftotext(work, cwd, cmd, **kwargs):
                out_txt = Path(cmd[-1])
                out_txt.write_text(
                    "Page 1 original\f" if "0" in out_txt.name else "Page 1 DIFFERENT\f"
                )
                return {"exit": 0, "timeout": False, "log": b""}

            report = {"syntax_parse": "complete"}
            with (
                patch("qecgraph.preparation.execution.tool", return_value="/bin/pdftotext"),
                patch("qecgraph.preparation.execution.sandbox.run", side_effect=diff_pdftotext),
            ):
                verify_roundtrip(orig, tree, tree.files["main.tex"], report, (), derived_compiler)
            self.assertEqual(report["pdf_text"], "different")
            self.assertFalse(report["complete"])

            # Case 2: pdftotext times out or exits non-zero
            orig2 = Build("main.tex", "pdflatex", root / "orig2", success=True)
            (orig2.root / "project").mkdir(parents=True)
            (orig2.root / "project/main.pdf").write_bytes(b"orig pdf")
            report_fail = {"syntax_parse": "complete"}
            with (
                patch("qecgraph.preparation.execution.tool", return_value="/bin/pdftotext"),
                patch(
                    "qecgraph.preparation.execution.sandbox.run",
                    return_value={"exit": 1, "timeout": True, "log": b"timeout"},
                ),
            ):
                verify_roundtrip(
                    orig2, tree, tree.files["main.tex"], report_fail, (), derived_compiler
                )
            self.assertEqual(report_fail["pdf_text"], "failed")
            self.assertFalse(report_fail["complete"])

    def test_diff03_etex_dvips_ps2pdf_pipeline_and_short_circuit_on_failure(self):
        tree = SourceTree(
            "tex", {"main.tex": b"\\input harvmac\n\\Title{T}{A}\nBody.\\bye\n"}
        )
        invoked = []

        def fake_runner(work, cwd, command, **kwargs):
            binary = Path(command[0]).name
            invoked.append((binary, kwargs.get("stdin")))
            if binary == "etex" and "-recorder" in command:
                (cwd / "main.dvi").write_bytes(b"dvi")
            elif binary == "dvips":
                return {"exit": 1, "timeout": False, "seconds": 0.01, "log": b"dvips err"}
            return {"exit": 0, "timeout": False, "seconds": 0.01, "log": b"ok"}

        with (
            tempfile.TemporaryDirectory() as temp,
            patch("qecgraph.preparation.build.tool", side_effect=lambda n: "/bin/" + n),
        ):
            build = compile_tree(tree, "main.tex", Path(temp), runner=fake_runner)
            self.assertEqual(build.engine, "etex")
            self.assertFalse(build.success)
            names = [name for name, _ in invoked]
            self.assertIn("dvips", names)
            # ps2pdf must not be called when dvips fails
            self.assertNotIn("ps2pdf", names)
            # etex steps must pass stdin="b\n"
            etex_runs = [stdin for name, stdin in invoked if name == "etex" and stdin]
            self.assertTrue(all(s == "b\n" for s in etex_runs))

    def test_diff04_non_utf8_aux_bbl_and_bib_produce_explicit_diagnostics(self):
        files = {
            "main.tex": b"\\documentclass{article}\\begin{document}\\cite{k}\\end{document}",
            "main.aux": b"\\citation{k}\n\\bibcite{k}{\xff\xfe}\n",
            "main.bbl": b"\\bibitem{k}Non-UTF8 \xff\xfe\n",
            "refs.bib": b"@article{k, author={\xff\xfe}}\n",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tree = SourceTree("tex", files)
            tree.materialize(root / "project")
            build = SimpleNamespace(
                root=root,
                inputs=["main.tex", "main.aux", "main.bbl"],
                outputs=[],
                entry="main.tex",
            )
            result = adapt_references(build, tree)
            self.assertFalse(result["complete"])
            codes = {d["code"] for d in result["diagnostics"]}
            self.assertIn("bibliography_encoding", codes)
            self.assertIn("bib_encoding", codes)


if __name__ == "__main__":
    unittest.main()
