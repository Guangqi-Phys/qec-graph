"""Classify preserved guards; never choose an unknown prose branch."""

import re

from ..source.assembly import condition_regions, _skip_definition, _definition_event


def conditional_views(text, nodes, start, end):
    inactive, uncertain = condition_regions(text)
    views = []
    for a, b in [*inactive, *uncertain]:
        region = (
            "preamble"
            if start is not None and b <= start
            else "inactive"
            if end is not None and a >= end
            else "body"
        )
        kind = "unmapped"
        raw = text[a:b]
        if region != "body":
            kind = region + "_syntax_preserved"
        elif _layout_guard(raw):
            kind = "layout_only"
        elif _inside_bibliography(a, b, nodes) and _bibliography_helpers(raw):
            kind = "bibliography_format_setup"
        views.append(
            {"range": [a, b], "region": region, "kind": kind, "branch_selected": False}
        )
    return views


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
