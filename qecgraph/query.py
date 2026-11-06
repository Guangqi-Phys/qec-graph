"""Bounded, JSON-friendly queries over an extraction snapshot."""
from __future__ import annotations

import json
import sqlite3
from collections import deque

from .graph import CANDIDATES, DEPENDENCIES
from .store import load_graph


def resolve(graph, identifier):
    nodes = {n["id"]: n for n in graph["nodes"]}
    if identifier in nodes:
        return identifier
    label = identifier.removeprefix("label:")
    matches = graph["labels"].get(label, [])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous label {label!r}; choose an exact node ID: {matches}")
    raise ValueError(f"Unknown node or label: {identifier}")


def search(store, query, kind=None, limit=20):
    graph, snapshot = load_graph(store)
    con = sqlite3.connect((snapshot / "graph.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if not query.strip():
        raise ValueError("Search query must not be empty")
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    try:
        literal = '"' + query.replace('"', '""') + '"'
        sql = "SELECT n.id,n.kind,n.title,n.source_path,n.line_start,bm25(node_fts) AS score FROM node_fts JOIN nodes n ON n.id=node_fts.id WHERE node_fts MATCH ?"
        params = [literal]
        if kind:
            sql += " AND n.kind=?"
            params.append(kind)
        sql += " ORDER BY score,n.id LIMIT ?"
        params.append(limit)
        rows = [dict(row) for row in con.execute(sql, params)]
        # Deterministic substring fallback also helps unsegmented Chinese and symbols.
        if len(rows) < limit:
            pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql = "SELECT id,kind,title,source_path,line_start,NULL AS score FROM nodes WHERE (title LIKE ? ESCAPE '\\' OR payload LIKE ? ESCAPE '\\')"
            params = [pattern, pattern]
            if kind:
                sql += " AND kind=?"
                params.append(kind)
            sql += " ORDER BY id LIMIT ?"
            params.append(limit)
            seen = {r["id"] for r in rows}
            for row in con.execute(sql, params):
                if row["id"] not in seen:
                    rows.append(dict(row))
                    seen.add(row["id"])
                if len(rows) >= limit:
                    break
    finally:
        con.close()
    return {"snapshot_id": graph["snapshot_id"], "extraction_status": graph["extraction_status"],
            "query": query, "results": rows,
            "method": "FTS5 literal phrase followed by substring fallback; no semantic embedding"}


def show(store, identifier):
    graph, _ = load_graph(store)
    node_id = resolve(graph, identifier)
    node = next(n for n in graph["nodes"] if n["id"] == node_id)
    return {"snapshot_id": graph["snapshot_id"], "node": node,
            "outgoing": [e for e in graph["edges"] if e["source"] == node_id],
            "incoming": [e for e in graph["edges"] if e["target"] == node_id]}


def traverse(graph, root, depth, include_candidates=False, reverse=False, max_nodes=100):
    relations = DEPENDENCIES | (CANDIDATES if include_candidates else set())
    permitted = [e for e in graph["edges"] if e["relation"] in relations
                 and e["status"] not in {"stale", "unbound_review", "unresolved"}]
    visited, selected, queue, omitted = {root}, [], deque([(root, 0)]), set()
    while queue:
        current, level = queue.popleft()
        if level >= depth:
            continue
        for edge in permitted:
            source, target = (edge["target"], edge["source"]) if reverse else (edge["source"], edge["target"])
            if source != current:
                continue
            if target not in visited:
                if len(visited) >= max_nodes:
                    omitted.add(target)
                    continue
                visited.add(target)
                queue.append((target, level + 1))
            if edge not in selected:
                selected.append(edge)
    return visited, selected, omitted


def dependencies(store, identifier, depth=3, include_candidates=False, reverse=False, max_nodes=100):
    if not 0 <= depth <= 20 or not 1 <= max_nodes <= 1000:
        raise ValueError("depth must be 0..20 and max_nodes 1..1000")
    graph, _ = load_graph(store)
    root = resolve(graph, identifier)
    ids, edges, omitted = traverse(graph, root, depth, include_candidates, reverse, max_nodes)
    return {"snapshot_id": graph["snapshot_id"], "root_id": root,
            "direction": "potential_impact" if reverse else "dependencies", "include_candidates": include_candidates,
            "nodes": [n for n in graph["nodes"] if n["id"] in ids], "edges": edges,
            "truncated": bool(omitted), "omitted_frontier_count": len(omitted),
            "note": "Declared/reviewed document dependencies, not a complete or Lean-verified proof graph."}


def context(store, identifier, depth=2, include_candidates=False, max_nodes=60):
    if not 0 <= depth <= 20 or not 1 <= max_nodes <= 1000:
        raise ValueError("depth must be 0..20 and max_nodes 1..1000")
    graph, _ = load_graph(store)
    root = resolve(graph, identifier)
    def eligible(edge):
        if edge["status"] in {"stale", "unbound_review", "unresolved"}:
            return False
        if not include_candidates and (edge["status"] == "candidate" or edge["relation"].endswith("_candidate")):
            return False
        return True
    ids, _, omitted = traverse(graph, root, depth, include_candidates, False, max_nodes)
    candidates = list(sorted(ids - {root}))
    chosen = [root] + candidates
    # Include proof text and its dependencies even when no direct theorem edge exists.
    proof_relations = {"proof_of"} | ({"proof_of_candidate"} if include_candidates else set())
    for edge in graph["edges"]:
        if edge["target"] in ids and edge["relation"] in proof_relations and edge["status"] not in {"stale", "unbound_review", "unresolved"}:
            if edge["source"] not in chosen:
                chosen.append(edge["source"])
                proof_ids, _, extra_omitted = traverse(graph, edge["source"], depth, include_candidates, False, max_nodes)
                chosen.extend(x for x in sorted(proof_ids) if x not in chosen)
                omitted |= extra_omitted
    contextual = {"references", "cites", "uses_resource", "describes", "about", "supports", "formalizes",
                  "has_matrix", "has_presentation", "generated_by", "uses_circuit", "uses_noise",
                  "uses_decoder", "instance_of", "reports"}
    frontier = set(chosen)
    for _ in range(depth):
        next_frontier = set()
        for edge in graph["edges"]:
            relevant = edge["relation"] in contextual or edge["relation"].startswith("catalog:")
            if relevant and eligible(edge) and (edge["source"] in frontier or edge["target"] in frontier):
                for endpoint in (edge["source"], edge["target"]):
                    if endpoint not in chosen:
                        chosen.append(endpoint)
                        next_frontier.add(endpoint)
        frontier = next_frontier
        if not frontier:
            break
    # Add structural ancestors, but do not add their unrelated children.
    changed = True
    while changed:
        changed = False
        for edge in graph["edges"]:
            if edge["relation"] == "contains" and edge["target"] in chosen and edge["source"] not in chosen and edge["status"] not in {"stale", "unbound_review", "unresolved"}:
                chosen.append(edge["source"])
                changed = True
    truncated = len(chosen) > max_nodes or bool(omitted)
    selected = set(chosen[:max_nodes])
    lookup = {n["id"]: n for n in graph["nodes"]}
    selected_nodes = []
    excluded_annotations = 0
    for identifier in chosen[:max_nodes]:
        node = dict(lookup[identifier])
        if "annotations" in node:
            usable = [a for a in node["annotations"] if a["effective_status"] not in {"stale", "unbound_review"}]
            excluded_annotations += len(node["annotations"]) - len(usable)
            node["annotations"] = usable
        selected_nodes.append(node)
    return {"snapshot_id": graph["snapshot_id"], "project_source_hash": graph["project_source_hash"],
            "root_id": root, "include_candidates": include_candidates,
            "nodes": selected_nodes,
            "edges": [e for e in graph["edges"] if e["source"] in selected and e["target"] in selected and eligible(e)],
            "excluded_stale_or_unbound_annotations": excluded_annotations,
            "truncated": truncated, "omitted_node_count_at_least": max(0, len(chosen)-max_nodes)+len(omitted),
            "extraction_status": graph["extraction_status"],
            "note": "Whole extracted blocks with source locations; hypotheses are not semantically completed by this tool."}
