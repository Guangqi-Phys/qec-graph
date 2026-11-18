"""Offline acceptance must be derived from retained bundles, never summary claims."""

from copy import deepcopy
import json
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.preparation.acceptance import (
    check_cases,
    counts,
    generate_report,
    replay_metadata,
)
from qecgraph.preparation.build import Build
from qecgraph.preparation.contract import digest, read_material
from qecgraph.preparation.pipeline import prepare_material


class PreparationAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "main.tex"
        self.source.write_bytes(
            rb"\documentclass{article}\begin{document}\section{Scope}Body.\end{document}"
        )
        self.replay = self.root / "replay"
        self.replay.mkdir()
        output = self.replay / "synthetic"
        prepare_material(self.source, output, compiler=self.compiler)
        material = read_material(output)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "samples": [
                        {
                            "arxiv_id": "synthetic",
                            "package": "main.tex",
                            "sha256": digest(self.source.read_bytes()),
                            "format": "tex",
                        }
                    ]
                }
            )
        )
        self.cases = self.root / "cases.json"
        self.cases.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "paper": "synthetic",
                            "file": "main.tex",
                            "kind": "macro",
                            "name": "section",
                            "source_sha256": digest(self.source.read_bytes()),
                            "anchor": r"\section{Scope}",
                        }
                    ]
                }
            )
        )
        row = {
            "paper": "synthetic",
            "material": output.name,
            "material_manifest_sha256": digest((output / "manifest.json").read_bytes()),
            "exit": 0,
            "package_sha256": digest(self.source.read_bytes()),
            "status": material["manifest"]["status"],
            "stages": material["manifest"]["stages"],
            "source_fidelity": material["validation"]["source_fidelity"],
            "nodes": material["validation"]["nodes"],
            "reasons": material["coverage"]["reasons"],
            "normalization": {
                k: material["normalization"].get(k)
                for k in (
                    "complete",
                    "native_compile",
                    "syntax_parse",
                    "pdf_text",
                    "transformations",
                )
            },
        }
        self.results = {
            "manifest_sha256": digest(self.manifest.read_bytes()),
            "model_calls": 0,
            "rows": [row],
            "counts": counts([row]),
            "run_metadata": replay_metadata(
                ["synthetic offline fixture"], cases=self.cases
            ),
            "syntax_probes": check_cases(
                self.replay, json.loads(self.cases.read_text())["cases"], rows=[row]
            ),
        }
        self.save()

    @staticmethod
    def compiler(tree, entry, root, **kwargs):
        tree.materialize(root / "project")
        return Build(entry, "pdflatex", root, success=True, inputs=[entry])

    def save(self):
        (self.replay / "results.json").write_text(json.dumps(self.results))

    def report(self, **kwargs):
        return generate_report(
            self.manifest, self.replay, cases_path=self.cases, **kwargs
        )

    def test_report_reopens_bundles_and_rechecks_original_source_probes(self):
        result = self.report()
        self.assertEqual(result["original_bundles_validated"], 1)
        self.assertEqual(result["syntax_probes"]["passed"], 1)
        self.assertEqual(result["rows"][0]["nodes"], self.results["rows"][0]["nodes"])
        self.assertFalse(result["scientific_acceptance"]["accepted"])

    def test_failed_retry_is_reported_from_the_attempt_receipt(self):
        from tools.reproduce_preparation import _record_attempt

        def failed_compiler(tree, entry, root, **kwargs):
            return Build(entry, "pdflatex", root, success=False)

        output = self.replay / "synthetic"
        previous = (output / "manifest.json").read_bytes()
        receipt = prepare_material(self.source, output, compiler=failed_compiler)
        self.assertTrue(receipt["previous_retained"])
        row = {
            "paper": "synthetic",
            "package_sha256": digest(self.source.read_bytes()),
            "material": None,
        }
        command = CompletedProcess([], 2, json.dumps(receipt).encode(), b"")
        _record_attempt(output, command, row)
        self.assertEqual(
            (row["material"], row["status"]), ("synthetic.attempt", "partial")
        )
        self.assertEqual((output / "manifest.json").read_bytes(), previous)
        self.results["rows"] = [row]
        self.results["counts"] = counts([row])
        self.results["syntax_probes"] = check_cases(
            self.replay, json.loads(self.cases.read_bytes())["cases"], rows=[row]
        )
        self.save()
        self.assertEqual(self.report()["counts"]["ready"], 0)
        self.assertEqual(self.report()["syntax_probes"]["passed"], 0)

        # A subsequent attempt may replace the partial directory. The old replay
        # still names a specific publication and should detect the replacement.
        def later_compiler(tree, entry, root, **kwargs):
            raise ValueError("A different preparation attempt failed")

        prepare_material(self.source, output, compiler=later_compiler)
        with self.assertRaisesRegex(ValueError, "published attempt"):
            self.report()

    def test_inflated_counts_and_row_claims_are_rejected(self):
        original = deepcopy(self.results)
        self.results["counts"]["ready"] += 1
        self.save()
        with self.assertRaisesRegex(ValueError, "counts"):
            self.report()
        self.results = original
        self.results["rows"][0]["nodes"] += 1
        self.save()
        with self.assertRaisesRegex(ValueError, "row does not match"):
            self.report()

    def test_changed_package_bytes_and_stale_code_snapshot_are_rejected(self):
        raw = self.source.read_bytes()
        self.source.write_bytes(raw + b"% changed")
        with self.assertRaisesRegex(ValueError, "package bytes changed"):
            self.report()
        self.source.write_bytes(raw)
        self.results["run_metadata"]["execution_sources"] = {}
        self.save()
        with self.assertRaisesRegex(ValueError, "code snapshot"):
            self.report()

    def test_false_probe_pass_and_incomplete_replay_are_rejected(self):
        original = deepcopy(self.results)
        self.results["syntax_probes"]["passed"] = 100
        self.save()
        with self.assertRaisesRegex(ValueError, "probe claims"):
            self.report()
        self.results = original
        self.results["rows"] = []
        self.save()
        with self.assertRaisesRegex(ValueError, "every frozen corpus input"):
            self.report()

    def test_comparison_rejects_different_corpus(self):
        baseline = self.report()
        baseline["input"]["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "corpus identities differ"):
            self.report(baseline=baseline)

    def test_retained_material_comparison_detects_changes_beyond_counts(self):
        from tools.compare_preparation import compare_replays
        from tools.reproduce_preparation import _record_attempt
        import shutil

        copied = self.root / "copied"
        shutil.copytree(self.replay, copied)
        matching = compare_replays(self.replay, copied)
        self.assertEqual(matching["matched"], 1)

        def compiler(tree, entry, root, **kwargs):
            return Build(entry, "pdflatex", root, success=False)

        output = copied / "synthetic"
        receipt = prepare_material(self.source, output, compiler=compiler)
        with self.assertRaisesRegex(ValueError, "published attempt"):
            mismatched = deepcopy(self.results)
            mismatched["rows"][0].update(
                material=Path(receipt["out"]).name, status="partial", exit=2
            )
            (copied / "results.json").write_text(json.dumps(mismatched))
            compare_replays(self.replay, copied)
        results = deepcopy(self.results)
        _record_attempt(
            output,
            CompletedProcess([], 2, json.dumps(receipt).encode(), b""),
            results["rows"][0],
        )
        (copied / "results.json").write_text(json.dumps(results))
        changed = compare_replays(self.replay, copied)
        self.assertEqual(changed["matched"], 0)
        self.assertIn("stable_artifacts", changed["rows"][0]["differences"])
        self.assertIn("content", changed["rows"][0]["differences"])

    def test_retained_material_comparison_rejects_a_different_corpus(self):
        from tools.compare_preparation import compare_replays
        import shutil

        copied = self.root / "copied"
        shutil.copytree(self.replay, copied)
        results = deepcopy(self.results)
        results["manifest_sha256"] = "0" * 64
        (copied / "results.json").write_text(json.dumps(results))
        with self.assertRaisesRegex(ValueError, "same frozen corpus"):
            compare_replays(self.replay, copied)

    def test_probe_check_reuses_the_verified_material_read(self):
        with patch(
            "qecgraph.preparation.acceptance.read_material", wraps=read_material
        ) as read:
            self.report()
        self.assertEqual(read.call_count, 1)
