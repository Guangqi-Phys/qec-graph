"""Build explicit, declared and candidate relations without conflating them."""
from __future__ import annotations

import hashlib
import json
import math
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

from .. import __version__

STATEMENTS = {"lemma", "theorem", "proposition", "corollary", "conjecture"}
MATHEMATICS = STATEMENTS | {"definition", "proof", "equation"}
LEAN_DEPENDENCIES = {'lean_type_depends_on', 'lean_proof_depends_on',
                     'lean_type_depends_on_transitive', 'lean_proof_depends_on_transitive'}
DEPENDENCIES = {"depends_on_declared", "depends_on_reviewed"} | LEAN_DEPENDENCIES
CANDIDATES = {"depends_on_candidate"}
KNOWN_RELATIONS = {
    "contains", "defined_in", "includes", "references", "cites", "uses_resource",
    "depends_on_declared", "depends_on_candidate", "depends_on_reviewed",
    "proof_of", "proof_of_candidate", "formalizes", "describes", "about",
    "has_matrix", "has_presentation", "generated_by", "uses_circuit", "uses_noise",
    "uses_decoder", "supports", "contradicts", "reports", "instance_of",
}


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strict_json_loads(text, source='<json>'):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate key {key!r} in {source}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f'Non-finite JSON number {value!r} in {source}')

    def finite_float(raw):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f'Non-finite JSON number in {source}')
        return value

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float)


def read_json(path):
    return strict_json_loads(Path(path).read_text(encoding='utf-8'), source=str(path))


def node_filename(node_id: str) -> str:
    # Human-readable prefix plus full-content identity suffix; no path separators.
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", node_id).strip("-")[:72] or "node"
    return slug + "--" + hash_text(node_id)[:16]


def build_graph(parsed: dict, project_id: str, project_source_hash: str,
                annotations: dict | None = None, catalog: list[dict] | None = None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", project_id):
        raise ValueError("project-id must contain only letters, numbers, dot, dash or underscore")

    builder = _GraphBuilder(parsed, project_id, project_source_hash)
    builder.add_source_nodes()
    builder.add_source_relations()
    builder.infer_adjacent_proofs()
    builder.attach_resources()
    builder.attach_catalog(catalog)
    builder.attach_annotations(annotations)
    builder.lift_proof_dependencies()
    return builder.finish()


class _GraphBuilder:
    """Assemble one graph from parsed sources, sidecars and catalogue records."""

    def __init__(self, parsed: dict, project_id: str, project_source_hash: str) -> None:
        self.parsed = parsed
        self.project_id = project_id
        self.project_source_hash = project_source_hash
        self.document_id = "paper:" + project_id
        self.blocks = parsed["blocks"]
        self.files = {file["path"]: file for file in parsed["files"]}
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.edge_ids: set[str] = set()
        self.labels: defaultdict[str, list[str]] = defaultdict(list)
        self.key_to_id: dict[str, str] = {}
        self.diagnostics = list(parsed.get("diagnostics", []))

    def add_node(self, node):
        if node["id"] in self.nodes:
            raise ValueError(f"Duplicate node identity: {node['id']}")
        node.setdefault("review_status", "extracted")
        node.setdefault("verification_status", "not_verified")
        node.setdefault("labels", [])
        node.setdefault("data", {})
        node.setdefault("latex", "")
        node.setdefault("source", None)
        node.setdefault("content_sha256", hash_text(node["latex"] or canonical(node["data"])))
        self.nodes[node["id"]] = node

    def edge(self, source, target, relation, status="observed", evidence=None):
        if source not in self.nodes or target not in self.nodes:
            raise ValueError(f"Edge endpoint missing: {source} -> {target}")
        item = {"source": source, "target": target, "relation": relation, "status": status,
                "evidence": evidence or {}}
        item["id"] = "edge:" + hash_text(canonical(item))[:24]
        if item["id"] not in self.edge_ids:
            self.edge_ids.add(item["id"])
            self.edges.append(item)
            return item

    def diag(self, code, message, source=None, severity="warning"):
        self.diagnostics.append({"severity": severity, "code": code, "message": message, "source": source})

    def file_id(self, path):
        return "source:" + self.project_id + ":" + quote(path, safe="/._-")

    def resolve_label(self, label, source=None):
        matches = self.labels.get(label, [])
        if len(matches) == 1:
            return matches[0]
        reason = "ambiguous" if matches else "missing"
        identifier = "unresolved:" + self.project_id + ":" + quote(label, safe=":._-")
        if identifier not in self.nodes:
            self.add_node({"id": identifier, "kind": "unresolved_reference", "title": label,
                      "origin": "parser", "review_status": "needs_review",
                      "data": {"label": label, "reason": reason, "candidate_ids": matches}})
        self.diag("unresolved_reference", f"Reference {label!r} is {reason}", source)
        return identifier

    def add_source_nodes(self) -> None:
        source_hash = {path: file["sha256"] for path, file in self.files.items()}
        occurrences: Counter[str] = Counter()
        label_counts = Counter(label for block in self.blocks for label in set(block.get("labels", [])))
        self.add_node({"id": self.document_id, "kind": "document", "title": self.project_id,
                  "origin": "parser", "data": {"entry": self.parsed["entry"], "project_source_hash": self.project_source_hash}})
        for path, file in self.files.items():
            self.add_node({"id": self.file_id(path), "kind": "source_file", "title": path, "origin": "parser",
                      "data": {"path": path, "sha256": file["sha256"], "encoding": file["encoding"]}})
            self.edge(self.document_id, self.file_id(path), "contains")

        for block in self.blocks:
            owned_labels = list(dict.fromkeys(block.get("labels", [])))
            if owned_labels:
                base = self.project_id + ":label:" + quote(owned_labels[0], safe=":._-")
                if label_counts[owned_labels[0]] > 1:
                    base += ":occ:" + hash_text(canonical(block["source"]))[:12]
            else:
                base = self.project_id + ":" + block["kind"] + ":anon:" + hash_text(
                    block["source"]["path"] + "\0" + block["kind"] + "\0" + block["latex"])[:16]
            occurrences[base] += 1
            identifier = base if occurrences[base] == 1 else base + ":" + str(occurrences[base])
            self.key_to_id[block["key"]] = identifier
            span = dict(block["source"])
            span["file_sha256"] = source_hash[span["path"]]
            span["coordinate_system"] = "unicode_codepoints_half_open; lines_1based_inclusive"
            self.add_node({"id": identifier, "kind": block["kind"], "origin": "parser",
                      "title": block.get("title_tex") or (owned_labels[0] if owned_labels else block["kind"]),
                      "labels": owned_labels, "source": span, "latex": block["latex"],
                      "content_sha256": hash_text(block["latex"]),
                      "data": {"environment": block.get("environment"), "order": block.get("order", 0),
                               "author_claims_formalized": bool(block.get("leanok_declared", False)),
                               "identity_basis": "label" if owned_labels else "content_and_occurrence",
                               "semantic_context_sha256": self.project_source_hash}})
            for label in owned_labels:
                self.labels[label].append(identifier)

        for label, ids in self.labels.items():
            if len(ids) > 1:
                self.diag("duplicate_label", f"Label {label!r} has {len(ids)} owners; references stay unresolved")

    def add_source_relations(self) -> None:
        for block in self.blocks:
            identifier = self.key_to_id[block["key"]]
            parent = self.key_to_id.get(block.get("parent_key"), self.file_id(block["source"]["path"]))
            self.edge(parent, identifier, "contains")
            self.edge(identifier, self.file_id(block["source"]["path"]), "defined_in", evidence={"source": block["source"]})
        for inclusion in self.parsed.get("includes", []):
            if inclusion.get("to") in self.files and inclusion["from"] in self.files:
                self.edge(self.file_id(inclusion["from"]), self.file_id(inclusion["to"]), "includes", evidence=inclusion)

        # Preserve explicit syntax; ordinary references never become checked dependencies.
        for block in self.blocks:
            identifier = self.key_to_id[block["key"]]
            for reference in block.get("references", []):
                kind = reference["kind"]
                for label in reference["targets"]:
                    evidence = {"method": "latex_" + kind, "source": reference.get("source"), "label": label}
                    if kind == "cite":
                        target = "citation:" + self.project_id + ":" + quote(label, safe=":._-")
                        if target not in self.nodes:
                            self.add_node({"id": target, "kind": "citation_key", "title": label, "origin": "parser",
                                      "data": {"bibliography_key": label, "metadata_status": "not_resolved"}})
                        self.edge(identifier, target, "cites", evidence=evidence)
                        continue
                    target = self.resolve_label(label, reference.get("source"))
                    unresolved = self.nodes[target]["kind"] == "unresolved_reference"
                    if kind == "uses":
                        if block["kind"] in MATHEMATICS:
                            self.edge(identifier, target, "depends_on_declared", "unresolved" if unresolved else "declared", evidence)
                        else:
                            # A dependency annotation outside a mathematical block keeps
                            # its textual meaning but is not a typed proof dependency.
                            self.diag("uses_outside_mathematics",
                                      "\\uses outside a mathematical block is preserved as a reference",
                                      reference.get("source") or block["source"])
                            self.edge(identifier, target, "references", "unresolved" if unresolved else "observed", evidence)
                    elif kind == "proves":
                        if block["kind"] != "proof":
                            self.diag("proves_outside_proof", "\\proves found outside a proof block", reference.get("source"))
                            continue
                        if not unresolved and self.nodes[target]["kind"] not in STATEMENTS:
                            self.diag("invalid_proof_target", f"Proof target {label!r} is not a theorem-like node", reference.get("source"))
                            continue
                        self.edge(identifier, target, "proof_of", "unresolved" if unresolved else "declared", evidence)
                    else:
                        self.edge(identifier, target, "references", "unresolved" if unresolved else "observed", evidence)

            for declaration in block.get("lean_declarations", []):
                target = "lean:" + self.project_id + ":" + quote(declaration, safe="._-")
                if target not in self.nodes:
                    self.add_node({"id": target, "kind": "lean_declaration", "title": declaration, "origin": "parser",
                              "data": {"declaration": declaration, "project_revision": None, "build_evidence": None,
                                       "mapping_status": "author_declared", "proof_status": "not_checked"}})
                if block["kind"] in MATHEMATICS:
                    self.edge(target, identifier, "formalizes", "declared", {"method": "latex_lean", "source": block["source"]})
                else:
                    # \lean on a remark/table/paragraph is author metadata, not a
                    # formalization of a mathematical statement.
                    self.diag("lean_metadata_outside_mathematics",
                              "\\lean outside a mathematical block is preserved as a declared association",
                              block["source"])
                    self.edge(target, identifier, "describes", "declared", {"method": "latex_lean", "source": block["source"]})

    def infer_adjacent_proofs(self) -> None:
        # A neighbouring proof is a candidate association, never a verified claim.
        declared_proofs = {item["source"] for item in self.edges if item["relation"] == "proof_of"}
        statement_ends: dict[tuple[str, str | None], dict[int, dict]] = defaultdict(dict)
        for block in self.blocks:
            if block["kind"] in STATEMENTS:
                source = block["source"]
                statement_ends[source["path"], block.get("parent_key")].setdefault(source["char_end"], block)
        ordered_ends = {scope: sorted(statements) for scope, statements in statement_ends.items()}
        for block in self.blocks:
            if block["kind"] != "proof":
                continue
            proof_id = self.key_to_id[block["key"]]
            if proof_id in declared_proofs:
                continue
            source = block["source"]
            scope = (source["path"], block.get("parent_key"))
            ends = ordered_ends.get(scope, ())
            index = bisect_right(ends, source["char_start"])
            if index:
                end = ends[index - 1]
                statement = statement_ends[scope][end]
                gap = self.files[source["path"]]["text"][end:source["char_start"]]
                if not re.sub(r"(?m)(?<!\\)%[^\r\n]*", "", gap).strip():
                    self.edge(proof_id, self.key_to_id[statement["key"]], "proof_of_candidate", "candidate",
                         {"method": "adjacent_statement", "source": block["source"]})

    def attach_resources(self) -> None:
        # Resources are asset references, not interpreted numeric datasets.
        for resource in self.parsed.get("resources", []):
            key = resource.get("path") or resource["literal"]
            identifier = "asset:" + self.project_id + ":" + quote(key, safe="/._-:")
            if identifier not in self.nodes:
                self.add_node({"id": identifier, "kind": "asset", "title": resource["literal"], "origin": "parser",
                          "data": {"resource_kind": resource["kind"], "path": resource.get("path"),
                                   "sha256": resource.get("sha256"), "size_bytes": resource.get("size_bytes"),
                                   "resolution_status": "resolved_path" if resource.get("path") else "unresolved"}})
            owner = self.key_to_id.get(resource.get("block_key"), self.file_id(resource["source"]["path"]))
            self.edge(owner, identifier, "uses_resource", evidence={"source": resource["source"]})

    def attach_catalog(self, catalog: list[dict] | None) -> None:
        # Import an existing JSON record catalog without interpreting its numerical claims.
        catalog = catalog or []
        for record in catalog:
            self.add_node({"id": record["id"], "kind": record.get("kind", "data_entity"), "origin": "catalog",
                      "title": record.get("title", record["id"]), "data": {"record": record},
                      "review_status": "imported", "verification_status": "imported_claim_not_rechecked"})
        for record in catalog:
            for ref in record.get("refs", []):
                if ref["target_id"] in self.nodes:
                    self.edge(record["id"], ref["target_id"], "catalog:" + ref["relation"], "declared",
                         {"method": "catalog_record", "record_id": record["id"]})
                else:
                    self.diag("catalog_missing_target", f"{record['id']} refers to missing {ref['target_id']}")

    def attach_annotations(self, annotations: dict | None) -> None:
        annotations = annotations or {}
        if annotations and annotations.get("schema_version") != "qecgraph.annotations.v1":
            raise ValueError("Expected annotation schema_version qecgraph.annotations.v1")

        def selector(value):
            if value in self.nodes:
                return value
            if value.startswith("label:"):
                label = value.removeprefix("label:")
                if len(self.labels.get(label, [])) == 1:
                    return self.labels[label][0]
                raise ValueError(f"Annotation label is missing or ambiguous: {label}")
            raise ValueError(f"Unknown annotation node: {value}")

        for node in annotations.get("nodes", []):
            if not {"id", "kind", "title"} <= node.keys():
                raise ValueError("Annotation nodes require id, kind and title")
            if not re.fullmatch(r"[a-z][a-z0-9_]*", node["kind"]):
                raise ValueError("Invalid annotation node kind")
            self.add_node({"id": node["id"], "kind": node["kind"], "title": node["title"], "origin": "sidecar",
                      "data": node.get("data", {}), "review_status": "declared",
                      "verification_status": "not_rechecked"})
            for label in node.get("source_labels", []):
                try:
                    source = selector("label:" + label)
                except ValueError as exc:
                    self.diag("annotation_unresolved", str(exc))
                    continue
                self.edge(source, node["id"], "describes", "declared", {"method": "sidecar", "source_label": label})

        for annotation in annotations.get("annotations", []):
            try:
                target = selector(annotation["target"])
            except ValueError as exc:
                self.diag("annotation_unresolved", str(exc))
                continue
            expected = annotation.get("expected_content_sha256")
            expected_context = annotation.get("expected_project_source_hash")
            is_stale = ((expected is not None and expected != self.nodes[target]["content_sha256"])
                        or (expected_context is not None and expected_context != self.project_source_hash))
            requested_status = annotation.get("review_status", "draft")
            status = "stale" if is_stale else requested_status
            if requested_status == "reviewed" and (not expected or not expected_context):
                status = "unbound_review"
                self.diag("review_not_bound", "A reviewed annotation must bind both content and project source hashes", self.nodes[target]["source"])
            if is_stale:
                self.diag("stale_annotation", f"Stored review no longer matches {target}", self.nodes[target]["source"])
            self.nodes[target].setdefault("annotations", []).append({**annotation, "effective_status": status})

        for item in annotations.get("edges", []):
            relation = item["relation"]
            if relation not in KNOWN_RELATIONS:
                raise ValueError(f"Unknown sidecar relation {relation!r}; extend the documented schema explicitly")
            try:
                source, target = selector(item["source"]), selector(item["target"])
            except ValueError as exc:
                self.diag("annotation_unresolved", str(exc))
                continue
            bindings = item.get("expected_hashes", {})
            expected_context = item.get("expected_project_source_hash")
            stale = bool(expected_context and expected_context != self.project_source_hash)
            for endpoint in (source, target):
                if endpoint in bindings and bindings[endpoint] != self.nodes[endpoint]["content_sha256"]:
                    stale = True
            status = "stale" if stale else "declared"
            if relation == "depends_on_reviewed" and (not expected_context or not all(x in bindings for x in (source, target))):
                status = "unbound_review"
                self.diag("review_not_bound", "Reviewed dependency requires endpoint and project hashes")
            self.edge(source, target, relation, status, {"method": "sidecar", "annotation": item})
            if stale:
                self.diag("stale_annotation", f"Edge {source} -> {target} needs review")

    def lift_proof_dependencies(self) -> None:
        from ..validators import ENDPOINTS

        # Lift references/uses from a proof to its proposed/declared statement.
        proof_links, containment, reference_edges = [], defaultdict(list), defaultdict(list)
        for position, item in enumerate(self.edges):
            if item["status"] in {"stale", "unbound_review", "unresolved"}:
                continue
            relation = item["relation"]
            if relation in {"proof_of", "proof_of_candidate"}:
                proof_links.append(item)
            elif relation == "contains":
                containment[item["source"]].append(item["target"])
            elif relation in {"references", "depends_on_declared"}:
                reference_edges[item["source"]].append((position, item))
        for link in proof_links:
            proof_id, statement_id = link["source"], link["target"]
            proof_children = {proof_id}
            pending = [proof_id]
            while pending:
                for child in containment.get(pending.pop(), ()):
                    if child not in proof_children:
                        proof_children.add(child)
                        pending.append(child)
            references = sorted(pair for child in proof_children for pair in reference_edges.get(child, ()))
            for _, reference in references:
                target = reference["target"]
                if target == statement_id:
                    continue
                declared = reference["relation"] == "depends_on_declared" and link["relation"] == "proof_of"
                relation = "depends_on_declared" if declared else "depends_on_candidate"
                sources, targets = ENDPOINTS[relation]
                # Keep ordinary source references without adding a dependency.
                if self.nodes[statement_id]["kind"] not in sources or self.nodes[target]["kind"] not in targets:
                    continue
                lifted = self.edge(statement_id, target, relation, "declared" if declared else "candidate",
                              {"method": "via_proof", "proof_id": proof_id, "proof_link_id": link["id"],
                               "reference_id": reference["id"]})
                if declared and lifted is not None:
                    # Later proof links can see newly declared edges in insertion order.
                    reference_edges[statement_id].append((len(self.edges) - 1, lifted))

    def finish(self) -> dict:
        for node in self.nodes.values():
            node["revision"] = hash_text(canonical({"content": node["content_sha256"], "source": node["source"],
                                                    "semantic_context": self.project_source_hash}))
        graph = {"schema_version": "qecgraph.graph.v1", "tool_version": __version__, "project_id": self.project_id,
                 "project_source_hash": self.project_source_hash, "entry": self.parsed["entry"],
                 "nodes": sorted(self.nodes.values(), key=lambda x: x["id"]),
                 "edges": sorted(self.edges, key=lambda x: x["id"]),
                 "labels": dict(sorted(self.labels.items())), "diagnostics": self.diagnostics,
                 "extraction_status": "partial" if any(d["severity"] == "error" for d in self.diagnostics) else "complete_for_supported_syntax",
                 "semantic_status": "not_mathematically_verified"}
        return graph


def views(graph):
    all_nodes = {n["id"]: n for n in graph["nodes"]}
    source_ids = {n["id"] for n in graph["nodes"] if n["origin"] == "parser" and n["kind"] != "lean_declaration"}
    lemma_ids = {n["id"] for n in graph["nodes"] if n["kind"] in MATHEMATICS | {"lean_declaration"}}
    data_ids = {n["id"] for n in graph["nodes"] if n["origin"] in {"sidecar", "catalog"} or n["kind"] in {"table", "figure", "asset"}}
    result = {}
    for name, base in (("sourcegraph", source_ids), ("lemmagraph", lemma_ids), ("datagraph", data_ids)):
        selected = set(base)
        relevant = [e for e in graph["edges"] if (e["source"] in base or e["target"] in base)
                    and e["relation"] not in {"defined_in", "contains", "includes"}]
        for edge in relevant:
            selected.update((edge["source"], edge["target"]))
        result[name] = {"view": name, "snapshot_id": graph.get("snapshot_id"),
                        "nodes": [all_nodes[n] for n in sorted(selected)],
                        "edges": [e for e in graph["edges"] if e["source"] in selected and e["target"] in selected]}
    return result
