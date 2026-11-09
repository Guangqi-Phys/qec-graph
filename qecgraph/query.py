"""Bounded, JSON-friendly queries over an extraction snapshot."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque

from .graph import CANDIDATES, DEPENDENCIES
from .store import load_graph, snapshot_database
from .status import annotation_eligible, eligible


def answer_node(original, include_candidates=False):
    """Whole statement/data with effective relations, rather than raw audit duplicates."""
    node = dict(original)
    excluded = 0
    if 'annotations' in node:
        usable = [a for a in node['annotations'] if annotation_eligible(a, include_candidates)]
        excluded = len(node['annotations']) - len(usable)
        node['annotations'] = usable
    if 'record' in node:
        record = node['record']
        keys = ('schema_version', 'id', 'kind', 'revision', 'content_sha256', 'hash_protocol',
                'provenance', 'assets', 'evidence_ids')
        node['record'] = {key: record[key] for key in keys}
        node['record_projection'] = 'Identity/provenance metadata; full data is in node.data; eligible relations are in edges; raw extensions/refs/review are available via audit show'
    return node, excluded


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
    if not query.strip():
        raise ValueError("Search query must not be empty")
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if snapshot is None:
        matches = [n for n in graph['nodes'] if (not kind or n['kind'] == kind)
                   and query.casefold() in (n['title'] + '\n' + n['latex'] + '\n' + json.dumps(n['data'], ensure_ascii=False)
                                           + '\n' + ' '.join(n['labels'])).casefold()]
        matches.sort(key=lambda n: n['id'])
        return {'snapshot_id': graph['snapshot_id'], 'extraction_status': graph['extraction_status'],
                'query': query, 'results': [{'id': n['id'], 'kind': n['kind'], 'title': n['title'],
                                           'source': n.get('source'), 'provenance': n.get('provenance'),
                                           'review_status': n['review_status'], 'verification_status': n['verification_status'],
                                           **({'build_binding': n['build_binding']} if 'build_binding' in n else {})}
                                          for n in matches[:limit]],
                'truncated': len(matches) > limit, 'method': 'deterministic corpus substring; no embedding'}
    with snapshot_database(snapshot) as con:
        con.row_factory = sqlite3.Row
        literal = '"' + query.replace('"', '""') + '"'
        sql = "SELECT n.id,n.kind,n.title,n.source_path,n.line_start,bm25(node_fts) AS score FROM node_fts JOIN nodes n ON n.id=node_fts.id WHERE node_fts MATCH ?"
        params = [literal]
        if kind:
            sql += " AND n.kind=?"
            params.append(kind)
        sql += " ORDER BY score,n.id LIMIT ?"
        params.append(limit + 1)
        rows = [dict(row) for row in con.execute(sql, params)]
        # Deterministic substring fallback also helps unsegmented Chinese and symbols.
        if len(rows) < limit + 1:
            pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql = "SELECT id,kind,title,source_path,line_start,NULL AS score FROM nodes WHERE (title LIKE ? ESCAPE '\\' OR payload LIKE ? ESCAPE '\\')"
            params = [pattern, pattern]
            if kind:
                sql += " AND kind=?"
                params.append(kind)
            sql += " ORDER BY id LIMIT ?"
            params.append(limit + 1)
            seen = {r["id"] for r in rows}
            for row in con.execute(sql, params):
                if row["id"] not in seen:
                    rows.append(dict(row))
                    seen.add(row["id"])
                if len(rows) >= limit + 1:
                    break
    return {"snapshot_id": graph["snapshot_id"], "extraction_status": graph["extraction_status"],
            "query": query, "results": rows[:limit], 'truncated': len(rows) > limit,
            "method": "FTS5 literal phrase followed by substring fallback; no semantic embedding"}


def show(store, identifier):
    graph, _ = load_graph(store)
    node_id = resolve(graph, identifier)
    node = next(n for n in graph["nodes"] if n["id"] == node_id)
    return {"snapshot_id": graph["snapshot_id"], "node": node,
            "outgoing": [e for e in graph["edges"] if e["source"] == node_id],
            "incoming": [e for e in graph["edges"] if e["target"] == node_id]}


def traverse(graph, root, depth, include_candidates=False, reverse=False, max_nodes=100):
    return _walk_dependencies(_dependency_adjacency(graph, include_candidates, reverse), root, depth, max_nodes)


def _dependency_adjacency(graph, include_candidates, reverse=False):
    relations = DEPENDENCIES | CANDIDATES if include_candidates else DEPENDENCIES
    source_key, target_key = ('target', 'source') if reverse else ('source', 'target')
    adjacent = defaultdict(list)
    for edge in graph["edges"]:
        if edge["relation"] in relations and eligible(edge, include_candidates):
            adjacent[edge[source_key]].append((edge[target_key], edge))
    return adjacent


def _walk_dependencies(adjacent, root, depth, max_nodes):
    visited, selected, queue, omitted = {root}, [], deque([(root, 0)]), set()
    selected_by_id = {}
    while queue:
        current, level = queue.popleft()
        if level >= depth:
            omitted.update(target for target, _ in adjacent.get(current, ()) if target not in visited)
            continue
        for target, edge in adjacent.get(current, ()):
            if target not in visited:
                if len(visited) >= max_nodes:
                    omitted.add(target)
                    continue
                visited.add(target)
                queue.append((target, level + 1))
            identifier = edge.get('id')
            first = selected_by_id.get(identifier)
            if first is None:
                selected_by_id[identifier] = edge
                selected.append(edge)
            elif first != edge and edge not in selected:
                # An audit graph can contain different evidence under a repeated ID.
                selected.append(edge)
    return visited, selected, omitted - visited


def dependencies(store, identifier, depth=3, include_candidates=False, reverse=False, max_nodes=100):
    if not 0 <= depth <= 20 or not 1 <= max_nodes <= 1000:
        raise ValueError("depth must be 0..20 and max_nodes 1..1000")
    graph, _ = load_graph(store)
    root = resolve(graph, identifier)
    ids, edges, omitted = traverse(graph, root, depth, include_candidates, reverse, max_nodes)
    projected = [answer_node(n, include_candidates) for n in graph['nodes'] if n['id'] in ids]
    return {"snapshot_id": graph["snapshot_id"], "root_id": root,
            "direction": "potential_impact" if reverse else "dependencies", "include_candidates": include_candidates,
            "nodes": [item[0] for item in projected], "edges": edges,
            'excluded_ineligible_annotations': sum(item[1] for item in projected),
            "truncated": bool(omitted), "omitted_frontier_count": len(omitted),
            "note": "Document declared/reviewed edges and separately named actual Lean constant edges; bounded scope, not semantic equivalence of a paper and Lean type."}


def context(store, identifier, depth=2, include_candidates=False, max_nodes=60):
    if not 0 <= depth <= 20 or not 1 <= max_nodes <= 1000:
        raise ValueError("depth must be 0..20 and max_nodes 1..1000")
    graph, _ = load_graph(store)
    root = resolve(graph, identifier)
    adjacent = _dependency_adjacency(graph, include_candidates)
    ids, _, omitted = _walk_dependencies(adjacent, root, depth, max_nodes)
    candidates = list(sorted(ids - {root}))
    chosen = [root] + candidates
    chosen_ids = set(chosen)
    # Include proof text and its dependencies even when no direct theorem edge exists.
    proof_relations = {"proof_of"} | ({"proof_of_candidate"} if include_candidates else set())
    for edge in graph["edges"]:
        if edge["target"] in ids and edge["relation"] in proof_relations and eligible(edge, include_candidates):
            if edge["source"] not in chosen_ids:
                chosen.append(edge["source"])
                chosen_ids.add(edge["source"])
                proof_ids, _, extra_omitted = _walk_dependencies(adjacent, edge["source"], depth, max_nodes)
                additional = sorted(proof_ids - chosen_ids)
                chosen.extend(additional)
                chosen_ids.update(additional)
                omitted |= extra_omitted
    contextual = {"references", "cites", "uses_resource", "describes", "about", "supports", "formalizes",
                  "has_matrix", "has_presentation", "generated_by", "uses_circuit", "uses_noise",
                  "uses_decoder", "instance_of", "reports", "normalizes_to", 'maps_declaration', 'has_build_evidence',
                  'maps_source_occurrence'}
    frontier = chosen_ids.copy()
    for _ in range(depth):
        next_frontier = set()
        for edge in graph["edges"]:
            relevant = edge["relation"] in contextual or edge["relation"].startswith("catalog:")
            if relevant and eligible(edge, include_candidates) and (edge["source"] in frontier or edge["target"] in frontier):
                for endpoint in (edge["source"], edge["target"]):
                    if endpoint not in chosen_ids:
                        chosen.append(endpoint)
                        chosen_ids.add(endpoint)
                        next_frontier.add(endpoint)
        frontier = next_frontier
        if not frontier:
            break
    # Add structural ancestors, but do not add their unrelated children.
    changed = True
    while changed:
        changed = False
        for edge in graph["edges"]:
            if (edge["relation"] == "contains" and edge["target"] in chosen_ids and edge["source"] not in chosen_ids
                    and eligible(edge, include_candidates)):
                chosen.append(edge["source"])
                chosen_ids.add(edge["source"])
                changed = True
    truncated = len(chosen) > max_nodes or bool(omitted)
    selected = set(chosen[:max_nodes])
    lookup = {n["id"]: n for n in graph["nodes"]}
    selected_nodes = []
    excluded_annotations = 0
    for identifier in chosen[:max_nodes]:
        node, excluded = answer_node(lookup[identifier], include_candidates)
        excluded_annotations += excluded
        selected_nodes.append(node)
    return {"snapshot_id": graph["snapshot_id"], "project_source_hash": graph["project_source_hash"],
            "root_id": root, "include_candidates": include_candidates,
            "nodes": selected_nodes,
            "edges": [e for e in graph["edges"] if e["source"] in selected and e["target"] in selected and eligible(e, include_candidates)],
            "excluded_stale_or_unbound_annotations": excluded_annotations,
            "truncated": truncated, "omitted_node_count_at_least": max(0, len(chosen)-max_nodes)+len(omitted),
            "extraction_status": graph["extraction_status"],
            "note": "Whole extracted blocks with source locations; hypotheses are not semantically completed by this tool."}
