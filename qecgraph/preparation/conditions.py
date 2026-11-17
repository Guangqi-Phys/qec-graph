"""Classify preserved guards; never choose an unknown prose branch."""

import re

from .branches import literal_false_ranges
from ..source.assembly import condition_regions, _skip_definition, _definition_event


DRAWING_ENVIRONMENTS = frozenset(
    {
        "tikzpicture",
        "pgfpicture",
        "picture",
        "circuitikz",
        "quantikz",
        "forest",
        "tikzcd",
    }
)


def conditional_views(text, nodes, start, end, *, observed_guards=()):
    inactive, uncertain = condition_regions(text)
    views = []
    literal = literal_false_ranges(text)
    observed = {g["header_range"][0]: g for g in observed_guards}
    for a, b in [*inactive, *uncertain]:
        raw = text[a:b]
        boundary = (start is not None and a < start < b) or (
            end is not None and a < end < b
        )
        region = (
            "document_boundary"
            if boundary
            else "preamble"
            if start is not None and b <= start
            else "inactive"
            if end is not None and a >= end
            else "body"
        )
        kind = "unmapped"
        if a in observed:
            kind = "native_observed_branch"
        elif any(x == a for x, _ in literal):
            kind = "literal_false_guard"
        elif region == "document_boundary":
            kind = "unmapped"
        elif region != "body":
            kind = region + "_syntax_preserved"
        elif _layout_guard(raw):
            kind = "layout_only"
        elif _inside_bibliography(a, b, nodes) and _bibliography_helpers(raw):
            kind = "bibliography_format_setup"
        elif _inside_drawing(a, b, nodes):
            kind = "drawing_payload"
        views.append(
            {
                "range": [a, b],
                "region": region,
                "kind": kind,
                "branch_selected": kind
                in {"literal_false_guard", "native_observed_branch"},
            }
        )
    return views


def _inside_drawing(start, end, nodes):
    return any(
        node["kind"] == "environment"
        and node["name"] in DRAWING_ENVIRONMENTS
        and node["range"][0] <= start < end <= node["range"][1]
        for node in nodes
    )


def _layout_guard(raw):
    return bool(re.fullmatch(r"\\ifCLASSOPTIONcaptionsoff\s*\\newpage\s*\\fi", raw))


def _inside_bibliography(start, end, nodes):
    return any(
        n["kind"] == "environment"
        and n["name"] == "thebibliography"
        and n["range"][0] <= start < end <= n["range"][1]
        for n in nodes
    )


def _bibliography_helpers(raw):
    header = re.match(
        r"\\ifx(?:\\xfnm\\undefined|\\csname\s+urlstyle\\endcsname\\relax)\s*", raw
    )
    if header is None or not raw.endswith(r"\fi"):
        return False
    body = raw[header.end() : -3]
    return all(_helper_declarations(part) for part in body.split(r"\else"))


def _helper_declarations(text):
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        match = re.match(r"\\(def|providecommand)(?![A-Za-z@])", text[position:])
        if match is None:
            return False
        name = match[1]
        definition = _definition_event(text, position, name)
        if definition is None or definition.name not in {"xfnm", "doi"}:
            return False
        after = _skip_definition(text, position + match.end(), name)
        if after <= position:
            return False
        position = after
    return True
