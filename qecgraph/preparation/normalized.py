"""A bounded, reversible LaTeX view; never reconstruct source from a PDF."""

from __future__ import annotations

from collections import Counter
import re

from pylatexenc.latexwalker import LatexWalker, LatexWalkerParseError

from .contract import digest
from .branches import syntax_view
from ..source.syntax import declaration_context

PROFILE = "qecgraph.normalized_latex/1"
DELIMITERS = {"$": (r"\(", r"\)"), "$$": (r"\[", r"\]")}


def normalize_latex(text, document, references, bibliography=None):
    """Flattened source plus only mechanically checkable surface rewrites.

    Keep the author class, packages, definitions, unknown macros and assets.
    Each output character belongs to an exact copy or an explicit format edit.
    """
    edits = _format_edits(text, document, references, bibliography)
    edits.sort(key=lambda edit: edit["input_range"])
    pieces, segments = [], []
    cursor, output_pos = 0, 0
    for edit in edits:
        start, end = edit["input_range"]
        if start < cursor:
            raise ValueError("Overlapping normalized LaTeX edits")
        output_pos = _append(pieces, segments, text, cursor, start, output_pos)
        output_pos = _append(pieces, segments, text, start, end, output_pos, edit)
        cursor = end
    _append(pieces, segments, text, cursor, len(text), output_pos)
    normalized = "".join(pieces)
    mapping = {
        "schema": PROFILE,
        "input": "entry.tex",
        "output": "normalized.tex",
        "coordinate_unit": "unicode_codepoint",
        "range_convention": "half_open",
        "input_sha256": digest(text.encode()),
        "output_sha256": digest(normalized.encode()),
        "segments": segments,
        "bibliography": (
            {"path": bibliography[0], "sha256": digest(bibliography[1])}
            if bibliography
            else None
        ),
    }
    report = {
        "schema": PROFILE,
        "transformations": dict(Counter(e["operation"] for e in edits)),
        "source_mapping": "verified",
        "syntax_parse": _syntax_check(
            normalized,
            legacy_bounds="observed_guards" not in document,
            dialect=document.get("dialect"),
        ),
        "document_coordinate_space": "entry.tex",
        "complete": False,
        "native_compile": "not_run",
        "pdf_text": "not_run",
        "limitations": [
            "The author class, packages, unknown macros and assets remain required.",
            "No arbitrary macro expansion, semantic rewriting or active-branch reconstruction.",
            "This is derived LaTeX; exact quotations use entry.tex and original source spans.",
            "Inserted bibliography text comes from the consumed BBL, not original prose.",
        ],
    }
    validate_normalized(text, normalized, mapping, document, references, bibliography)
    return normalized.encode(), mapping, report


def _syntax_check(text, *, legacy_bounds=False, dialect=None):
    from . import harvmac

    text = harvmac.parse_view(text) if dialect else text
    text, _ = syntax_view(text, allow_observed_bounds=legacy_bounds)
    try:
        _, start, length = LatexWalker(
            text,
            latex_context=harvmac.context(text)
            if dialect
            else declaration_context(source_text=text),
            tolerant_parsing=False,
        ).get_latex_nodes()
    except (LatexWalkerParseError, ValueError):
        return "partial"
    return "complete" if start + length == len(text) else "partial"


def _math_edits(text, document):
    edits = []
    by_id = {n["id"]: n for n in document["nodes"]}
    for node in document["nodes"]:
        if node["kind"] != "math" or node["region"] != "body":
            continue
        if not _plain_math_context(node, by_id):
            continue
        start, end = node["range"]
        raw = text[start:end]
        delimiter = "$$" if raw.startswith("$$") else "$"
        if not raw.startswith(delimiter) or not raw.endswith(delimiter):
            continue
        size = len(delimiter)
        if end - start < 2 * size:
            continue
        for bounds, replacement in zip(
            ((start, start + size), (end - size, end)), DELIMITERS[delimiter]
        ):
            edits.append(
                {
                    "input_range": list(bounds),
                    "replacement": replacement,
                    "operation": "math_delimiter",
                    "node": node["id"],
                }
            )
    return edits


def _format_edits(text, document, references, bibliography):
    if document.get("dialect") or not document.get("syntax_complete", True):
        return []
    return (
        _guard_edits(text, document)
        + _math_edits(text, document)
        + _cite_edits(text, document, references)
        + _bbl_edits(document, references, bibliography)
    )


def _guard_edits(text, document):
    result = []
    for guard in document.get("observed_guards", []):
        start, end = guard["header_range"]
        if (
            type(guard["selected"]) is not bool
            or text[start:end] != guard["header_tex"]
        ):
            raise ValueError("Observed guard header does not match the source view")
        result.append(
            {
                "input_range": [start, end],
                "operation": "observed_conditional_header",
                "replacement": r"\iftrue" if guard["selected"] else r"\iffalse",
                "guard": guard["id"],
            }
        )
    return result


def _plain_math_context(node, by_id):
    parent = node["parent"]
    while parent:
        owner = by_id[parent]
        if owner["kind"] in {"macro", "group", "math"}:
            return False
        parent = owner["parent"]
    return True


def _cite_edits(text, document, references):
    by_id = {n["id"]: n for n in document["nodes"]}
    resolved = {
        (b["section"], b["key"])
        for b in references["bindings"]
        if b.get("status") == "resolved"
    }
    edits = []
    for call in document["citations"]:
        if call["origin"] != "literal_wrapper_verified_by_aux":
            continue
        definition = by_id[call["definition_node"]]
        if definition["name"] != "newcommand" or definition["region"] != "preamble":
            continue
        if any((call["section"], key) not in resolved for key in call["keys"]):
            continue
        start, end = call["range"]
        invocation = text[start:end]
        argument = re.fullmatch(
            r"\\[A-Za-z@]+\s*(?:\{([^{}]*)\}|([A-Za-z0-9]))", invocation
        )
        if argument is None:
            continue
        value = argument[1] if argument[1] is not None else argument[2]
        body = definition["arguments"][-1][1:-1]
        edits.append(
            {
                "input_range": [start, end],
                "replacement": body.replace("#1", value),
                "operation": "citation_wrapper",
                "node": call["node"],
                "definition_node": definition["id"],
            }
        )
    return edits


def _append(pieces, segments, text, start, end, output_pos, edit=None):
    if start == end:
        return output_pos
    value = text[start:end] if edit is None else edit["replacement"]
    segment = {
        "input_range": [start, end],
        "output_range": [output_pos, output_pos + len(value)],
        "operation": "copy" if edit is None else edit["operation"],
    }
    if edit is not None:
        segment.update({k: v for k, v in edit.items() if k != "replacement"})
    segments.append(segment)
    pieces.append(value)
    return output_pos + len(value)


def _bbl_edits(document, references, bibliography):
    if not bibliography or references.get("mode") != "classic":
        return []
    # Legacy v4 mappings remain verifiable under their recorded surface policy.
    if "syntax_complete" in document and _multiple_bibliographies(document):
        return []
    classes = [
        n["arguments"][-1]
        for n in document["nodes"]
        if n["kind"] == "macro" and n["name"] == "documentclass" and n["arguments"]
    ]
    # Deferred bibliography/footnote hooks in other classes need their own adapter.
    if classes not in (["{article}"], ["{report}"], ["{book}"]):
        return []
    nodes = [
        n
        for n in document["nodes"]
        if n["kind"] == "macro"
        and n["name"] == "bibliography"
        and n["region"] == "body"
    ]
    if len(nodes) != 1:
        return []
    raw = bibliography[1].decode("utf-8")
    if r"\begin{thebibliography}" not in raw or r"\end{thebibliography}" not in raw:
        return []
    return [
        {
            "input_range": nodes[0]["range"],
            "replacement": "\n" + raw + "\n",
            "operation": "compiled_bibliography",
            "node": nodes[0]["id"],
        }
    ]


def _multiple_bibliographies(document):
    for node in document["nodes"]:
        if node["name"] == "newcites":
            return True
        if node["name"] == "usepackage" and any(
            a and "multibib" in a.strip("{}").split(",") for a in node["arguments"]
        ):
            return True
    return False


def validate_normalized(
    text, normalized, mapping, document, references, bibliography=None
):
    """Recompute allowed edits; reject dropped text, invented math and forged maps."""
    if (
        mapping["schema"] != PROFILE
        or mapping["input_sha256"] != digest(text.encode())
        or mapping["output_sha256"] != digest(normalized.encode())
    ):
        raise ValueError("Normalized LaTeX identity mismatch")
    edits = _format_edits(text, document, references, bibliography)
    expected_bbl = (
        {"path": bibliography[0], "sha256": digest(bibliography[1])}
        if bibliography
        else None
    )
    if mapping.get("bibliography") != expected_bbl:
        raise ValueError("Normalized bibliography provenance mismatch")
    allowed = {tuple(e["input_range"]): e for e in edits}
    cursor, output_pos = 0, 0
    for segment in mapping["segments"]:
        start, end = segment["input_range"]
        a, b = segment["output_range"]
        if not (
            start == cursor < end <= len(text)
            and a == output_pos < b <= len(normalized)
        ):
            raise ValueError("Normalized LaTeX mapping does not tile both views")
        expected = _expected_segment(segment, text, allowed)
        if normalized[a:b] != expected:
            raise ValueError(
                "Normalized LaTeX changes content outside an allowed format edit"
            )
        cursor, output_pos = end, b
    if cursor != len(text) or output_pos != len(normalized):
        raise ValueError("Normalized LaTeX tail is missing")
    return True


def _expected_segment(segment, text, allowed):
    start, end = segment["input_range"]
    if segment["operation"] == "copy":
        return text[start:end]
    edit = allowed.get((start, end))
    if edit is None or any(
        segment.get(k) != v for k, v in edit.items() if k != "replacement"
    ):
        raise ValueError("Unsupported normalized LaTeX operation")
    return edit["replacement"]
