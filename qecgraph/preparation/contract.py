"""The material handoff and its independent source-fidelity checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

SCHEMA = "qecgraph.prepare/3"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def safe_path(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or "\\" in name or "\x00" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ValueError(f"Unsafe material path: {name!r}")
    return name


def validate_material(files: dict[str, bytes]) -> dict:
    """Validate bytes, tree, token tiling and exact source locators, without TeX."""
    manifest = json.loads(files["manifest.json"])
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported prepared material schema")
    for name, expected in manifest["artifacts"].items():
        safe_path(name)
        if digest(files[name]) != expected:
            raise ValueError(f"Material artifact changed: {name}")
    document = json.loads(files["content.json"])
    nodes = document["nodes"]
    identifiers = {node["id"] for node in nodes}
    if len(identifiers) != len(nodes):
        raise ValueError("Duplicate material node identity")
    text = files["entry.tex"].decode("utf-8")
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        start, end = node["range"]
        if not 0 <= start < end <= len(text):
            raise ValueError("Invalid material node range")
        if node["parent"] is not None and node["parent"] not in identifiers:
            raise ValueError("Missing material parent")
        _validate_children(node, by_id)
        pieces = []
        for span in node["source_spans"]:
            raw = files["sources/" + safe_path(span["path"])]
            if digest(raw) != span["sha256"]:
                raise ValueError("Source locator hash changed")
            decoded = raw.decode(span["encoding"])
            a, b = span["chars"]
            low, high = span["bytes"]
            if (not 0 <= a < b <= len(decoded) or low != len(decoded[:a].encode(span["encoding"]))
                    or high != len(decoded[:b].encode(span["encoding"]))):
                raise ValueError("Source locator byte/codepoint mismatch")
            if (span["lines"] != [decoded.count("\n", 0, a) + 1,
                                  decoded.count("\n", 0, b - 1) + 1]):
                raise ValueError("Source locator line mismatch")
            pieces.append(decoded[a:b])
        if "".join(pieces) != text[start:end]:
            raise ValueError("Material node does not copy its original source")
    _validate_roots(document, by_id, len(text))
    return {"source_fidelity": True, "nodes": len(nodes),
            "ready_for_extraction": manifest["status"] == "ready"}


def _validate_children(node, by_id):
    previous = node["range"][0]
    for child_id in node["children"]:
        child = by_id.get(child_id)
        if (child is None or child["parent"] != node["id"]
                or not previous <= child["range"][0] < child["range"][1] <= node["range"][1]):
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
    manifest = json.loads((root / "manifest.json").read_bytes())
    files = {"manifest.json": (root / "manifest.json").read_bytes()}
    for name in manifest["artifacts"]:
        path = root / safe_path(name)
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ValueError("Linked material artifact")
        files[name] = path.read_bytes()
    check = validate_material(files)
    return {"manifest": manifest, "document": json.loads(files["content.json"]),
            "references": json.loads(files["references.json"]), "validation": check}
