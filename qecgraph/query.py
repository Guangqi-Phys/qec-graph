"""Bounded, JSON-friendly queries over an extraction snapshot."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator
from functools import cached_property
from itertools import islice

from .core.graph import CANDIDATES, DEPENDENCIES
from .store import load_graph, snapshot_database
from .domain.status import annotation_eligible, eligible


class SelectionError(ValueError):
    def __init__(self, code, message, details):
        super().__init__(message)
        self.code, self.details = code, details


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
        keys = ('schema', 'id', 'kind', 'revision', 'content_sha256', 'hash_protocol',
                'provenance', 'assets', 'evidence_ids')
        node['record'] = {key: record[key] for key in keys}
        node['record_projection'] = 'Identity/provenance metadata; full data is in node.data; eligible relations are in edges; raw extensions/refs/review are available via audit show'
    return node, excluded


def resolve(graph, identifier, *, nodes=None):
    if nodes is None:
        nodes = {n["id"]: n for n in graph["nodes"]}
    if identifier in nodes:
        return identifier
    label = identifier.removeprefix("label:")
    matches = graph["labels"].get(label, [])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        candidates = sorted(matches)[:20]
        raise SelectionError('AMBIGUOUS_SELECTOR', f"Ambiguous label {label!r}; choose an exact node ID: {candidates}",
                             {'label': label, 'candidate_ids': candidates, 'candidate_count': len(matches),
                              'truncated': len(candidates) < len(matches)})
    raise SelectionError('NOT_FOUND', f"Unknown node or label: {identifier}", {'identifier': identifier})


def resolve_node(graph, identifier):
    nodes = {node["id"]: node for node in graph["nodes"]}
    return nodes[resolve(graph, identifier, nodes=nodes)]


def _serialize_search_data(data):
    return json.dumps(data, ensure_ascii=False)


class GraphTextIndex:
    """Deterministic substring matching for a captured graph projection."""

    def __init__(self, nodes: Iterable[dict], *,
                 serialize_data: Callable[[dict], str] = _serialize_search_data) -> None:
        self.nodes = sorted(nodes, key=lambda node: node['id'])
        self._serialize_data = serialize_data
        self._text: dict[str, str] = {}

    def matching(self, query: str, kind: str | None = None) -> Iterator[dict]:
        needle = query.casefold()
        for node in self.nodes:
            if kind and node['kind'] != kind:
                continue
            identifier = node['id']
            text = self._text.get(identifier)
            if text is None:
                text = '\n'.join((node['title'], node['latex'], self._serialize_data(node['data']),
                                  ' '.join(node['labels']))).casefold()
                self._text[identifier] = text
            if needle in text:
                yield node


def search_node_summary(node, *, include_build_binding=False):
    row = {key: node.get(key) for key in ('id', 'kind', 'title', 'source', 'provenance',
                                        'review_status', 'verification_status')}
    if include_build_binding and 'build_binding' in node:
        row['build_binding'] = node['build_binding']
    return row


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


class QuerySession:
    """Common queries over one captured graph or snapshot reference."""

    def __init__(self, source):
        self.source = source

    @cached_property
    def projection(self):
        return load_graph(self.source)

    @cached_property
    def node_ids(self):
        return {node['id'] for node in self.projection[0]['nodes']}

    def corpus_identifier(self, identifier, source_version_id):
        if identifier in self.node_ids or '::' in identifier:
            return identifier
        if source_version_id:
            return source_version_id + '::' + identifier
        return None

    def execute(self, action, identifier=None, *, text=None, kind=None, limit=20, depth=2,
                include_candidates=False, max_nodes=60):
        if action == 'search':
            return self.search(text, kind, limit)
        if action == 'show':
            return self.show(identifier)
        if action == 'context':
            return self.context(identifier, depth, include_candidates, max_nodes)
        if action in {'deps', 'impact'}:
            return self.deps(identifier, depth, include_candidates, action == 'impact', max_nodes)
        raise ValueError('Unknown read-only graph action')

    def search(self, query, kind=None, limit=20):
        graph, snapshot = self.projection
        if not query.strip():
            raise ValueError("Search query must not be empty")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if snapshot is None:
            index = GraphTextIndex(graph['nodes'])
            matches = list(islice(index.matching(query, kind), limit + 1))
            return {'snapshot_id': graph['snapshot_id'], 'extraction_status': graph['extraction_status'],
                    'query': query, 'results': [search_node_summary(node, include_build_binding=True) for node in matches[:limit]],
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

    def show(self, identifier):
        graph, _ = self.projection
        node = resolve_node(graph, identifier)
        node_id = node["id"]
        outgoing, incoming = [], []
        for edge in graph["edges"]:
            if edge["source"] == node_id:
                outgoing.append(edge)
            if edge["target"] == node_id:
                incoming.append(edge)
        return {"snapshot_id": graph["snapshot_id"], "node": node,
                "outgoing": outgoing, "incoming": incoming}

    def deps(self, identifier, depth=3, include_candidates=False, reverse=False, max_nodes=100):
        if not 0 <= depth <= 20 or not 1 <= max_nodes <= 1000:
            raise ValueError("depth must be 0..20 and max_nodes 1..1000")
        graph, _ = self.projection
        root = resolve(graph, identifier)
        ids, edges, omitted = traverse(graph, root, depth, include_candidates, reverse, max_nodes)
        projected = [answer_node(n, include_candidates) for n in graph['nodes'] if n['id'] in ids]
        return {"snapshot_id": graph["snapshot_id"], "root_id": root,
                "direction": "potential_impact" if reverse else "dependencies", "include_candidates": include_candidates,
                "nodes": [item[0] for item in projected], "edges": edges,
                'excluded_ineligible_annotations': sum(item[1] for item in projected),
                "truncated": bool(omitted), "omitted_frontier_count": len(omitted),
                "note": "Document declared/reviewed edges and separately named actual Lean constant edges; bounded scope, not semantic equivalence of a paper and Lean type."}

    def context(self, identifier, depth=2, include_candidates=False, max_nodes=60):
        if not 0 <= depth <= 20 or not 1 <= max_nodes <= 1000:
            raise ValueError("depth must be 0..20 and max_nodes 1..1000")
        graph, _ = self.projection
        lookup = {n["id"]: n for n in graph["nodes"]}
        root = resolve(graph, identifier, nodes=lookup)
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
                      "has_matrix", "has_check_matrix", "generated_by", "uses_circuit", "uses_noise",
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


def search(store, query, kind=None, limit=20):
    return QuerySession(store).search(query, kind, limit)


def show(store, identifier):
    return QuerySession(store).show(identifier)


def dependencies(store, identifier, depth=3, include_candidates=False, reverse=False, max_nodes=100):
    return QuerySession(store).deps(identifier, depth, include_candidates, reverse, max_nodes)


def context(store, identifier, depth=2, include_candidates=False, max_nodes=60):
    return QuerySession(store).context(identifier, depth, include_candidates, max_nodes)
