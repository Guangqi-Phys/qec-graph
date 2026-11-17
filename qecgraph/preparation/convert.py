"""Lossless TeX syntax conversion after compilation; no scientific classifications."""

from __future__ import annotations

from pathlib import PurePosixPath
import re

from pylatexenc.latexwalker import LatexWalker, LatexWalkerParseError

from .artifacts import digest, json_bytes, SourceIndex
from .reference_syntax import group
from .citations import locate_citations as _citations, scope_commands
from ..source.assembly import (
    assemble_files,
    EntryCoordinates,
    entry_source_spans,
    document_bounds,
)
from ..source.syntax import declaration_context
from .crossrefs import cross_references as _cross_references
from .artifacts import CROSS_REFERENCE_POLICY
from .conditions import conditional_views
from .branches import syntax_view
from .environments import label_declarations
from .guard_syntax import scan_views, project_view
from . import harvmac
from . import harvmac_refs

HEADINGS = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
    "subparagraph": 6,
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
    def __init__(
        self, tree, assembly, coordinates, parse_text, inactive=(), dialect=None
    ):
        self.tree, self.assembly, self.coordinates, self.parse_text = (
            tree,
            assembly,
            coordinates,
            parse_text,
        )
        self.text, self.tree_hash = assembly.text, tree.digest
        self.dialect = dialect
        self.nodes, self.indices, self.source_names = [], {}, set()
        strict = document_bounds(parse_text)
        _, start, end = strict
        if dialect:
            start, end, _ = harvmac.body_bounds(assembly.text)
            start, end = coordinates.to_parse(start), coordinates.to_parse(end)
        self.body_start = coordinates.to_entry(start) if start is not None else None
        self.body_end = coordinates.to_entry(end) if end is not None else None
        self.inactive = inactive

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
            "region": "inactive"
            if any(a <= node.pos < b for a, b in self.inactive)
            else "preamble"
            if self.body_start is not None and end <= self.body_start
            else "inactive"
            if self.body_end is not None and start >= self.body_end
            else "body",
        }
        self.nodes.append(item)
        if self.dialect:
            item["arguments"] = [
                self.text[
                    self.coordinates.to_entry(n.pos) : self.coordinates.to_entry(
                        n.pos + n.len
                    )
                ]
                if n
                else None
                for n in (
                    getattr(getattr(node, "nodeargd", None), "argnlist", None) or []
                )
            ]
            harvmac.annotate_node(item, self.text)
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


def _parse_nodes(text, diagnostics, extra_citations=(), dialect=None):
    context = (
        harvmac.context(text)
        if dialect
        else declaration_context(extra_citations, source_text=text)
    )
    try:
        LatexWalker(
            text, latex_context=context, tolerant_parsing=False
        ).get_latex_nodes()
    except (LatexWalkerParseError, ValueError) as exc:
        diagnostics.append({"code": "syntax_incomplete", "message": str(exc)[:400]})
    return LatexWalker(
        text, latex_context=context, tolerant_parsing=True
    ).get_latex_nodes()[0]


def convert_source(
    tree, entry, references, *, used_files=(), build_view=None, dialect=None
):
    """Preserve all source tokens, math and author markup in a versioned material tree.

    This adapter does not promise arbitrary macro expansion. Runtime citation and
    numbering observations remain separate from exact original TeX source spans.
    """
    assembly = assemble_files(
        tree.files,
        entry,
        scan_views=harvmac.assembly_views(tree, scan_views(tree, build_view), dialect),
        allowed_inputs=set(used_files) if used_files else None,
    )
    text = assembly.text
    harvmac.adapt_assembly(assembly, dialect)
    coordinates = EntryCoordinates(assembly)
    view_masks, observed_guards = project_view(assembly, build_view)
    parse_text, inactive = syntax_view(
        harvmac.parse_view(coordinates.copy_text())
        if dialect
        else coordinates.copy_text(),
        [(coordinates.to_parse(a), coordinates.to_parse(b)) for a, b in view_masks],
        allow_observed_bounds=False,
    )
    observations = [
        d for d in assembly.diagnostics if d["code"] == "conditionals_present"
    ]
    diagnostics = [
        d for d in assembly.diagnostics if d["code"] != "conditionals_present"
    ]
    parsed = _parse_nodes(parse_text, diagnostics, scope_commands(references), dialect)
    syntax = _Syntax(tree, assembly, coordinates, parse_text, inactive, dialect)
    roots = syntax.roots(parsed, diagnostics)
    nodes, source_names = syntax.nodes, syntax.source_names
    body_start, body_end = syntax.body_start, syntax.body_end
    views = conditional_views(
        harvmac.scan_text(text) if dialect else text,
        nodes,
        body_start,
        body_end,
        observed_guards=observed_guards,
    )
    outline = _outline(
        nodes,
        {**HEADINGS, "newsec": 1, "subsec": 2, "appendix": 1} if dialect else HEADINGS,
    )
    citations = (
        harvmac_refs.citations(nodes, references, diagnostics)
        if dialect
        else _citations(nodes, references, diagnostics, text, assembly, tree)
    )
    assets = _assets(tree, nodes, set(used_files))
    _record_asset_issues(nodes, diagnostics)
    declarations = label_declarations(tree, set(used_files) or source_names)
    labels, cross_references = (
        harvmac_refs.cross_references(nodes)
        if dialect
        else _cross_references(
            nodes,
            references.get("external_labels", []),
            references.get("observed_labels", []),
            text,
            declarations,
        )
    )
    _record_cross_reference_issues(cross_references, diagnostics, observations)
    _record_duplicate_labels(labels, observations)
    coverage = assembly.coverage()
    reasons = list(coverage["reasons"])
    if diagnostics:
        reasons.append("conversion_diagnostics")
    if body_start is None:
        reasons.append("nonstandard_document_body")
    _record_view_observations(views, nodes, observations)
    conditional_ranges = [v["range"] for v in views if v["kind"] == "unmapped"]
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
        "dialect": dialect,
        "cross_reference_policy": CROSS_REFERENCE_POLICY,
        "environment_label_declarations": declarations,
        "body_range": [body_start, body_end],
        "conditional_ranges": conditional_ranges,
        "conditional_views": views,
        "observed_guards": observed_guards,
        "build_view_sha256": digest(json_bytes(build_view))
        if build_view is not None
        else None,
        "inactive_ranges": [
            [coordinates.to_entry(a), coordinates.to_entry(b)] for a, b in inactive
        ],
        "syntax_complete": not any(
            d["code"] in {"syntax_incomplete", "unparsed_source_preserved"}
            for d in diagnostics
        ),
        "capabilities": {
            "original_tex": True,
            "source_spans": "exact_copy",
            "arbitrary_macro_expansion": False,
            "table_cells": "syntactic",
            "scientific_records": False,
        },
        "files_not_in_reading_view": sorted(set(tree.files) - source_names),
    }
    document["reading_units"] = _reading_units(
        nodes,
        text,
        body_start,
        body_end,
        document["inactive_ranges"],
        plain=bool(dialect),
    )
    document["labels"], document["cross_references"] = labels, cross_references
    return (
        assembly,
        document,
        {
            "complete": not reasons,
            "reasons": sorted(set(reasons)),
            "diagnostics": diagnostics,
            "observations": observations,
        },
    )


def _record_asset_issues(nodes, diagnostics):
    unresolved = [
        node["id"]
        for node in nodes
        if node.get("asset_targets", {}).get("status") != "resolved"
        and "asset_targets" in node
    ]
    if unresolved:
        diagnostics.append({"code": "asset_target_unresolved", "nodes": unresolved})


def _record_cross_reference_issues(cross_references, diagnostics, observations):
    body = [row for row in cross_references if row["region"] == "body"]
    for code, status in (
        ("cross_reference_unresolved", "unresolved"),
        ("cross_reference_ambiguous", "ambiguous"),
    ):
        rows = [
            row
            for row in body
            if any(target["status"] == status for target in row["targets"])
        ]
        if rows:
            destination = observations if status == "ambiguous" else diagnostics
            destination.append(
                {
                    "code": code,
                    "nodes": [row["node"] for row in rows],
                    "occurrences": [
                        {"node": row["node"], "keys": row["keys"]} for row in rows
                    ],
                }
            )


def _record_duplicate_labels(labels, observations):
    duplicates = sorted(
        (key, count) for key, count in _label_counts(labels).items() if count > 1
    )
    if duplicates:
        observations.append(
            {
                "code": "duplicate_labels",
                "labels": [{"key": key, "count": count} for key, count in duplicates],
            }
        )


def _record_view_observations(views, nodes, observations):
    for view in views:
        if view["kind"] == "native_observed_branch":
            observations.append(
                {"code": "native_guard_observation", "range": view["range"]}
            )
        elif view["kind"] == "drawing_payload":
            observations.append({"code": "drawing_conditional", "range": view["range"]})
    case_assets = [
        node["id"]
        for node in nodes
        if node.get("asset_targets", {}).get("match") == "case_insensitive"
    ]
    if case_assets:
        observations.append({"code": "asset_case_mismatch", "nodes": case_assets})


def _label_counts(labels):
    counts = {}
    for label in labels:
        if label["region"] != "body":
            continue
        for key in label["keys"]:
            counts[key] = counts.get(key, 0) + 1
    return counts


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


def _outline(nodes, headings=HEADINGS):
    outline, stack = [], []
    for node in nodes:
        if (
            node["kind"] != "macro"
            or node["name"] not in headings
            or node["region"] != "body"
        ):
            continue
        level = headings[node["name"]]
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


def _reading_units(nodes, text, start, end, inactive=(), *, plain=False):
    if start is None:
        return []
    end = end if end is not None else len(text)
    boundaries = {start, end}
    boundaries.update(p for bounds in inactive for p in bounds if start < p < end)
    by_id = {n["id"]: n for n in nodes}
    atomic = {}
    for node in nodes:
        a, b = node["range"]
        parent = by_id.get(node["parent"], {})
        if not start <= a < b <= end or not (
            parent.get("name") == "document" or (plain and node["parent"] is None)
        ):
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
            "kind": "inactive_source"
            if any(x <= a < b <= y for x, y in inactive)
            else "authored_structure"
            if (a, b) in atomic
            else "paragraph",
        }
        for a, b in zip(points, points[1:])
        if text[a:b].strip()
    ]


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
        candidates, case_insensitive = _asset_candidates(node, name, result)
        used = {p.casefold() for p in used_files}
        observed = [a for a in candidates if a["path"].casefold() in used]
        if case_insensitive and not observed:
            candidates = []
        else:
            candidates = observed or candidates
        node["asset_targets"] = {
            "paths": [a["path"] for a in candidates],
            "status": "resolved"
            if len(candidates) == 1
            else "ambiguous"
            if candidates
            else "unresolved",
            "match": "case_insensitive"
            if candidates and case_insensitive
            else "exact"
            if candidates
            else None,
        }
        for asset in candidates:
            asset["call_nodes"].append(node["id"])
            asset["used_in_build"] = (
                asset["used_in_build"] or asset["path"].casefold() in used
            )
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
        return candidates, False
    folded = {value.casefold() for value in names}
    candidates = [
        a
        for a in assets
        if a["path"].casefold() in folded
        or str(PurePosixPath(a["path"]).with_suffix("")).casefold() in folded
    ]
    if candidates:
        return candidates, True
    candidates = [
        a
        for a in assets
        if PurePosixPath(a["path"]).name == name
        or PurePosixPath(a["path"]).stem == name
    ]
    if candidates:
        return candidates, False
    candidates = [
        a
        for a in assets
        if PurePosixPath(a["path"]).name.casefold() == name.casefold()
        or PurePosixPath(a["path"]).stem.casefold() == name.casefold()
    ]
    return candidates, bool(candidates)
