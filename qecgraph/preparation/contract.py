"""The material handoff and its independent source-fidelity checks."""

from __future__ import annotations

import json
from pathlib import Path

from ..source.package import SourceTree

from . import PREPARATION_VERSION
from .artifacts import ArtifactJSON, SCHEMA as SCHEMA, SourceIndex as SourceIndex
from .artifacts import (
    digest as digest,
    json_bytes as json_bytes,
    safe_path as safe_path,
)
from .bibliography_runtime import bibliography_runtime, bibliography_runtime_failed


def validate_material(files: dict[str, bytes]) -> dict:
    """Validate bytes, tree, token tiling and exact source locators, without TeX."""
    return _validate(ArtifactJSON(files), files["entry.tex"].decode("utf-8"))


def _validate(evidence: ArtifactJSON, text: str) -> dict:
    manifest = evidence["manifest.json"]
    _check_manifest(evidence.files, manifest)
    from .projection import check_projection

    check_projection(evidence)
    document = evidence["content.json"]
    sources = _SourceEvidence(evidence)
    _check_syntax(document, text, sources)
    _check_reference_origins(evidence, sources)
    _check_bibliography_runtime(evidence, manifest)
    from .harvmac import check_dialect

    check_dialect(evidence, document)
    _check_environment_declarations(evidence, document, text, sources)
    from .crossrefs import check_reference_candidates

    check_reference_candidates(evidence, document, text, manifest)
    from .view_contract import check_view

    check_view(evidence, document, text)
    _check_normalized(evidence, document, text)
    from .capabilities import preparation_capabilities

    expected = preparation_capabilities(
        evidence["build.json"],
        document,
        evidence["coverage.json"],
        evidence["references.json"],
    )
    if manifest["preparation_capabilities"] != expected:
        raise ValueError("Preparation capabilities do not match retained evidence")
    if manifest["status"] == "ready":
        if not (
            document["nodes"]
            and evidence["build.json"]["success"]
            and evidence["coverage.json"]["complete"]
            and evidence["references.json"]["complete"]
        ):
            raise ValueError("Ready material has an incomplete prerequisite")
    return {
        "source_fidelity": True,
        "nodes": len(document["nodes"]),
        "ready_for_extraction": manifest["status"] == "ready",
    }


def _check_bibliography_runtime(evidence, manifest):
    files = evidence.files
    references = evidence["references.json"]
    if references.get("mode") in {"classic", "biblatex"}:
        expected = bibliography_runtime(files, manifest["entry"], prefix="build/")
        if references.get("runtime") != expected:
            raise ValueError("Bibliography runtime status does not match the final log")
        if references["complete"] != (
            references["structure_complete"]
            and not bibliography_runtime_failed(expected)
        ):
            raise ValueError(
                "Bibliography completeness does not match retained evidence"
            )
    normalized = evidence["normalization.json"]
    if normalized["native_compile"] == "complete" and (
        normalized["complete"] or "error" not in normalized
    ):
        expected = bibliography_runtime(
            files, manifest["entry"], prefix="normalized-build/"
        )
        if normalized.get("bibliography_runtime") != expected or (
            normalized["complete"] and bibliography_runtime_failed(expected)
        ):
            raise ValueError("Normalized bibliography runtime evidence mismatch")


def _check_syntax(document, text, sources):
    nodes = document["nodes"]
    identifiers = {node["id"] for node in nodes}
    if len(identifiers) != len(nodes):
        raise ValueError("Duplicate material node identity")
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        start, end = node["range"]
        if not 0 <= start < end <= len(text):
            raise ValueError("Invalid material node range")
        if node["parent"] is not None and node["parent"] not in identifiers:
            raise ValueError("Missing material parent")
        _validate_children(node, by_id)
        pieces = [sources.piece(span) for span in node["source_spans"]]
        if "".join(pieces) != text[start:end]:
            raise ValueError("Material node does not copy its original source")
    _validate_roots(document, by_id, len(text))


def _check_environment_declarations(evidence, document, text, sources):
    if "environment_label_declarations" not in document:
        return
    from .environments import label_declarations
    from .crossrefs import _environment_labels

    records = document["environment_label_declarations"]
    for record in records:
        if sources.piece(record["origin"]) != record["raw_tex"]:
            raise ValueError(
                "Environment declaration does not copy its original source"
            )
    build = evidence["build.json"]
    paths = build.get("inputs", [r["origin"]["path"] for r in records])
    from .projection import working_tree, decorate_origins

    files = evidence.files
    projection = evidence.get("source-projection.json", {"verified": False})
    expected_records = label_declarations(
        working_tree(files, projection=projection), paths
    )
    decorate_origins(expected_records, files, projection=projection)
    if expected_records != records:
        raise ValueError(
            "Environment label declarations do not match consumed source grammar"
        )
    references = evidence["references.json"]
    expected = _environment_labels(
        document["nodes"], references.get("observed_labels", []), text, records
    )
    actual = [
        row
        for row in document.get("labels", [])
        if row.get("origin") == "environment_option_verified_by_aux"
    ]
    if actual != expected:
        raise ValueError(
            "Environment option labels do not match declaration and AUX evidence"
        )


def _check_normalized(evidence, document, text):
    from .normalized import validate_normalized

    files, manifest = evidence.files, evidence["manifest.json"]
    if "normalized.tex" not in files:
        if manifest["status"] == "ready":
            raise ValueError("Ready preparation is missing normalized LaTeX")
        return
    mapping = evidence["normalized-map.json"]
    origin = mapping.get("bibliography")
    bibliography = (
        (safe_path(origin["path"]), files[safe_path(origin["path"])])
        if origin
        else None
    )
    validate_normalized(
        text,
        files["normalized.tex"].decode("utf-8"),
        mapping,
        document,
        evidence["references.json"],
        bibliography,
    )
    if manifest["status"] == "ready":
        report = evidence["normalization.json"]
        if not (
            report["complete"]
            and report["native_compile"] == "complete"
            and report["syntax_parse"] == "complete"
            and report["pdf_text"] in {"equal", "tool_unavailable", "pdf_unavailable"}
        ):
            raise ValueError("Ready normalized LaTeX has not passed its round trip")


def _check_reference_origins(evidence, sources):
    files = evidence.files
    references = evidence["references.json"]
    for field in ("entries", "original_bib_entries", "external_labels"):
        for record in references.get(field, []):
            span = record.get("origin", {})
            if span.get("layer") in {"original", "projected"}:
                if sources.piece(span) != record["raw_tex"]:
                    raise ValueError(
                        "Reference metadata does not copy its original source"
                    )

    for record in references.get("observed_labels", []):
        span = record["origin"]
        path = safe_path(span["path"])
        artifact = "build/files/" + path
        if artifact not in files:
            artifact = "sources/" + path
        if artifact not in files:
            raise ValueError("Compiled label observation is missing its AUX")
        index = sources.index(artifact, span["encoding"])
        start, end = span["chars"]
        if (
            index.span(path, start, end, layer="compiled") != span
            or index.text[start:end] != record["raw_tex"]
        ):
            raise ValueError("Compiled label observation does not match consumed AUX")


def _check_material_identity(manifest):
    if (
        not isinstance(manifest, dict)
        or manifest.get("rule_version") != PREPARATION_VERSION
    ):
        raise ValueError(f"Preparation requires a {PREPARATION_VERSION} material")
    if manifest.get("schema") != SCHEMA or manifest.get("status") not in {
        "ready",
        "partial",
    }:
        raise ValueError("Unsupported preparation material schema or state")


def _check_manifest(files, manifest):
    _check_material_identity(manifest)
    for path, expected in manifest["artifacts"].items():
        if digest(files[safe_path(path)]) != expected:
            raise ValueError("Material artifact hash changed")
    _check_originals(files, manifest)


def _check_originals(files, manifest):
    tree = SourceTree(
        "material",
        {
            p.removeprefix("sources/"): raw
            for p, raw in files.items()
            if p.startswith("sources/")
        },
    )
    if (
        tree.manifest != manifest["sources"]
        or tree.digest != manifest["source_tree_sha256"]
    ):
        raise ValueError("Original source inventory does not match the bound tree")
    if (
        "original.package" in files
        and digest(files["original.package"]) != manifest["package_sha256"]
    ):
        raise ValueError("Original package hash changed")


def _validate_children(node, by_id):
    previous = node["range"][0]
    for child_id in node["children"]:
        child = by_id.get(child_id)
        if (
            child is None
            or child["parent"] != node["id"]
            or not previous <= child["range"][0] < child["range"][1] <= node["range"][1]
        ):
            raise ValueError("Invalid material child ordering or ownership")
        previous = child["range"][1]


def _validate_roots(document, by_id, length):
    cursor = 0
    for root in document["roots"]:
        node = by_id[root]
        if node["parent"] is not None or node["range"][0] != cursor:
            raise ValueError("Material roots do not tile the source")
        cursor = node["range"][1]
    if cursor != length:
        raise ValueError("Material source tail is missing")
    seen = set()
    pending = list(document["roots"])
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            raise ValueError("Material node cycle or repeated child")
        seen.add(identifier)
        pending.extend(by_id[identifier]["children"])
    if seen != set(by_id):
        raise ValueError("Unreachable material nodes")


def read_material(root: Path, *, expected_manifest_sha256: str | None = None) -> dict:
    """Read only manifest-listed regular files; never follow links or infer sources."""
    if root.is_symlink() or (root / "manifest.json").is_symlink():
        raise ValueError("Linked material root or manifest")
    root = root.resolve()
    raw_manifest = (root / "manifest.json").read_bytes()
    if (
        expected_manifest_sha256 is not None
        and digest(raw_manifest) != expected_manifest_sha256
    ):
        raise ValueError("Material manifest differs from the published attempt")
    manifest = json.loads(raw_manifest)
    _check_material_identity(manifest)
    files = {"manifest.json": raw_manifest}
    for name in manifest["artifacts"]:
        path = root / safe_path(name)
        if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)):
            raise ValueError("Linked material artifact")
        files[name] = path.read_bytes()
    evidence = ArtifactJSON(files, manifest=manifest)
    entry = files["entry.tex"].decode("utf-8")
    check = _validate(evidence, entry)
    engine_log = files.get("build/logs/engine-version.log", b"").splitlines()
    return {
        "manifest": manifest,
        "document": evidence["content.json"],
        "entry_tex": entry,
        "references": evidence["references.json"],
        "coverage": evidence["coverage.json"],
        "validation": check,
        "normalized_tex": files.get("normalized.tex", b"").decode("utf-8"),
        "normalized_map": evidence.get("normalized-map.json"),
        "normalization": evidence.get("normalization.json"),
        "source_projection": evidence.get("source-projection.json"),
        "source_map": evidence.get("source-map.json"),
        "build": evidence.get("build.json", {}),
        "engine_version": engine_log[0].decode() if engine_log else None,
        "build_view": evidence.get("build-view.json", {}),
        "diagnostics": evidence.get("diagnostics.json", []),
    }


class _SourceEvidence:
    """Read-scoped indexes; validation never reuses evidence from a previous bundle."""

    def __init__(self, evidence):
        self.files = evidence.files
        self.indices = {}
        self.paths = {}
        self.projection = evidence.get("source-projection.json")

    def index(self, path, encoding):
        key = (path, encoding)
        if key not in self.indices:
            self.indices[key] = SourceIndex(self.files[path], encoding)
        return self.indices[key]

    def piece(self, span):
        projected = span.get("layer") == "projected"
        prefix = "projected-sources/" if projected else "sources/"
        path = span["path"]
        if path not in self.paths:
            self.paths[path] = safe_path(path)
        source = self.index(prefix + self.paths[path], span["encoding"])
        if projected:
            from .projection import check_locator

            check_locator(span, self.files, source.text, report=self.projection)
        if source.sha256 != span["sha256"]:
            raise ValueError("Source locator hash changed")
        decoded = source.text
        a, b = span["chars"]
        low, high = span["bytes"]
        if (
            not 0 <= a < b <= len(decoded)
            or low != source.byte_at(a)
            or high != source.byte_at(b)
        ):
            raise ValueError("Source locator byte/codepoint mismatch")
        if span["lines"] != [source.lines.line_at(a), source.lines.line_at(b - 1)]:
            raise ValueError("Source locator line mismatch")
        return decoded[a:b]
