"""Lossless TeX syntax conversion after compilation; no scientific classifications."""

from __future__ import annotations

from pathlib import PurePosixPath
import re

from pylatexenc.latexwalker import LatexWalker, LatexWalkerParseError

from .contract import digest, json_bytes, SourceIndex
from .references import group
from ..source.assembly import (
    assemble_files,
    EntryCoordinates,
    entry_source_spans,
    document_bounds,
    condition_regions,
)
from ..source.syntax import declaration_context

HEADINGS = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
    "subparagraph": 6,
}
CITES = {
    "cite",
    "citep",
    "citet",
    "citealt",
    "citealp",
    "autocite",
    "parencite",
    "textcite",
    "footcite",
    "nocite",
}
TABLES = {"tabular", "tabular*", "tabularx", "longtable", "array"}
ASSETS = {
    ".pdf",
    ".eps",
    ".ps",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".csv",
    ".dat",
    ".mtx",
}


def _children(node):
    children = list(getattr(node, "nodelist", None) or [])
    arguments = getattr(getattr(node, "nodeargd", None), "argnlist", None) or []
    children.extend(n for n in arguments if n is not None)
    return sorted(children, key=lambda n: n.pos)


def _arguments(node, text):
    return [
        text[n.pos : n.pos + n.len] if n else None
        for n in (getattr(getattr(node, "nodeargd", None), "argnlist", None) or [])
    ]


def _token_name(node):
    return getattr(node, "macroname", None) or getattr(node, "environmentname", None)


class _Syntax:
    def __init__(self, tree, assembly, coordinates, parse_text):
        self.tree, self.assembly, self.coordinates, self.parse_text = (
            tree,
            assembly,
            coordinates,
            parse_text,
        )
        self.text, self.tree_hash = assembly.text, tree.digest
        self.nodes, self.indices, self.source_names = [], {}, set()
        _, self.body_start, self.body_end = document_bounds(self.text)

    def roots(self, parsed, diagnostics):
        roots, cursor = [], 0
        for node in parsed:
            start = self.coordinates.to_entry(node.pos)
            if cursor < start:
                roots.append(
                    _opaque_node(
                        self.assembly, self.tree, cursor, start, self.nodes, diagnostics
                    )
                )
            identifier = self.add(node)
            if identifier:
                roots.append(identifier)
                cursor = self.coordinates.to_entry(node.pos + node.len)
        if cursor < len(self.text):
            roots.append(
                _opaque_node(
                    self.assembly,
                    self.tree,
                    cursor,
                    len(self.text),
                    self.nodes,
                    diagnostics,
                )
            )
        return roots

    def add(self, node, parent=None, depth=0):
        if depth > 128 or len(self.nodes) >= 200000:
            raise ValueError("Material token depth/count limit exceeded")
        start = self.coordinates.to_entry(node.pos)
        end = self.coordinates.to_entry(node.pos + node.len)
        if start >= end:
            return None
        name = _token_name(node)
        spans = []
        for path, a, b in entry_source_spans(self.assembly, start, end):
            if path not in self.indices:
                self.indices[path] = SourceIndex(self.tree.files[path])
            spans.append(self.indices[path].span(path, a, b))
        self.source_names.update((s["path"] for s in spans))
        identifier = (
            "syntax:"
            + digest(
                json_bytes([self.tree_hash, start, end, type(node).__name__, name])
            )[:24]
        )
        kind = type(node).__name__.removeprefix("Latex").removesuffix("Node").lower()
        item = {
            "id": identifier,
            "kind": kind,
            "name": name,
            "range": [start, end],
            "parent": parent,
            "children": [],
            "source_spans": spans,
            "arguments": _arguments(node, self.parse_text),
            "region": "preamble"
            if self.body_start is not None and end <= self.body_start
            else "inactive"
            if self.body_end is not None and start >= self.body_end
            else "body",
        }
        self.nodes.append(item)
        for child in _children(node):
            child_id = self.add(child, identifier, depth + 1)
            if child_id:
                item["children"].append(child_id)
        if kind == "math":
            item["math_tex"] = self.text[start:end]
            item["display"] = getattr(node, "displaytype", None)
        if kind == "environment" and name in TABLES:
            item["rows"] = _table_rows(node, self.text, self.coordinates)
        return identifier


def _parse_nodes(text, diagnostics):
    context = declaration_context()
    try:
        LatexWalker(
            text, latex_context=context, tolerant_parsing=False
        ).get_latex_nodes()
    except (LatexWalkerParseError, ValueError) as exc:
        diagnostics.append({"code": "syntax_incomplete", "message": str(exc)[:400]})
    return LatexWalker(
        text, latex_context=context, tolerant_parsing=True
    ).get_latex_nodes()[0]


def convert_source(tree, entry, references, *, used_files=()):
    """Preserve all source tokens, math and author markup in a versioned material tree.

    This adapter does not promise arbitrary macro expansion. Runtime citation and
    numbering observations remain separate from exact original TeX source spans.
    """
    assembly = assemble_files(tree.files, entry)
    text = assembly.text
    coordinates = EntryCoordinates(assembly)
    parse_text = coordinates.copy_text()
    diagnostics = list(assembly.diagnostics)
    parsed = _parse_nodes(parse_text, diagnostics)
    syntax = _Syntax(tree, assembly, coordinates, parse_text)
    roots = syntax.roots(parsed, diagnostics)
    nodes, source_names = syntax.nodes, syntax.source_names
    body_start, body_end = syntax.body_start, syntax.body_end
    outline = _outline(nodes)
    citations = _citations(nodes, references, diagnostics, text, assembly, tree)
    assets = _assets(tree, nodes, set(used_files))
    unresolved_assets = [
        n["id"]
        for n in nodes
        if n.get("asset_targets", {}).get("status") != "resolved"
        and "asset_targets" in n
    ]
    if unresolved_assets:
        diagnostics.append(
            {"code": "asset_target_unresolved", "nodes": unresolved_assets}
        )
    labels, cross_references = _cross_references(nodes)
    unresolved = [
        r
        for r in cross_references
        if r["region"] == "body"
        and any(t["status"] != "resolved" for t in r["targets"])
    ]
    if unresolved:
        diagnostics.append(
            {
                "code": "cross_reference_unresolved",
                "nodes": [r["node"] for r in unresolved],
            }
        )
    coverage = assembly.coverage()
    reasons = list(coverage["reasons"])
    if diagnostics:
        reasons.append("conversion_diagnostics")
    if body_start is None:
        reasons.append("nonstandard_document_body")
    conditional_ranges = _body_conditionals(
        parse_text, coordinates, body_start, body_end
    )
    if conditional_ranges:
        # A native build is one view. Never silently treat every source branch as active.
        reasons.append("conditional_view_not_mapped")
    document = {
        "schema": "qecgraph.prepared_syntax/1",
        "source_tree_sha256": tree.digest,
        "entry": entry,
        "roots": roots,
        "nodes": nodes,
        "outline": outline,
        "citations": citations,
        "assets": assets,
        "body_range": [body_start, body_end],
        "conditional_ranges": conditional_ranges,
        "capabilities": {
            "original_tex": True,
            "source_spans": "exact_copy",
            "arbitrary_macro_expansion": False,
            "table_cells": "syntactic",
            "scientific_records": False,
        },
        "files_not_in_reading_view": sorted(set(tree.files) - source_names),
    }
    document["reading_units"] = _reading_units(nodes, text, body_start, body_end)
    document["labels"], document["cross_references"] = labels, cross_references
    return (
        assembly,
        document,
        {
            "complete": not reasons,
            "reasons": sorted(set(reasons)),
            "diagnostics": diagnostics,
        },
    )


def _body_conditionals(parse_text, coordinates, start, end):
    inactive, uncertain = condition_regions(parse_text)
    ranges = [
        (coordinates.to_entry(a), coordinates.to_entry(b))
        for a, b in [*inactive, *uncertain]
    ]
    return [[a, b] for a, b in ranges if b > (start or 0) and (end is None or a < end)]


def _opaque_node(assembly, tree, start, end, nodes, diagnostics):
    identifier = "opaque:" + digest(json_bytes([tree.digest, start, end]))[:24]
    spans = [
        SourceIndex(tree.files[path]).span(path, a, b)
        for path, a, b in entry_source_spans(assembly, start, end)
    ]
    nodes.append(
        {
            "id": identifier,
            "kind": "opaque",
            "name": None,
            "range": [start, end],
            "parent": None,
            "children": [],
            "source_spans": spans,
            "arguments": [],
            "region": "unknown",
        }
    )
    diagnostics.append({"code": "unparsed_source_preserved", "range": [start, end]})
    return identifier


def _without_comments(text):
    return re.sub(r"(?m)(?<!\\)%[^\n]*", "", text)


def _outline(nodes):
    outline, stack = [], []
    for node in nodes:
        if (
            node["kind"] != "macro"
            or node["name"] not in HEADINGS
            or node["region"] != "body"
        ):
            continue
        level = HEADINGS[node["name"]]
        while stack and stack[-1][0] >= level:
            stack.pop()
        outline.append(
            {
                "node": node["id"],
                "level": level,
                "parent": stack[-1][1] if stack else None,
                "title_tex": next((a for a in reversed(node["arguments"]) if a), None),
            }
        )
        stack.append((level, node["id"]))
    return outline


def _reading_units(nodes, text, start, end):
    if start is None:
        return []
    end = end if end is not None else len(text)
    boundaries = {start, end}
    by_id = {n["id"]: n for n in nodes}
    atomic = {}
    for node in nodes:
        a, b = node["range"]
        parent = by_id.get(node["parent"], {})
        if not start <= a < b <= end or parent.get("name") != "document":
            continue
        if node["kind"] in {"environment", "math"} or node["name"] in HEADINGS:
            boundaries.update((a, b))
            atomic[(a, b)] = node["id"]
        elif node["kind"] == "chars":
            for match in re.finditer(r"\n\s*\n", text[a:b]):
                boundaries.add(a + match.end())
    points = sorted(boundaries)
    return [
        {
            "range": [a, b],
            "node": atomic.get((a, b)),
            "kind": "authored_structure" if (a, b) in atomic else "paragraph",
        }
        for a, b in zip(points, points[1:])
        if text[a:b].strip()
    ]


def _cross_references(nodes):
    labels, references = [], []
    for node in nodes:
        if node["kind"] != "macro" or node["name"] not in {
            "label",
            "ref",
            "eqref",
            "pageref",
            "autoref",
            "cref",
            "Cref",
        }:
            continue
        args = [a for a in node["arguments"] if a and a.startswith("{")]
        if not args:
            continue
        row = {
            "node": node["id"],
            "keys": [k.strip() for k in args[-1][1:-1].split(",")],
            "command": node["name"],
            "region": node["region"],
        }
        (labels if node["name"] == "label" else references).append(row)
    for row in references:
        row["targets"] = []
        for key in row["keys"]:
            matches = [
                n["node"] for n in labels if n["region"] == "body" and key in n["keys"]
            ]
            row["targets"].append(
                {
                    "key": key,
                    "nodes": matches,
                    "status": "resolved"
                    if len(matches) == 1
                    else "ambiguous"
                    if matches
                    else "unresolved",
                }
            )
    return labels, references


def _citations(nodes, references, diagnostics, text, assembly, tree):
    result, located = [], set()
    section_ids, section = {}, 0
    by_id = {n["id"]: n for n in nodes}
    for node in nodes:
        if node["kind"] == "environment" and node["name"] == "refsection":
            section += 1
            section_ids[node["id"]] = str(section)
        if (
            node["kind"] != "macro"
            or node["name"] not in CITES
            or node["region"] != "body"
        ):
            continue
        arguments = [a for a in node["arguments"] if a and a.startswith("{")]
        if not arguments:
            continue
        scope = "0"
        parent = node["parent"]
        while parent:
            if parent in section_ids:
                scope = section_ids[parent]
                break
            parent = by_id[parent]["parent"]
        keys = [k.strip() for k in _without_comments(arguments[-1][1:-1]).split(",")]
        for key in keys:
            if key == "*" or not key:
                continue
            located.add((scope, key))
            result.append(
                {
                    "node": node["id"],
                    "key": key,
                    "section": scope,
                    "call_tex": arguments[-1],
                    "origin": "literal_call",
                }
            )
    required = {(r["section"], r["key"]) for r in references["bindings"]}
    wrapped, wrapped_keys = _wrapper_calls(nodes, required, text, assembly, tree)
    result.extend(wrapped)
    located.update(wrapped_keys)
    missing = sorted(required - located)
    if missing:
        diagnostics.append(
            {
                "code": "expanded_citation_locations_unknown",
                "bindings": [list(v) for v in missing],
            }
        )
    return result


def _source_span_for_wrapper(tree, path, start, end):
    return SourceIndex(tree.files[path]).span(path, start, end)


def _citation_wrappers(nodes, text):
    wrappers, targets = {}, []
    for node in nodes:
        if node["kind"] != "macro" or node["name"] not in {
            "newcommand",
            "renewcommand",
            "providecommand",
        }:
            continue
        args = node["arguments"]
        target = (
            re.fullmatch(r"\{\\([A-Za-z@]+)\}", args[1] or "")
            if len(args) >= 2
            else None
        )
        if target:
            targets.append(target[1])
        if len(args) != 5 or args[2] != "[1]" or args[3] is not None:
            continue
        cite = re.search(
            r"\\cite(?:p|t)?\{([A-Za-z0-9:._/-]*#1[A-Za-z0-9:._/-]*)\}", args[4] or ""
        )
        if target and cite and (args[4] or "").count("#1") == 1:
            wrappers[target[1]] = (cite[1], node["id"])
    return {
        name: value
        for name, value in wrappers.items()
        if targets.count(name) == 1
        and not re.search(
            r"\\(?:def|gdef|edef|xdef|let)\s*\\" + re.escape(name) + r"(?![A-Za-z@])",
            text,
        )
    }


def _table_rows(node, text, coordinates):
    body = getattr(node, "nodelist", None) or []
    if not body:
        return []
    cursor = coordinates.to_entry(body[0].pos)
    cells, rows = [], []
    for child in body:
        is_cell = getattr(child, "specials_chars", None) == "&"
        is_row = getattr(child, "macroname", None) in {"\\", "tabularnewline", "cr"}
        if is_cell or is_row:
            stop = coordinates.to_entry(child.pos)
            cells.append(_cell(text, cursor, stop))
            cursor = coordinates.to_entry(child.pos + child.len)
            if is_row:
                rows.append(cells)
                cells = []
    end = coordinates.to_entry(body[-1].pos + body[-1].len)
    if text[cursor:end].strip():
        cells.append(_cell(text, cursor, end))
    if cells:
        rows.append(cells)
    return rows


def _cell(text, start, end):
    raw = text[start:end]
    spans = {"columns": 1, "rows": 1}
    for command, key in (("multicolumn", "columns"), ("multirow", "rows")):
        match = re.search(r"\\" + command + r"\s*", raw)
        if match:
            arg = group(raw, match.end())
            spans[key] = (
                int(arg[0]) if arg and re.fullmatch(r"[1-9]\d*", arg[0]) else None
            )
    return {"range": [start, end], "tex": raw, "spans": spans}


def _assets(tree, nodes, used_files):
    result = [
        {
            "path": p,
            "sha256": digest(raw),
            "source": "original",
            "call_nodes": [],
            "used_in_build": p in used_files,
        }
        for p, raw in sorted(tree.files.items())
        if PurePosixPath(p).suffix.lower() in ASSETS
    ]
    for node in nodes:
        if node["kind"] != "macro" or node["name"] != "includegraphics":
            continue
        args = [a for a in node["arguments"] if a and a.startswith("{")]
        if not args:
            continue
        name = args[-1][1:-1]
        candidates = _asset_candidates(node, name, result)
        observed = [a for a in candidates if a["used_in_build"]]
        candidates = observed or candidates
        node["asset_targets"] = {
            "paths": [a["path"] for a in candidates],
            "status": "resolved"
            if len(candidates) == 1
            else "ambiguous"
            if candidates
            else "unresolved",
        }
        for asset in candidates:
            asset["call_nodes"].append(node["id"])
    return result


def _asset_candidates(node, name, assets):
    names = {name}
    names.update(
        str(PurePosixPath(s["path"]).parent / name) for s in node["source_spans"]
    )
    candidates = [
        a
        for a in assets
        if a["path"] in names or str(PurePosixPath(a["path"]).with_suffix("")) in names
    ]
    if candidates:
        return candidates
    return [
        a
        for a in assets
        if PurePosixPath(a["path"]).name == name
        or PurePosixPath(a["path"]).stem == name
    ]


def _wrapper_calls(nodes, required, text, assembly, tree):
    result, located = [], set()
    wrappers = _citation_wrappers(nodes, text)
    for node in nodes:
        if (
            node["kind"] != "macro"
            or node["region"] != "body"
            or node["name"] not in wrappers
        ):
            continue
        template, definition = wrappers[node["name"]]
        start, stop = node["range"]
        arg = group(text, stop)
        if arg:
            value, end = arg[:2]
        else:
            tail = re.match(r"\s*([A-Za-z0-9])", text[stop:])
            if not tail:
                continue
            value, end = tail[1], stop + tail.end()
        key = template.replace("#1", value)
        if ("0", key) in required:
            result.append(
                {
                    "node": node["id"],
                    "section": "0",
                    "keys": [key],
                    "definition_node": definition,
                    "origin": "literal_wrapper_verified_by_aux",
                    "range": [start, end],
                    "source_spans": [
                        _source_span_for_wrapper(tree, p, a, b)
                        for p, a, b in entry_source_spans(assembly, start, end)
                    ],
                }
            )
            located.add(("0", key))
    return result, located
