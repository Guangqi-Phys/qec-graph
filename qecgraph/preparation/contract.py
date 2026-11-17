"""The material handoff and its independent source-fidelity checks."""

from __future__ import annotations

import hashlib
import json
from array import array
from pathlib import Path, PurePosixPath

from ..source.package import SourceTree

from ..core.coordinates import SourceLines

SCHEMA = "qecgraph.prepare/3"


class SourceIndex:
    """Cache hashes and coordinates once per file, not once per token."""

    def __init__(self, raw, encoding="utf-8"):
        self.text = raw.decode(encoding)
        self.encoding = encoding
        self.sha256 = digest(raw)
        self.lines = SourceLines(self.text)
        self.offsets = None
        if not self.text.isascii() or encoding != "utf-8":
            self.offsets = array("Q", [0])
            for char in self.text:
                self.offsets.append(self.offsets[-1] + len(char.encode(encoding)))

    def byte_at(self, offset):
        return self.offsets[offset] if self.offsets is not None else offset

    def span(self, path, start, end, *, layer="original"):
        return {
            "path": path,
            "sha256": self.sha256,
            "layer": layer,
            "encoding": self.encoding,
            "chars": [start, end],
            "bytes": [self.byte_at(start), self.byte_at(end)],
            "lines": [
                self.lines.line_at(start),
                self.lines.line_at(max(start, end - 1)),
            ],
        }


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def safe_path(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or "\\" in name
        or "\x00" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError(f"Unsafe material path: {name!r}")
    return name


def validate_material(files: dict[str, bytes]) -> dict:
    """Validate bytes, tree, token tiling and exact source locators, without TeX."""
    manifest = _check_manifest(files)
    from .projection import check_projection

    check_projection(files)
    document = json.loads(files["content.json"])
    nodes = document["nodes"]
    identifiers = {node["id"] for node in nodes}
    if len(identifiers) != len(nodes):
        raise ValueError("Duplicate material node identity")
    text = files["entry.tex"].decode("utf-8")
    by_id = {node["id"]: node for node in nodes}
    source_indices: dict[tuple[str, str], SourceIndex] = {}
    for node in nodes:
        start, end = node["range"]
        if not 0 <= start < end <= len(text):
            raise ValueError("Invalid material node range")
        if node["parent"] is not None and node["parent"] not in identifiers:
            raise ValueError("Missing material parent")
        _validate_children(node, by_id)
        pieces = [
            _source_piece(files, span, source_indices) for span in node["source_spans"]
        ]
        if "".join(pieces) != text[start:end]:
            raise ValueError("Material node does not copy its original source")
    _validate_roots(document, by_id, len(text))
    _check_reference_origins(files, source_indices)
    from .harvmac import check_dialect

    check_dialect(files, document)
    _check_environment_declarations(files, document, text, source_indices)
    from .crossrefs import check_reference_candidates

    check_reference_candidates(files, document, text, manifest)
    from .view_contract import check_view

    check_view(files, document, text)
    _check_normalized(files, document, text)
    if "preparation_capabilities" in manifest:
        from .capabilities import preparation_capabilities

        expected = preparation_capabilities(
            json.loads(files["build.json"]),
            document,
            json.loads(files["coverage.json"]),
            json.loads(files["references.json"]),
        )
        if manifest["preparation_capabilities"] != expected:
            raise ValueError("Preparation capabilities do not match retained evidence")
    if manifest["status"] == "ready":
        if not (
            nodes
            and json.loads(files["build.json"])["success"]
            and json.loads(files["coverage.json"])["complete"]
            and json.loads(files["references.json"])["complete"]
        ):
            raise ValueError("Ready material has an incomplete prerequisite")
    return {
        "source_fidelity": True,
        "nodes": len(nodes),
        "ready_for_extraction": manifest["status"] == "ready",
    }


def _check_environment_declarations(files, document, text, source_indices):
    if "environment_label_declarations" not in document:
        return
    from .environments import label_declarations
    from .crossrefs import _environment_labels

    records = document["environment_label_declarations"]
    for record in records:
        if _source_piece(files, record["origin"], source_indices) != record["raw_tex"]:
            raise ValueError(
                "Environment declaration does not copy its original source"
            )
    build = json.loads(files.get("build.json", b"{}"))
    paths = build.get("inputs", [r["origin"]["path"] for r in records])
    from .projection import working_tree, decorate_origins

    expected_records = label_declarations(working_tree(files), paths)
    decorate_origins(expected_records, files)
    if expected_records != records:
        raise ValueError(
            "Environment label declarations do not match consumed source grammar"
        )
    references = json.loads(files.get("references.json", b"{}"))
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


def _check_normalized(files, document, text):
    from .normalized import validate_normalized

    if "normalized.tex" not in files:
        manifest = json.loads(files["manifest.json"])
        if (
            str(manifest.get("rule_version", "")).startswith("compile-prepare-v")
            and manifest["rule_version"]
            not in {"compile-prepare-v1", "compile-prepare-v2", "compile-prepare-v3"}
            and manifest["status"] == "ready"
        ):
            raise ValueError("Ready preparation is missing normalized LaTeX")
        return
    mapping = json.loads(files["normalized-map.json"])
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
        json.loads(files["references.json"]),
        bibliography,
    )
    manifest = json.loads(files["manifest.json"])
    if manifest["status"] == "ready":
        report = json.loads(files["normalization.json"])
        if not (
            report["complete"]
            and report["native_compile"] == "complete"
            and report["syntax_parse"] == "complete"
            and report["pdf_text"] in {"equal", "tool_unavailable", "pdf_unavailable"}
        ):
            raise ValueError("Ready normalized LaTeX has not passed its round trip")


def _check_reference_origins(files, source_indices):
    if "references.json" not in files:
        return
    references = json.loads(files["references.json"])
    for field in ("entries", "original_bib_entries", "external_labels"):
        for record in references.get(field, []):
            span = record.get("origin", {})
            if span.get("layer") in {"original", "projected"}:
                if _source_piece(files, span, source_indices) != record["raw_tex"]:
                    raise ValueError(
                        "Reference metadata does not copy its original source"
                    )

    for record in references.get("observed_labels", []):
        span = record["origin"]
        path = safe_path(span["path"])
        raw = files.get("build/files/" + path, files.get("sources/" + path))
        if raw is None:
            raise ValueError("Compiled label observation is missing its AUX")
        index = SourceIndex(raw, span["encoding"])
        start, end = span["chars"]
        if (
            index.span(path, start, end, layer="compiled") != span
            or index.text[start:end] != record["raw_tex"]
        ):
            raise ValueError("Compiled label observation does not match consumed AUX")


def _check_manifest(files):
    manifest = json.loads(files["manifest.json"])
    if manifest.get("schema") != SCHEMA or manifest.get("status") not in {
        "ready",
        "partial",
    }:
        raise ValueError("Unsupported preparation material schema or state")
    for path, expected in manifest.get("artifacts", {}).items():
        if digest(files[safe_path(path)]) != expected:
            raise ValueError("Material artifact hash changed")
    _check_originals(files, manifest)
    return manifest


def _check_originals(files, manifest):
    if "sources" in manifest:
        original = {
            p.removeprefix("sources/"): raw
            for p, raw in files.items()
            if p.startswith("sources/")
        }
        tree = SourceTree("material", original)
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


def read_material(root: Path) -> dict:
    """Read only manifest-listed regular files; never follow links or infer sources."""
    if root.is_symlink() or (root / "manifest.json").is_symlink():
        raise ValueError("Linked material root or manifest")
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_bytes())
    files = {"manifest.json": (root / "manifest.json").read_bytes()}
    for name in manifest["artifacts"]:
        path = root / safe_path(name)
        if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)):
            raise ValueError("Linked material artifact")
        files[name] = path.read_bytes()
    check = validate_material(files)
    return {
        "manifest": manifest,
        "document": json.loads(files["content.json"]),
        "entry_tex": files["entry.tex"].decode("utf-8"),
        "references": json.loads(files["references.json"]),
        "coverage": json.loads(files["coverage.json"]),
        "validation": check,
        "normalized_tex": files.get("normalized.tex", b"").decode("utf-8"),
        "normalized_map": json.loads(files["normalized-map.json"])
        if "normalized-map.json" in files
        else None,
        "normalization": json.loads(files["normalization.json"])
        if "normalization.json" in files
        else None,
        "source_projection": json.loads(files["source-projection.json"])
        if "source-projection.json" in files
        else None,
        "source_map": json.loads(files["source-map.json"])
        if "source-map.json" in files
        else None,
    }


def _source_piece(files, span, source_indices):
    projected = span.get("layer") == "projected"
    prefix = "projected-sources/" if projected else "sources/"
    key = (prefix + safe_path(span["path"]), span["encoding"])
    if key not in source_indices:
        source_indices[key] = SourceIndex(files[key[0]], key[1])
    if projected:
        from .projection import check_locator

        check_locator(span, files, source_indices[key].text)
    source = source_indices[key]
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
