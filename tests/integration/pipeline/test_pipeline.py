"""Semantic regression tests for source provenance and evidence-aware graph edges.

The tests use real LaTeX fixtures and isolated temporary stores. They do not run
TeX, a numerical QEC verifier, Lean, or a language model.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from qecgraph import query
from qecgraph.store import current_snapshot, ingest, load_graph, validate_snapshot


from tests.support import ROOT

PACKAGE_ROOT = ROOT
DEMO_SOURCE = PACKAGE_ROOT / "examples" / "paper"
EXPECTED_LABEL_KINDS = {
    "sec:foundations": "section",
    "sec:hgp": "section",
    "sec:literal-examples": "section",
    "def:gf2": "definition",
    "def:css": "definition",
    "lem:css-commutation": "lemma",
    "thm:hgp-css": "theorem",
    "thm:hgp-length": "theorem",
    "proof:css-commutation": "proof",
    "proof:hgp-css": "proof",
    "proof:hgp-length": "proof",
    "eq:css-commutation": "equation",
    "eq:hgp-checks": "equation",
    "eq:hgp-commutation": "equation",
    "eq:repetition-seed": "equation",
    "tab:rep3": "table",
    "fig:repetition-seed": "figure",
    "rem:source-only": "remark",
    "ex:rep3-parameters": "example",
}


class PipelineSemanticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="qecgraph-semantic-test-")
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.paper = self.work / "paper"
        self.store = self.work / "graph"
        self.entry = self.paper / "main.tex"

    def _demo(self):
        shutil.copytree(DEMO_SOURCE, self.paper)
        return self._ingest()

    def _write_project(self, source, extra_files=None):
        self.paper.mkdir(parents=True, exist_ok=True)
        self.entry.write_bytes(source.encode("utf-8"))
        for relative, text in (extra_files or {}).items():
            path = self.paper / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        return self._ingest()

    def _ingest(self, annotations_path=None):
        result = ingest(
            self.entry,
            project_id="fixture",
            out=self.store,
            project_root=self.paper,
            annotations_path=annotations_path,
        )
        graph, snapshot = load_graph(self.store)
        self.assertEqual(result["snapshot_id"], graph["snapshot_id"])
        self.assertEqual(snapshot, current_snapshot(self.store))
        return result, graph, snapshot

    def _node(self, graph, label):
        owners = graph["labels"].get(label, [])
        self.assertEqual(len(owners), 1, f"Expected exactly one owner for {label}: {owners}")
        return next(node for node in graph["nodes"] if node["id"] == owners[0])

    def _edges(self, graph, source, target=None, relation=None):
        return [
            edge
            for edge in graph["edges"]
            if edge["source"] == source
            and (target is None or edge["target"] == target)
            and (relation is None or edge["relation"] == relation)
        ]

    def _sidecar(self, content):
        path = self.work / "annotations.json"
        path.write_text(
            json.dumps({"schema": "qecgraph.annotations", **content}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_rehashed_resource_cannot_keep_the_original_snapshot_identity(self):
        _, _, snapshot = self._write_project(
            r"\includegraphics{figure.svg}", {"figure.svg": "<svg>original</svg>"}
        )
        replacement = b"<svg>modified</svg>"
        (snapshot / "assets/figure.svg").write_bytes(replacement)
        manifest_path = snapshot / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        digest = hashlib.sha256(replacement).hexdigest()
        resource, = manifest["resources"]
        resource["sha256"] = digest
        next(output for output in manifest["outputs"] if output["path"] == "assets/figure.svg")["sha256"] = digest
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Project source fingerprint mismatch"):
            validate_snapshot(snapshot)

    def test_snapshot_requires_checksum_entries_for_graph_and_referenced_files(self):
        _, graph, snapshot = self._write_project(r"\section{Example}Fixture.")
        manifest_path = snapshot / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        node = next(node for node in graph["nodes"] if node.get("fragment_path"))
        for relative in ("graph.json", "sources/main.tex", node["record_path"], node["fragment_path"]):
            with self.subTest(relative=relative):
                updated = {**manifest, "outputs": [row for row in manifest["outputs"] if row["path"] != relative]}
                manifest_path.write_text(json.dumps(updated))
                with self.assertRaisesRegex(ValueError, "Required snapshot outputs missing"):
                    validate_snapshot(snapshot)

    def test_rehashed_fragment_must_still_match_the_archived_source(self):
        _, graph, snapshot = self._write_project(r"\section{Example}Fixture.")
        fragment = next(node["fragment_path"] for node in graph["nodes"] if node.get("fragment_path"))
        replacement = b"Modified fragment."
        (snapshot / fragment).write_bytes(replacement)
        manifest_path = snapshot / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        next(row for row in manifest["outputs"] if row["path"] == fragment)["sha256"] = hashlib.sha256(replacement).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Snapshot output does not match the archived source"):
            validate_snapshot(snapshot)

    def test_snapshot_output_links_must_resolve_inside_the_snapshot(self):
        _, graph, snapshot = self._write_project(r"\section{Example}Fixture.")
        node = next(node for node in graph["nodes"] if node.get("fragment_path"))
        fragment = snapshot / node["fragment_path"]
        retained = snapshot / "retained.tex"
        fragment.rename(retained)
        fragment.symlink_to(retained)
        self.assertTrue(validate_snapshot(snapshot)["passed"])

        outside = self.work / "outside.tex"
        outside.write_bytes(retained.read_bytes())
        fragment.unlink()
        fragment.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Path escapes root"):
            validate_snapshot(snapshot)

    def test_snapshot_validation_rejects_a_named_pipe_without_blocking(self):
        _, _, snapshot = self._write_project(r"\section{Example}Fixture.")
        graph_path = snapshot / "graph.json"
        graph_path.unlink()
        os.mkfifo(graph_path)
        with self.assertRaisesRegex(ValueError, "Expected a regular snapshot output"):
            validate_snapshot(snapshot)

    def test_demo_has_exact_real_labels_and_ignores_comment_and_verbatim_ghosts(self):
        _, graph, _ = self._demo()
        self.assertEqual(set(graph["labels"]), set(EXPECTED_LABEL_KINDS))
        for label, kind in EXPECTED_LABEL_KINDS.items():
            with self.subTest(label=label):
                self.assertEqual(self._node(graph, label)["kind"], kind)
        ghosts = {"lem:comment-ghost", "lem:verbatim-ghost", "thm:verbatim-ghost"}
        self.assertFalse(ghosts.intersection(graph["labels"]))
        self.assertFalse(
            any(edge["evidence"].get("label") in ghosts for edge in graph["edges"])
        )
        file_paths = {
            node["data"]["path"]
            for node in graph["nodes"]
            if node["kind"] == "source_file"
        }
        self.assertEqual(
            file_paths,
            {"main.tex", "sections/foundations.tex", "sections/hgp.tex", "references.bib"},
        )
        self.assertFalse(
            any("must-not-be-read" in diagnostic["message"] for diagnostic in graph["diagnostics"])
        )

    def test_nested_equations_keep_their_own_labels_and_containment(self):
        _, graph, _ = self._demo()
        pairs = [
            ("def:css", "eq:css-commutation"),
            ("thm:hgp-css", "eq:hgp-checks"),
            ("thm:hgp-length", "eq:repetition-seed"),
        ]
        for parent_label, equation_label in pairs:
            with self.subTest(equation=equation_label):
                parent = self._node(graph, parent_label)
                equation = self._node(graph, equation_label)
                self.assertEqual(equation["kind"], "equation")
                self.assertNotIn(equation_label, parent["labels"])
                self.assertEqual(len(self._edges(graph, parent["id"], equation["id"], "contains")), 1)
                self.assertEqual(parent["source"]["path"], equation["source"]["path"])
                self.assertLessEqual(parent["source"]["char_start"], equation["source"]["char_start"])
                self.assertGreaterEqual(parent["source"]["char_end"], equation["source"]["char_end"])

    def test_explicit_proves_and_adjacent_proofs_have_distinct_status(self):
        _, graph, _ = self._demo()
        proof = self._node(graph, "proof:hgp-length")
        statement = self._node(graph, "thm:hgp-length")
        explicit = self._edges(graph, proof["id"], statement["id"], "proof_of")
        self.assertEqual(len(explicit), 1)
        self.assertEqual(explicit[0]["status"], "declared")
        self.assertEqual(explicit[0]["evidence"]["method"], "latex_proves")
        self.assertEqual(self._edges(graph, proof["id"], relation="proof_of_candidate"), [])
        for proof_label, statement_label in [
            ("proof:css-commutation", "lem:css-commutation"),
            ("proof:hgp-css", "thm:hgp-css"),
        ]:
            with self.subTest(proof=proof_label):
                candidate_proof = self._node(graph, proof_label)
                candidate_statement = self._node(graph, statement_label)
                links = self._edges(
                    graph, candidate_proof["id"], candidate_statement["id"], "proof_of_candidate"
                )
                self.assertEqual(len(links), 1)
                self.assertEqual(links[0]["status"], "candidate")
                self.assertEqual(self._edges(graph, candidate_proof["id"], relation="proof_of"), [])

    def test_uses_is_declared_but_a_background_ref_is_only_a_reference(self):
        _, graph, _ = self._demo()
        proof = self._node(graph, "proof:hgp-css")
        lemma = self._node(graph, "lem:css-commutation")
        uses = self._edges(graph, proof["id"], lemma["id"], "depends_on_declared")
        self.assertEqual(len(uses), 1)
        self.assertEqual(uses[0]["status"], "declared")
        self.assertEqual(uses[0]["evidence"]["method"], "latex_uses")
        background = [
            node for node in graph["nodes"]
            if node["kind"] == "paragraph" and "For background and motivation" in node["latex"]
        ]
        self.assertEqual(len(background), 1)
        theorem = self._node(graph, "thm:hgp-css")
        refs = self._edges(graph, background[0]["id"], theorem["id"], "references")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["status"], "observed")
        self.assertFalse(
            any(edge["relation"].startswith("depends_on")
                for edge in self._edges(graph, background[0]["id"]))
        )
        self.assertFalse(any(edge["relation"] == "depends_on_reviewed" for edge in graph["edges"]))

    def test_author_leanok_does_not_claim_mathematical_or_lean_verification(self):
        _, graph, _ = self._demo()
        lemma = self._node(graph, "lem:css-commutation")
        self.assertTrue(lemma["data"]["author_claims_formalized"])
        lean_nodes = [node for node in graph["nodes"] if node["kind"] == "lean_declaration"]
        self.assertEqual(len(lean_nodes), 1)
        declaration = lean_nodes[0]
        self.assertEqual(declaration["data"]["declaration"], "QEC.Examples.binary_css_commutation")
        self.assertEqual(declaration["data"]["proof_status"], "not_checked")
        self.assertIsNone(declaration["data"]["build_evidence"])
        self.assertEqual(
            len(self._edges(graph, declaration["id"], lemma["id"], "formalizes")), 1
        )
        forbidden = {"verified", "lean_verified", "kernel_checked"}
        self.assertTrue(all(node["verification_status"] not in forbidden for node in graph["nodes"]))
        self.assertEqual(graph["semantic_status"], "not_mathematically_verified")

    def test_unicode_crlf_and_fragment_coordinates_preserve_original_bytes(self):
        text = "\r\n".join([
            r"\documentclass{article}",
            r"\newtheorem{lemma}{Lemma}",
            r"\begin{document}",
            "% 中文在块之前；字节偏移不等于字符偏移。",
            "正文含有中文。",
            "",
            r"\begin{lemma}[Unicode example]",
            r"\label{lem:unicode}",
            r"For $a\in\mathbb{F}_2$, $a+a=0$.",
            r"\end{lemma}",
            r"\end{document}",
            "",
        ])
        original = text.encode("utf-8")
        _, graph, snapshot = self._write_project(text)
        self.assertEqual(self.entry.read_bytes(), original)
        self.assertEqual((snapshot / "sources" / "main.tex").read_bytes(), original)
        node = self._node(graph, "lem:unicode")
        start = node["source"]["char_start"]
        self.assertGreater(len(text[:start].encode("utf-8")), start)
        self.assertIn("\r\n", node["latex"])
        for fragment in graph["nodes"]:
            span = fragment.get("source")
            if not span:
                continue
            self.assertEqual(fragment["latex"], text[span["char_start"]:span["char_end"]])
            self.assertEqual(span["line_start"], text.count("\n", 0, span["char_start"]) + 1)
            self.assertEqual(
                span["line_end"],
                text.count("\n", 0, max(span["char_start"], span["char_end"] - 1)) + 1,
            )
            self.assertEqual(
                (snapshot / fragment["fragment_path"]).read_bytes(),
                fragment["latex"].encode("utf-8"),
            )
        source = next(node for node in graph["nodes"] if node["kind"] == "source_file")
        self.assertEqual(source["data"]["sha256"], hashlib.sha256(original).hexdigest())
        self.assertTrue(validate_snapshot(snapshot)["passed"])

    def test_missing_cycle_and_outside_includes_are_diagnosed(self):
        outside = self.work / "outside.tex"
        outside_bytes = br"\begin{lemma}\label{lem:outside-read}Secret fixture.\end{lemma}"
        outside.write_bytes(outside_bytes)
        main = r"""
\documentclass{article}
\newtheorem{lemma}{Lemma}
\begin{document}
\input{missing}
\input{cycle}
\input{../outside}
\end{document}
"""
        _, graph, snapshot = self._write_project(main, {"cycle.tex": r"\input{main}"})
        codes = {diagnostic["code"] for diagnostic in graph["diagnostics"]}
        self.assertTrue({"missing_include", "include_cycle", "path_outside_project"} <= codes)
        self.assertEqual(graph["extraction_status"], "partial")
        self.assertNotIn("lem:outside-read", graph["labels"])
        self.assertEqual(outside.read_bytes(), outside_bytes)
        source_paths = {
            node["data"]["path"] for node in graph["nodes"] if node["kind"] == "source_file"
        }
        self.assertEqual(source_paths, {"main.tex", "cycle.tex"})
        self.assertTrue(validate_snapshot(snapshot)["passed"])

    def test_duplicate_labels_are_not_merged_and_reference_resolution_is_ambiguous(self):
        text = r"""
\documentclass{article}
\newtheorem{lemma}{Lemma}
\begin{document}
\begin{lemma}\label{lem:duplicate}First statement.\end{lemma}
\begin{lemma}\label{lem:duplicate}Second statement.\end{lemma}

Compare Lemma~\ref{lem:duplicate}.
\end{document}
"""
        _, graph, _ = self._write_project(text)
        ids = graph["labels"]["lem:duplicate"]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        owners = [node for node in graph["nodes"] if node["id"] in ids]
        self.assertEqual({node["kind"] for node in owners}, {"lemma"})
        self.assertEqual(len({node["content_sha256"] for node in owners}), 2)
        unresolved = [
            node for node in graph["nodes"]
            if node["kind"] == "unresolved_reference"
            and node["data"]["label"] == "lem:duplicate"
        ]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["data"]["reason"], "ambiguous")
        self.assertEqual(set(unresolved[0]["data"]["candidate_ids"]), set(ids))
        refs = [edge for edge in graph["edges"] if edge["relation"] == "references"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["target"], unresolved[0]["id"])
        self.assertEqual(refs[0]["status"], "unresolved")
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            query.show(self.store, "lem:duplicate")

    def test_repeated_ingest_is_idempotent_and_does_not_modify_source_files(self):
        result, _, snapshot = self._demo()
        before = {
            str(path.relative_to(self.paper)): path.read_bytes()
            for path in self.paper.rglob("*") if path.is_file()
        }
        second, _, second_snapshot = self._ingest()
        self.assertEqual(result["snapshot_id"], second["snapshot_id"])
        self.assertEqual(snapshot, second_snapshot)
        self.assertEqual(len(list((self.store / "snapshots").iterdir())), 1)
        after = {
            str(path.relative_to(self.paper)): path.read_bytes()
            for path in self.paper.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertTrue(validate_snapshot(snapshot)["passed"])

    def test_labeled_edits_keep_identity_and_stale_a_bound_review(self):
        text = r"""
\documentclass{article}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}\label{thm:stable}
Let $n=13$. Then $n$ is positive.
\end{theorem}
\end{document}
"""
        _, initial, initial_snapshot = self._write_project(text)
        original = self._node(initial, "thm:stable")
        sidecar = self._sidecar({
            "annotations": [{
                "target": "label:thm:stable",
                "review_status": "reviewed",
                "expected_content_sha256": original["content_sha256"],
                "expected_project_source_hash": initial["project_source_hash"],
                "note": "A test-only source review bound to the original text.",
            }]
        })
        _, reviewed_graph, reviewed_snapshot = self._ingest(sidecar)
        reviewed = self._node(reviewed_graph, "thm:stable")
        self.assertEqual(reviewed["annotations"][0]["effective_status"], "reviewed")
        self.entry.write_bytes(text.replace("n=13", "n=14").encode("utf-8"))
        _, updated, updated_snapshot = self._ingest(sidecar)
        modified = self._node(updated, "thm:stable")
        self.assertEqual(original["id"], modified["id"])
        self.assertNotEqual(original["content_sha256"], modified["content_sha256"])
        self.assertNotEqual(initial["project_source_hash"], updated["project_source_hash"])
        self.assertEqual(modified["annotations"][0]["effective_status"], "stale")
        self.assertIn("stale_annotation", {d["code"] for d in updated["diagnostics"]})
        self.assertEqual((initial_snapshot / "sources" / "main.tex").read_bytes(), text.encode("utf-8"))
        self.assertEqual((reviewed_snapshot / "sources" / "main.tex").read_bytes(), text.encode("utf-8"))
        self.assertNotEqual(reviewed_snapshot, updated_snapshot)
        self.assertTrue(validate_snapshot(initial_snapshot)["passed"])
        report = json.loads((updated_snapshot / "report.json").read_text(encoding="utf-8"))
        self.assertIn(modified["id"], report["changes"]["content_changed"])

    def test_only_explicit_sidecar_creates_a_code_entity_from_a_parameter_table(self):
        _, graph, _ = self._demo()
        self.assertFalse(any(node["kind"] == "quantum_code" for node in graph["nodes"]))
        self.assertEqual(self._node(graph, "tab:rep3")["kind"], "table")
        code_id = "code:fixture:rep3"
        sidecar = self._sidecar({
            "nodes": [{
                "id": code_id,
                "kind": "quantum_code",
                "title": "Rep3 ordinary HGP example",
                "source_labels": ["tab:rep3", "ex:rep3-parameters"],
                "data": {"n": 13, "k": 1, "distance_claimed": 3},
            }]
        })
        _, extended, _ = self._ingest(sidecar)
        code = query.show(self.store, code_id)["node"]
        self.assertEqual(code["kind"], "quantum_code")
        self.assertEqual(code["origin"], "sidecar")
        self.assertEqual(code["verification_status"], "not_rechecked")
        self.assertEqual(code["data"]["distance_claimed"], 3)
        for label in ["tab:rep3", "ex:rep3-parameters"]:
            source = self._node(extended, label)
            links = self._edges(extended, source["id"], code_id, "describes")
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]["status"], "declared")
        hits = query.search(self.store, "Rep3", kind="quantum_code")["results"]
        self.assertEqual([hit["id"] for hit in hits], [code_id])

    def test_default_dependencies_exclude_candidates_and_context_keeps_explicit_proof(self):
        _, graph, _ = self._demo()
        lemma = self._node(graph, "lem:css-commutation")
        default = query.dependencies(self.store, "thm:hgp-css", depth=1)
        expanded = query.dependencies(
            self.store, "thm:hgp-css", depth=1, include_candidates=True
        )
        self.assertFalse(any(edge["relation"] == "depends_on_candidate" for edge in default["edges"]))
        self.assertNotIn(lemma["id"], {node["id"] for node in default["nodes"]})
        self.assertIn(lemma["id"], {node["id"] for node in expanded["nodes"]})
        self.assertTrue(any(edge["relation"] == "depends_on_candidate" for edge in expanded["edges"]))
        bundle = query.context(self.store, "thm:hgp-length", depth=1, max_nodes=60)
        explicit_proof = self._node(graph, "proof:hgp-length")
        self.assertIn(explicit_proof["id"], {node["id"] for node in bundle["nodes"]})
        bundled_proof = next(node for node in bundle["nodes"] if node["id"] == explicit_proof["id"])
        self.assertEqual(bundled_proof["latex"], explicit_proof["latex"])
        self.assertEqual(bundled_proof["source"], explicit_proof["source"])
        self.assertEqual(bundle["snapshot_id"], graph["snapshot_id"])

    def test_proof_reference_to_untyped_assumption_remains_a_source_reference(self):
        _, graph, snapshot = self._write_project(r"""
\begin{definition}\label{def:bound}Define the bound.\end{definition}
\begin{assumption}\label{asmp:bound}Assume the bound holds.\end{assumption}
\begin{lemma}\label{lem:bound}A consequence follows.\end{lemma}
\begin{proof}\label{proof:bound}
Apply \Cref{asmp:bound} to the quantity in \ref{def:bound}.
\end{proof}
""")
        proof = self._node(graph, "proof:bound")
        lemma = self._node(graph, "lem:bound")
        assumption = self._node(graph, "asmp:bound")
        definition = self._node(graph, "def:bound")

        self.assertEqual(assumption["kind"], "assumption")
        original, = self._edges(graph, proof["id"], assumption["id"], "references")
        self.assertEqual(original["status"], "observed")
        self.assertEqual(original["evidence"]["label"], "asmp:bound")
        assumption_edge, = self._edges(graph, lemma['id'], assumption['id'], 'depends_on_candidate')
        self.assertEqual(assumption_edge['status'], 'candidate')
        candidate, = self._edges(graph, lemma["id"], definition["id"], "depends_on_candidate")
        self.assertEqual(candidate["status"], "candidate")
        self.assertTrue(validate_snapshot(snapshot)["passed"])

    def test_stale_proof_dependency_is_not_lifted_to_its_statement(self):
        _, initial, _ = self._demo()
        proof = self._node(initial, "proof:hgp-length")
        statement = self._node(initial, "thm:hgp-length")
        lemma = self._node(initial, "lem:css-commutation")
        sidecar = self._sidecar({
            "edges": [{
                "source": "label:proof:hgp-length",
                "target": "label:lem:css-commutation",
                "relation": "depends_on_declared",
                "expected_project_source_hash": initial["project_source_hash"],
                "expected_hashes": {
                    proof["id"]: "0" * 64,
                    lemma["id"]: lemma["content_sha256"],
                },
            }]
        })
        _, graph, _ = self._ingest(sidecar)
        stale_edges = self._edges(graph, proof["id"], lemma["id"], "depends_on_declared")
        self.assertEqual(len(stale_edges), 1)
        self.assertEqual(stale_edges[0]["status"], "stale")
        lifted = [
            edge for edge in self._edges(graph, statement["id"], lemma["id"])
            if edge["relation"].startswith("depends_on")
        ]
        self.assertEqual(lifted, [])
        result = query.dependencies(self.store, "thm:hgp-length", depth=1)
        self.assertNotIn(lemma["id"], {node["id"] for node in result["nodes"]})

    def test_resource_hash_exists_before_review_matching_and_resource_edits_stale_it(self):
        _, initial, _ = self._demo()
        asset = next(
            node for node in initial["nodes"]
            if node["kind"] == "asset"
            and node["data"].get("path") == "figures/tanner-placeholder.svg"
        )
        resource = self.paper / asset["data"]["path"]
        original_bytes = resource.read_bytes()
        self.assertEqual(asset["data"]["sha256"], hashlib.sha256(original_bytes).hexdigest())
        self.assertEqual(asset["data"]["size_bytes"], len(original_bytes))
        sidecar = self._sidecar({
            "annotations": [{
                "target": asset["id"],
                "review_status": "reviewed",
                "expected_content_sha256": asset["content_sha256"],
                "expected_project_source_hash": initial["project_source_hash"],
                "note": "Test-only review of the exact referenced asset.",
            }]
        })
        _, reviewed_graph, _ = self._ingest(sidecar)
        reviewed = next(node for node in reviewed_graph["nodes"] if node["id"] == asset["id"])
        self.assertEqual(reviewed["content_sha256"], asset["content_sha256"])
        self.assertEqual(reviewed["annotations"][0]["effective_status"], "reviewed")
        changed_bytes = original_bytes.replace(b"<title", b"<!-- Resource revision. -->\n<title", 1)
        self.assertNotEqual(changed_bytes, original_bytes)
        resource.write_bytes(changed_bytes)
        _, updated_graph, updated_snapshot = self._ingest(sidecar)
        updated = next(node for node in updated_graph["nodes"] if node["id"] == asset["id"])
        self.assertEqual(updated["data"]["sha256"], hashlib.sha256(changed_bytes).hexdigest())
        self.assertNotEqual(updated["content_sha256"], asset["content_sha256"])
        self.assertEqual(updated["annotations"][0]["effective_status"], "stale")
        self.assertEqual(
            (updated_snapshot / "assets" / asset["data"]["path"]).read_bytes(), changed_bytes
        )


    def test_context_final_edges_exclude_candidates_and_stale_relations(self):
        _, initial, _ = self._demo()
        lemma = self._node(initial, "lem:css-commutation")
        theorem = self._node(initial, "thm:hgp-css")
        # Both endpoints are otherwise reachable through valid source references.
        sidecar = self._sidecar({"edges": [{
            "source": theorem["id"], "target": lemma["id"],
            "relation": "depends_on_declared",
            "expected_project_source_hash": "0" * 64,
        }]})
        self._ingest(sidecar)
        normal = query.context(self.store, "thm:hgp-css", depth=2)
        self.assertTrue(all(e["status"] not in {"candidate", "stale", "unbound_review", "unresolved"}
                            for e in normal["edges"]))
        self.assertTrue(all(not e["relation"].endswith("_candidate") for e in normal["edges"]))
        inclusive = query.context(self.store, "thm:hgp-css", depth=2, include_candidates=True)
        self.assertTrue(any(e["relation"].endswith("_candidate") for e in inclusive["edges"]))
        self.assertFalse(any(e["status"] == "stale" for e in inclusive["edges"]))

    def test_data_context_expands_explicit_matrix_and_configuration_links(self):
        self._demo()
        sidecar = self._sidecar({"nodes": [
            {"id": "code:context-demo", "kind": "quantum_code", "title": "Code"},
            {"id": "matrix:context-demo", "kind": "matrix", "title": "Matrix"},
            {"id": "circuit:context-demo", "kind": "circuit", "title": "Circuit"},
        ], "edges": [
            {"source": "code:context-demo", "target": "matrix:context-demo", "relation": "has_matrix"},
            {"source": "code:context-demo", "target": "circuit:context-demo", "relation": "uses_circuit"},
        ]})
        self._ingest(sidecar)
        result = query.context(self.store, "code:context-demo", depth=1)
        self.assertEqual({n["id"] for n in result["nodes"]},
                         {"code:context-demo", "matrix:context-demo", "circuit:context-demo"})


if __name__ == "__main__":
    unittest.main()
