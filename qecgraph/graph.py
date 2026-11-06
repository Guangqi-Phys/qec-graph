"""Build explicit, declared and candidate relations without conflating them."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

from . import __version__

STATEMENTS = {"lemma", "theorem", "proposition", "corollary", "conjecture"}
MATHEMATICS = STATEMENTS | {"definition", "proof", "equation"}
DEPENDENCIES = {"depends_on_declared", "depends_on_reviewed"}
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


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate key {key!r} in {path}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f'Non-finite JSON number {value!r} in {path}')

    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f'Non-finite JSON number in {path}')
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        if isinstance(value, list):
            for item in value:
                finite(item)

    value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    finite(value)
    return value


def node_filename(node_id: str) -> str:
    # Human-readable prefix plus full-content identity suffix; no path separators.
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", node_id).strip("-")[:72] or "node"
    return slug + "--" + hash_text(node_id)[:16]


def build_graph(parsed: dict, project_id: str, project_source_hash: str,
                annotations: dict | None = None, catalog: list[dict] | None = None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", project_id):
        raise ValueError("project-id must contain only letters, numbers, dot, dash or underscore")
    nodes, edges, diagnostics = {}, [], list(parsed.get("diagnostics", []))
    labels = defaultdict(list)
    blocks = parsed["blocks"]
    block_lookup = {block["key"]: block for block in blocks}
    key_to_id = {}
    files = {f["path"]: f for f in parsed["files"]}
    document_id = "paper:" + project_id
    source_hash = {path: f["sha256"] for path, f in files.items()}
    occurrences = Counter()
    label_counts = Counter(label for block in blocks for label in set(block.get("labels", [])))

    def add_node(node):
        if node["id"] in nodes:
            raise ValueError(f"Duplicate node identity: {node['id']}")
        node.setdefault("review_status", "extracted")
        node.setdefault("verification_status", "not_verified")
        node.setdefault("labels", [])
        node.setdefault("data", {})
        node.setdefault("latex", "")
        node.setdefault("source", None)
        node.setdefault("content_sha256", hash_text(node["latex"] or canonical(node["data"])))
        nodes[node["id"]] = node

    def edge(source, target, relation, status="observed", evidence=None):
        if source not in nodes or target not in nodes:
            raise ValueError(f"Edge endpoint missing: {source} -> {target}")
        item = {"source": source, "target": target, "relation": relation, "status": status,
                "evidence": evidence or {}}
        item["id"] = "edge:" + hash_text(canonical(item))[:24]
        if not any(existing["id"] == item["id"] for existing in edges):
            edges.append(item)

    def diag(code, message, source=None, severity="warning"):
        diagnostics.append({"severity": severity, "code": code, "message": message, "source": source})

    def file_id(path):
        return "source:" + project_id + ":" + quote(path, safe="/._-")

    add_node({"id": document_id, "kind": "document", "title": project_id,
              "origin": "parser", "data": {"entry": parsed["entry"], "project_source_hash": project_source_hash}})
    for path, file in files.items():
        add_node({"id": file_id(path), "kind": "source_file", "title": path, "origin": "parser",
                  "data": {"path": path, "sha256": file["sha256"], "encoding": file["encoding"]}})
        edge(document_id, file_id(path), "contains")

    for block in blocks:
        owned_labels = list(dict.fromkeys(block.get("labels", [])))
        if owned_labels:
            base = project_id + ":label:" + quote(owned_labels[0], safe=":._-")
            if label_counts[owned_labels[0]] > 1:
                base += ":occ:" + hash_text(canonical(block["source"]))[:12]
        else:
            base = project_id + ":" + block["kind"] + ":anon:" + hash_text(
                block["source"]["path"] + "\0" + block["kind"] + "\0" + block["latex"])[:16]
        occurrences[base] += 1
        identifier = base if occurrences[base] == 1 else base + ":" + str(occurrences[base])
        key_to_id[block["key"]] = identifier
        span = dict(block["source"])
        span["file_sha256"] = source_hash[span["path"]]
        span["coordinate_system"] = "unicode_codepoints_half_open; lines_1based_inclusive"
        add_node({"id": identifier, "kind": block["kind"], "origin": "parser",
                  "title": block.get("title_tex") or (owned_labels[0] if owned_labels else block["kind"]),
                  "labels": owned_labels, "source": span, "latex": block["latex"],
                  "content_sha256": hash_text(block["latex"]),
                  "data": {"environment": block.get("environment"), "order": block.get("order", 0),
                           "author_claims_formalized": bool(block.get("leanok_declared", False)),
                           "identity_basis": "label" if owned_labels else "content_and_occurrence",
                           "semantic_context_sha256": project_source_hash}})
        for label in owned_labels:
            labels[label].append(identifier)

    for label, ids in labels.items():
        if len(ids) > 1:
            diag("duplicate_label", f"Label {label!r} has {len(ids)} owners; references stay unresolved")

    def resolve_label(label, source=None):
        matches = labels.get(label, [])
        if len(matches) == 1:
            return matches[0]
        reason = "ambiguous" if matches else "missing"
        identifier = "unresolved:" + project_id + ":" + quote(label, safe=":._-")
        if identifier not in nodes:
            add_node({"id": identifier, "kind": "unresolved_reference", "title": label,
                      "origin": "parser", "review_status": "needs_review",
                      "data": {"label": label, "reason": reason, "candidate_ids": matches}})
        diag("unresolved_reference", f"Reference {label!r} is {reason}", source)
        return identifier

    for block in blocks:
        identifier = key_to_id[block["key"]]
        parent = key_to_id.get(block.get("parent_key"), file_id(block["source"]["path"]))
        edge(parent, identifier, "contains")
        edge(identifier, file_id(block["source"]["path"]), "defined_in", evidence={"source": block["source"]})
    for inclusion in parsed.get("includes", []):
        if inclusion.get("to") in files and inclusion["from"] in files:
            edge(file_id(inclusion["from"]), file_id(inclusion["to"]), "includes", evidence=inclusion)

    # Preserve explicit syntax; ordinary references never become checked dependencies.
    for block in blocks:
        identifier = key_to_id[block["key"]]
        for reference in block.get("references", []):
            kind = reference["kind"]
            for label in reference["targets"]:
                evidence = {"method": "latex_" + kind, "source": reference.get("source"), "label": label}
                if kind == "cite":
                    target = "citation:" + project_id + ":" + quote(label, safe=":._-")
                    if target not in nodes:
                        add_node({"id": target, "kind": "citation_key", "title": label, "origin": "parser",
                                  "data": {"bibliography_key": label, "metadata_status": "not_resolved"}})
                    edge(identifier, target, "cites", evidence=evidence)
                    continue
                target = resolve_label(label, reference.get("source"))
                unresolved = nodes[target]["kind"] == "unresolved_reference"
                if kind == "uses":
                    edge(identifier, target, "depends_on_declared", "unresolved" if unresolved else "declared", evidence)
                elif kind == "proves":
                    if block["kind"] != "proof":
                        diag("proves_outside_proof", "\\proves found outside a proof block", reference.get("source"))
                        continue
                    if not unresolved and nodes[target]["kind"] not in STATEMENTS:
                        diag("invalid_proof_target", f"Proof target {label!r} is not a theorem-like node", reference.get("source"))
                        continue
                    edge(identifier, target, "proof_of", "unresolved" if unresolved else "declared", evidence)
                else:
                    edge(identifier, target, "references", "unresolved" if unresolved else "observed", evidence)

        for declaration in block.get("lean_declarations", []):
            target = "lean:" + project_id + ":" + quote(declaration, safe="._-")
            if target not in nodes:
                add_node({"id": target, "kind": "lean_declaration", "title": declaration, "origin": "parser",
                          "data": {"declaration": declaration, "project_revision": None, "build_evidence": None,
                                   "mapping_status": "author_declared", "proof_status": "not_checked"}})
            edge(target, identifier, "formalizes", "declared", {"method": "latex_lean", "source": block["source"]})

    # A neighbouring proof is a candidate association, never a verified claim.
    for block in blocks:
        if block["kind"] != "proof":
            continue
        proof_id = key_to_id[block["key"]]
        if any(e["source"] == proof_id and e["relation"] == "proof_of" for e in edges):
            continue
        previous = [b for b in blocks if b["kind"] in STATEMENTS
                    and b["source"]["path"] == block["source"]["path"]
                    and b.get("parent_key") == block.get("parent_key")
                    and b["source"]["char_end"] <= block["source"]["char_start"]]
        if previous:
            statement = max(previous, key=lambda b: b["source"]["char_end"])
            gap = files[block["source"]["path"]]["text"][statement["source"]["char_end"]:block["source"]["char_start"]]
            if not re.sub(r"(?m)(?<!\\)%[^\r\n]*", "", gap).strip():
                edge(proof_id, key_to_id[statement["key"]], "proof_of_candidate", "candidate",
                     {"method": "adjacent_statement", "source": block["source"]})

    # Resources are asset references, not interpreted numeric datasets.
    for resource in parsed.get("resources", []):
        key = resource.get("path") or resource["literal"]
        identifier = "asset:" + project_id + ":" + quote(key, safe="/._-:")
        if identifier not in nodes:
            add_node({"id": identifier, "kind": "asset", "title": resource["literal"], "origin": "parser",
                      "data": {"resource_kind": resource["kind"], "path": resource.get("path"),
                               "sha256": resource.get("sha256"), "size_bytes": resource.get("size_bytes"),
                               "resolution_status": "resolved_path" if resource.get("path") else "unresolved"}})
        owner = key_to_id.get(resource.get("block_key"), file_id(resource["source"]["path"]))
        edge(owner, identifier, "uses_resource", evidence={"source": resource["source"]})

    # Import an existing JSON record catalog without interpreting its numerical claims.
    catalog = catalog or []
    for record in catalog:
        add_node({"id": record["id"], "kind": record.get("kind", "data_entity"), "origin": "catalog",
                  "title": record.get("title", record["id"]), "data": {"record": record},
                  "review_status": "imported", "verification_status": "imported_claim_not_rechecked"})
    for record in catalog:
        for ref in record.get("refs", []):
            if ref["target_id"] in nodes:
                edge(record["id"], ref["target_id"], "catalog:" + ref["relation"], "declared",
                     {"method": "catalog_record", "record_id": record["id"]})
            else:
                diag("catalog_missing_target", f"{record['id']} refers to missing {ref['target_id']}")

    annotations = annotations or {}
    if annotations and annotations.get("schema_version") != "qecgraph.annotations.v1":
        raise ValueError("Expected annotation schema_version qecgraph.annotations.v1")

    def selector(value):
        if value in nodes:
            return value
        if value.startswith("label:"):
            label = value.removeprefix("label:")
            if len(labels.get(label, [])) == 1:
                return labels[label][0]
            raise ValueError(f"Annotation label is missing or ambiguous: {label}")
        raise ValueError(f"Unknown annotation node: {value}")

    for node in annotations.get("nodes", []):
        if not {"id", "kind", "title"} <= node.keys():
            raise ValueError("Annotation nodes require id, kind and title")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", node["kind"]):
            raise ValueError("Invalid annotation node kind")
        add_node({"id": node["id"], "kind": node["kind"], "title": node["title"], "origin": "sidecar",
                  "data": node.get("data", {}), "review_status": "declared",
                  "verification_status": "not_rechecked"})
        for label in node.get("source_labels", []):
            try:
                source = selector("label:" + label)
            except ValueError as exc:
                diag("annotation_unresolved", str(exc))
                continue
            edge(source, node["id"], "describes", "declared", {"method": "sidecar", "source_label": label})

    for annotation in annotations.get("annotations", []):
        try:
            target = selector(annotation["target"])
        except ValueError as exc:
            diag("annotation_unresolved", str(exc))
            continue
        expected = annotation.get("expected_content_sha256")
        expected_context = annotation.get("expected_project_source_hash")
        is_stale = ((expected is not None and expected != nodes[target]["content_sha256"])
                    or (expected_context is not None and expected_context != project_source_hash))
        requested_status = annotation.get("review_status", "draft")
        status = "stale" if is_stale else requested_status
        if requested_status == "reviewed" and (not expected or not expected_context):
            status = "unbound_review"
            diag("review_not_bound", "A reviewed annotation must bind both content and project source hashes", nodes[target]["source"])
        if is_stale:
            diag("stale_annotation", f"Stored review no longer matches {target}", nodes[target]["source"])
        nodes[target].setdefault("annotations", []).append({**annotation, "effective_status": status})

    for item in annotations.get("edges", []):
        relation = item["relation"]
        if relation not in KNOWN_RELATIONS:
            raise ValueError(f"Unknown sidecar relation {relation!r}; extend the documented schema explicitly")
        try:
            source, target = selector(item["source"]), selector(item["target"])
        except ValueError as exc:
            diag("annotation_unresolved", str(exc))
            continue
        bindings = item.get("expected_hashes", {})
        expected_context = item.get("expected_project_source_hash")
        stale = bool(expected_context and expected_context != project_source_hash)
        for endpoint in (source, target):
            if endpoint in bindings and bindings[endpoint] != nodes[endpoint]["content_sha256"]:
                stale = True
        status = "stale" if stale else "declared"
        if relation == "depends_on_reviewed" and (not expected_context or not all(x in bindings for x in (source, target))):
            status = "unbound_review"
            diag("review_not_bound", "Reviewed dependency requires endpoint and project hashes")
        edge(source, target, relation, status, {"method": "sidecar", "annotation": item})
        if stale:
            diag("stale_annotation", f"Edge {source} -> {target} needs review")

    # Lift references/uses from a proof to its proposed/declared statement.
    proof_links = [e for e in edges if e["relation"] in {"proof_of", "proof_of_candidate"}
                   and e["status"] not in {"stale", "unresolved", "unbound_review"}]
    for link in proof_links:
        proof_id, statement_id = link["source"], link["target"]
        proof_children = {proof_id}
        while True:
            extended = proof_children | {e["target"] for e in edges
                                         if e["relation"] == "contains" and e["source"] in proof_children
                                         and e["status"] not in {"stale", "unbound_review", "unresolved"}}
            if extended == proof_children:
                break
            proof_children = extended
        for reference in list(edges):
            if reference["source"] not in proof_children or reference["relation"] not in {"references", "depends_on_declared"}:
                continue
            if reference["target"] == statement_id or reference["status"] in {"stale", "unbound_review", "unresolved"}:
                continue
            declared = reference["relation"] == "depends_on_declared" and link["relation"] == "proof_of"
            edge(statement_id, reference["target"], "depends_on_declared" if declared else "depends_on_candidate",
                 "declared" if declared else "candidate",
                 {"method": "via_proof", "proof_id": proof_id, "proof_link_id": link["id"], "reference_id": reference["id"]})

    for node in nodes.values():
        node["revision"] = hash_text(canonical({"content": node["content_sha256"], "source": node["source"],
                                                "semantic_context": project_source_hash}))
    graph = {"schema_version": "qecgraph.graph.v1", "tool_version": __version__, "project_id": project_id,
             "project_source_hash": project_source_hash, "entry": parsed["entry"],
             "nodes": sorted(nodes.values(), key=lambda x: x["id"]),
             "edges": sorted(edges, key=lambda x: x["id"]),
             "labels": dict(sorted(labels.items())), "diagnostics": diagnostics,
             "extraction_status": "partial" if any(d["severity"] == "error" for d in diagnostics) else "complete_for_supported_syntax",
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
