from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.llm.client import LLMClient
from qecgraph.llm.prepared import run_semantics, verify_semantics
from qecgraph.llm.providers.base import Completion
from qecgraph.preparation.artifacts import digest, json_bytes
from qecgraph.preparation.execution import Build
from qecgraph.preparation.pipeline import prepare_material
from qecgraph.prepared_extraction import PreparedSource, extract_source
from tests.unit.domain.test_ai_client import FakeProvider, config
from tools.extract_prepared import main


class RecordingProvider(FakeProvider):
    def complete(self, messages, **kwargs):
        self.evidence = messages[1].content
        return super().complete(messages, **kwargs)


class PreparedExtractionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        sources = self.root / "sources"
        sources.mkdir()
        self.main = (
            "\\documentclass{article}\n\\title{Source α}\\author{Ada Example}\n"
            "\\newtheorem{lemma}{Lemma}\n\\begin{document}\n\\section{Scope}\n"
            "Before input \\input{body} after input.\n\n"
            "% Excluded source comment.\n"
            "\\if 0 a\nInactive author passage.\n\\fi\n"
            "\\label{key}One.\\label{key}Two.\\ref{key}\n"
            "\\section{Other}Outside authored section.\n\\end{document}\n"
        )
        self.body = (
            "inside input.\n\n\\begin{lemma}A statement with $[[7,1,3]]$.\\end{lemma}\n"
            "\\begin{figure}\\caption{Authored caption.}\\end{figure}\n"
            "\\begin{tabular}{cc}Header & Value\\\\ Item & 3\\end{tabular}\n"
        )
        (sources / "main.tex").write_text(self.main)
        (sources / "body.tex").write_text(self.body)
        self.material = self.root / "material"
        prepare_material(
            sources, self.material, entry="main.tex", compiler=self.compile
        )

    @staticmethod
    def compile(tree, entry, root, **kwargs):
        tree.materialize(root / "project")
        return Build(entry, "pdflatex", root, success=True, inputs=list(tree.files))

    def test_extracts_program_items_and_preserves_all_reference_candidates(self):
        source = PreparedSource(self.material)
        result = extract_source(source)
        self.assertEqual(result["input"]["status"], "ready")
        self.assertEqual(result["semantic"], {})
        extracted = result["source"]
        self.assertEqual(
            extracted["cross_references"], source.document["cross_references"]
        )
        target = extracted["cross_references"][0]["targets"][0]
        self.assertEqual((target["status"], len(target["nodes"])), ("ambiguous", 2))
        self.assertEqual(extracted["bibliography"], source.material["references"])

        units = {row["kind"]: row for row in extracted["units"]}
        self.assertIn("Source α", units["title"]["latex"])
        self.assertIn("[[7,1,3]]", units["formula"]["latex"])
        self.assertIn("Value", str(units["table"]["data"]["rows"]))
        self.assertIn("Authored caption.", units["caption"]["latex"])
        self.assertEqual(
            units["code_parameters_mention"]["data"]["status"], "candidate"
        )
        self.assertEqual(units["code_parameters_mention"]["data"]["values"], [7, 1, 3])
        self.assertEqual(units["statement"]["source_spans"][0]["path"], "body.tex")
        for row in extracted["units"]:
            start, end = row["entry_range"]
            self.assertEqual(row["latex"], source.text[start:end])
            self.assertEqual(row["source_spans"], source.spans(start, end))

    def test_entry_ranges_resolve_multiple_original_files(self):
        source = PreparedSource(self.material)
        start = source.text.index("Before input")
        end = source.text.index("inside input") + len("inside input")
        spans = source.spans(start, end)
        self.assertEqual([span["path"] for span in spans], ["main.tex", "body.tex"])
        parts = []
        for span in spans:
            file = (self.material / "sources" / span["path"]).read_bytes()
            self.assertEqual(span["sha256"], digest(file))
            first, last = span["bytes"]
            parts.append(file[first:last].decode())
        self.assertEqual("".join(parts), source.text[start:end])

    def test_cli_verifies_saved_output_and_rejects_writes_into_material(self):
        out = self.root / "extraction.json"
        args = [str(self.material), "--out", str(out)]
        original = (self.material / "manifest.json").read_bytes()
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(args), 0)
            self.assertEqual(main([*args, "--check"]), 0)
            out.write_bytes(json_bytes({}))
            self.assertEqual(main([*args, "--check"]), 1)
            self.assertEqual(
                main([str(self.material), "--out", str(self.material / "extra")]), 1
            )
        self.assertEqual((self.material / "manifest.json").read_bytes(), original)
        self.assertFalse((self.material / "extra").exists())

    def test_semantic_cli_uses_exact_original_evidence_and_checks_offline(self):
        source = PreparedSource(self.material)
        quote = "Authored caption."
        citation = self.citation(source, quote)
        response = {
            "items": [
                {
                    "category": "side_result",
                    "statement": quote,
                    "source_quote": quote,
                    "attribution": "author_explicit",
                    "source_refs": [citation],
                }
            ],
            "unresolved": [],
        }
        provider = RecordingProvider(Completion(json.dumps(response), "offline-model"))
        client = LLMClient(config(max_input_chars=30000), provider=provider)
        out = self.root / "extraction.json"
        args = [str(self.material), "--out", str(out)]
        section = source.document["outline"][0]["node"]
        with (
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
            patch("tools.extract_prepared.load_ai_config", return_value=client.config),
            patch("tools.extract_prepared.LLMClient", return_value=client),
        ):
            self.assertEqual(
                main(
                    [
                        *args,
                        "--skill",
                        "extract_thoughts",
                        "--workspace",
                        str(self.root),
                        "--section",
                        section,
                    ]
                ),
                0,
            )
            self.assertEqual(main([*args, "--check"]), 0)
        self.assertEqual(provider.calls, 1)
        for excluded in (
            "Excluded source comment.",
            "Inactive author passage.",
            "Outside authored section.",
        ):
            self.assertNotIn(excluded, provider.evidence)
        result = json.loads(out.read_bytes())
        task = result["semantic"]["extract_thoughts"]
        self.assertEqual(task["proposal"]["review_status"], "proposed")
        locators = task["references"][citation]
        self.assertEqual({span["path"] for span in locators}, {"body.tex"})
        locators[0]["bytes"][0] += 1
        with self.assertRaisesRegex(ValueError, "citations differ"):
            verify_semantics(source, result)

    def test_semantic_permission_budget_and_out_of_scope_quotation(self):
        source = PreparedSource(self.material)
        result = extract_source(source)
        names = ["extract_theorems"]
        with self.assertRaisesRegex(ValueError, "source upload"):
            run_semantics(
                source,
                result,
                LLMClient(config(allow_source_upload=False), provider=FakeProvider()),
                names,
            )
        limited = FakeProvider()
        task = run_semantics(
            source,
            result,
            LLMClient(config(max_input_chars=10), provider=limited),
            names,
        )
        self.assertEqual(task[names[0]]["status"], "budget_exceeded")
        self.assertEqual(limited.calls, 0)
        quote = "Outside authored section."
        raw = json.dumps(
            {
                "items": [
                    {
                        "label": "bad",
                        "statement": quote,
                        "hypotheses": [],
                        "source_refs": [self.citation(source, quote)],
                    }
                ],
                "unresolved": [],
            }
        )
        invalid = FakeProvider(
            Completion(raw, "offline-model"), Completion(raw, "offline-model")
        )
        task = run_semantics(
            source,
            result,
            LLMClient(config(), provider=invalid),
            names,
            section=source.document["outline"][0]["node"],
        )[names[0]]
        self.assertEqual(task["status"], "failed")
        self.assertNotIn("proposal", task)
        self.assertEqual(invalid.calls, 2)

    def test_only_current_material_version_is_accepted(self):
        path = self.material / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["rule_version"] = "compile-prepare-v19"
        path.write_bytes(json_bytes(manifest))
        with self.assertRaisesRegex(ValueError, "requires a compile-prepare-v20"):
            PreparedSource(self.material)

    def test_data_conditions_do_not_supply_citation_locators(self):
        source = PreparedSource(self.material)
        result = extract_source(source)
        citation = self.citation(source, "A statement with")
        raw = json.dumps(
            {
                "items": [
                    {
                        "metric": "reported distance",
                        "value": 3,
                        "source_refs": [citation],
                        "conditions": {"source_refs": ["entry.tex:99999"]},
                    }
                ],
                "unresolved": [],
            }
        )
        client = LLMClient(
            config(max_input_chars=30000),
            provider=FakeProvider(Completion(raw, "offline-model")),
        )
        result["semantic"] = run_semantics(source, result, client, ["extract_data"])
        task = result["semantic"]["extract_data"]
        self.assertEqual(task["status"], "proposed")
        self.assertEqual(set(task["references"]), {citation})
        verify_semantics(source, result)

    @staticmethod
    def citation(source, text):
        line = source.text.count("\n", 0, source.text.index(text)) + 1
        return f"entry.tex:{line}"
