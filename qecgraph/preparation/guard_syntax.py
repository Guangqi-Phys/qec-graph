"""Bounded guard grammar and lossless projection into an assembled source view."""

import re

from .branches import _mask
from .artifacts import SourceIndex
from ..source.assembly import (
    condition_regions,
    document_bounds,
    _conditional_bounds,
    DIRECTIVES,
)

_HEADER = re.compile(
    r"\\ifdefined(?![A-Za-z@])\s*(\\[A-Za-z@]+)|\\ifx(?![A-Za-z@])\s*(\\[A-Za-z@]+)\s*(\\[A-Za-z@]+)"
)


def candidates(path, raw):
    text = raw.decode()
    _, uncertain = condition_regions(text)
    body = document_bounds(text)[1]
    result = []
    for start, stop in uncertain:
        header = _HEADER.match(text, start)
        if header is None or _only_preamble(text, start, stop, body):
            continue
        alternative, closing, end = _conditional_bounds(text, header.end())
        cuts = _cuts(text, start, header.end(), alternative, closing, end)
        if closing >= len(text) or end != stop or cuts is None:
            continue
        result.append(
            {
                "id": "g" + str(len(result)),
                "origin": SourceIndex(raw).span(path, start, end),
                "header_chars": [start, header.end()],
                "header_tex": header[0],
                "true_masks": cuts[0],
                "false_masks": cuts[1],
                "true_marker": header.end(),
                "false_marker": alternative,
                "closing": closing,
            }
        )
    return result


def _only_preamble(text, start, stop, body):
    if body is None or stop > body:
        return False
    return not re.search(
        r"\\(?:" + "|".join(sorted(DIRECTIVES)) + r")(?![A-Za-z@])", text[start:stop]
    )


def _line_end(text, position):
    tail = re.match(r"[ \t]*(?:%[^\r\n]*)?(?=\r?\n|$)", text[position:])
    return position + tail.end() if tail else None


def _cuts(text, start, header, alternative, closing, end):
    head_end, fi_end = _line_end(text, header), _line_end(text, end)
    if head_end is None or fi_end is None:
        return None
    if alternative is None:
        return ([[start, head_end], [closing, fi_end]], [[start, fi_end]])
    if text[alternative - 5 : alternative] != r"\else":
        return None
    else_end = _line_end(text, alternative)
    if else_end is None:
        return None
    return (
        [[start, head_end], [alternative - 5, fi_end]],
        [[start, else_end], [closing, fi_end]],
    )


def selected_guards(view):
    if not view or view.get("verified") is not True:
        return []
    return [g for g in view.get("guards", []) if g.get("status") == "observed"]


def scan_views(tree, view):
    by_path = {}
    for guard in selected_guards(view):
        by_path.setdefault(guard["origin"]["path"], []).extend(
            guard["true_masks"] if guard["selected"] else guard["false_masks"]
        )
    return {p: _mask(tree.files[p].decode(), masks) for p, masks in by_path.items()}


def project_view(assembly, view):
    masks, guards = [], []
    for guard in selected_guards(view):
        path = guard["origin"]["path"]
        cuts = guard["true_masks"] if guard["selected"] else guard["false_masks"]
        masks.extend(
            bounds for a, b in cuts for bounds in _project(assembly, path, a, b)
        )
        headers = _project(assembly, path, *guard["header_chars"])
        for a, b in headers:
            if b - a == len(guard["header_tex"]):
                guards.append(
                    {
                        "id": guard["id"],
                        "header_range": [a, b],
                        "header_tex": guard["header_tex"],
                        "selected": guard["selected"],
                        "origin": guard["origin"],
                    }
                )
    return masks, guards


def _project(assembly, path, start, end):
    result = []
    for segment in assembly.segments:
        a, b = max(start, segment.char_start), min(end, segment.char_end)
        if segment.path == path and a < b:
            result.append(
                [
                    segment.out_char_start + a - segment.char_start,
                    segment.out_char_start + b - segment.char_start,
                ]
            )
    return result
