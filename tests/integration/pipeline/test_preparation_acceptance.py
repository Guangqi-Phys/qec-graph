"""Offline acceptance must be derived from retained bundles, never summary claims."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

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
                self.replay, json.loads(self.cases.read_text())["cases"]
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
