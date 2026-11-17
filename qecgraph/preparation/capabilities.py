"""Distinguish prepared reference candidates from uniquely bound references."""

from .crossrefs import CROSS_REFERENCE_POLICY

_REFERENCE_ISSUES = {"cross_reference_ambiguous", "cross_reference_unresolved"}


def preparation_capabilities(build, document, coverage, references):
    body_reasons = set(coverage.get("reasons", [])) - {"conversion_diagnostics"}
    body_issues = [
        d for d in coverage.get("diagnostics", []) if d["code"] not in _REFERENCE_ISSUES
    ]
    body = bool(
        build.get("success")
        and document.get("nodes")
        and document.get("syntax_complete", False)
        and all(v is not None for v in document.get("body_range", [None, None]))
        and not body_reasons
        and not body_issues
    )
    unresolved = [
        {
            "node": row["node"],
            "key": target["key"],
            "status": target["status"],
            "candidates": target["nodes"],
        }
        for row in document.get("cross_references", [])
        if row["region"] == "body"
        for target in row["targets"]
        if target["status"] != "resolved"
    ]
    result = {
        "schema": "qecgraph.preparation_capabilities/1",
        "body_syntax": "complete" if body else "partial",
        "bibliography_bindings": "complete"
        if references.get("complete")
        else "partial",
        "cross_reference_bindings": "complete"
        if body and not unresolved
        else "partial",
        "unresolved_cross_references": unresolved,
        "scope": "Preparation syntax only; no scientific extraction or semantic validation",
    }
    if document.get("cross_reference_policy") == CROSS_REFERENCE_POLICY:
        result["cross_reference_preparation"] = (
            "complete"
            if body and all(row["status"] == "ambiguous" for row in unresolved)
            else "partial"
        )
    return result
