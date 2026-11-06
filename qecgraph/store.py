"""Immutable extraction snapshots with a rebuildable SQLite query projection."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from dataclasses import dataclass

from . import __version__
from .graph import build_graph, canonical, hash_text, node_filename, read_json, views
from .parser import parse_project


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_relative(root, relative):
    relative = Path(relative)
    if relative.is_absolute():
        raise ValueError("Expected a relative archive path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes root: {relative}")
    return path


@dataclass(frozen=True)
class SnapshotReference:
    path: Path
    snapshot_id: str


@dataclass(frozen=True)
class GraphInput:
    """An already fixed, read-only corpus projection for the shared query layer."""
    graph: dict


def pin_snapshot(store, snapshot_id=None):
    if snapshot_id is None:
        snapshot = current_snapshot(store)
    else:
        if len(snapshot_id) != 64 or any(c not in '0123456789abcdef' for c in snapshot_id):
            raise ValueError('Invalid snapshot ID')
        snapshot = Path(store).resolve() / 'snapshots' / snapshot_id
    graph = read_json(snapshot / 'graph.json')
    if graph['snapshot_id'] != snapshot.name:
        raise ValueError('Snapshot identity mismatch')
    return SnapshotReference(snapshot, graph['snapshot_id'])


def current_snapshot(store):
    if isinstance(store, SnapshotReference):
        return store.path
    store = Path(store).resolve()
    pointer = read_json(store / "CURRENT.json")
    if pointer.get("format") != "qecgraph.current.v1":
        raise ValueError("Not a qecgraph CURRENT pointer")
    snapshot = safe_relative(store, pointer["path"])
    if snapshot.name != pointer["snapshot_id"]:
        raise ValueError("Snapshot pointer mismatch")
    return snapshot


def load_graph(store):
    if isinstance(store, GraphInput):
        return store.graph, None
    snapshot = current_snapshot(store)
    graph = read_json(snapshot / "graph.json")
    if graph["snapshot_id"] != snapshot.name:
        raise ValueError("Graph and snapshot identity disagree")
    if isinstance(store, SnapshotReference) and graph['snapshot_id'] != store.snapshot_id:
        raise ValueError('Pinned snapshot identity mismatch')
    return graph, snapshot


def build_sqlite(path, graph):
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE nodes(id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
                review_status TEXT NOT NULL, source_path TEXT, line_start INTEGER, payload TEXT NOT NULL);
            CREATE TABLE edges(id TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES nodes(id),
                target TEXT NOT NULL REFERENCES nodes(id), relation TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX outgoing_edges ON edges(source, relation);
            CREATE INDEX incoming_edges ON edges(target, relation);
            CREATE TABLE labels(label TEXT NOT NULL, node_id TEXT NOT NULL REFERENCES nodes(id));
            CREATE INDEX label_lookup ON labels(label);
            CREATE VIRTUAL TABLE node_fts USING fts5(id UNINDEXED, title, text);
        """)
        for node in graph["nodes"]:
            source = node.get("source") or {}
            con.execute("INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (node["id"], node["kind"], node["title"], node["review_status"], source.get("path"),
                         source.get("line_start"), canonical(node)))
            text = " ".join(node["labels"]) + "\n" + node["latex"] + "\n" + canonical(node["data"])
            con.execute("INSERT INTO node_fts VALUES (?, ?, ?)", (node["id"], node["title"], text))
        for edge in graph["edges"]:
            con.execute("INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                        (edge["id"], edge["source"], edge["target"], edge["relation"], edge["status"], canonical(edge)))
        for label, ids in graph["labels"].items():
            con.executemany("INSERT INTO labels VALUES (?, ?)", [(label, node_id) for node_id in ids])
        con.execute("INSERT INTO metadata VALUES ('snapshot_id', ?)", (graph["snapshot_id"],))
        con.commit()
    finally:
        con.close()


def ingest(entry, project_id, out, project_root=None, config_path=None, annotations_path=None, catalog_dir=None):
    parser_version = version("pylatexenc")
    if parser_version != "2.10":
        raise ValueError(f"This release requires pylatexenc==2.10; found {parser_version}")
    entry = Path(entry).resolve()
    root = Path(project_root).resolve() if project_root else entry.parent
    out = Path(out).resolve()
    config = read_json(config_path) if config_path else {}
    annotations = read_json(annotations_path) if annotations_path else {}
    catalog, catalog_inputs = [], []
    if catalog_dir:
        for path in sorted(Path(catalog_dir).rglob("*.json")):
            record = read_json(path)
            if not {"id", "kind"} <= record.keys():
                raise ValueError(f"Catalog file does not look like a record: {path}")
            catalog.append(record)
            catalog_inputs.append({"path": str(path.relative_to(Path(catalog_dir))), "sha256": hash_text(canonical(record))})

    parsed = parse_project(entry, project_root=root, config=config)
    source_bytes = {}
    for item in parsed["files"]:
        raw = item["text"].encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError(f"Parser did not preserve original UTF-8 bytes: {item['path']}")
        source_bytes[item["path"]] = raw
    resource_bytes = {}
    for resource in parsed.get("resources", []):
        path = resource.get("path")
        if path:
            resolved = safe_relative(root, path)
            if resolved.is_file():
                resource_bytes[path] = resolved.read_bytes()
                resource["sha256"] = hashlib.sha256(resource_bytes[path]).hexdigest()
                resource["size_bytes"] = len(resource_bytes[path])
    source_manifest = [{"path": path, "sha256": hashlib.sha256(raw).hexdigest()} for path, raw in sorted(source_bytes.items())]
    resource_manifest = [{"path": path, "sha256": hashlib.sha256(raw).hexdigest()} for path, raw in sorted(resource_bytes.items())]
    project_source_hash = hash_text(canonical({"entry": parsed["entry"], "sources": source_manifest,
                                              "resources": resource_manifest, "parser_config": config}))
    package_root = Path(__file__).parent
    tool_sources = {str(path.relative_to(package_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(package_root.rglob('*')) if path.suffix in {'.py', '.json'}}
    fingerprint = {"project_id": project_id, "project_source_hash": project_source_hash,
                   "annotations": annotations, "catalog_inputs": catalog_inputs,
                   "tool_version": __version__, "tool_sources": tool_sources, "pylatexenc": parser_version,
                   'jsonschema': version('jsonschema')}
    snapshot_id = hash_text(canonical(fingerprint))
    graph = build_graph(parsed, project_id, project_source_hash, annotations, catalog)
    graph["snapshot_id"] = snapshot_id
    out.mkdir(parents=True, exist_ok=True)
    marker = out / ".qecgraph-store.json"
    if marker.exists():
        if read_json(marker) != {"format": "qecgraph.store.v1"}:
            raise ValueError("Output directory has an incompatible qecgraph marker")
    else:
        if (out / "CURRENT.json").exists() or (out / "snapshots").exists():
            raise ValueError("Refusing to replace an unrecognized output directory; choose a new --out")
        write_json(marker, {"format": "qecgraph.store.v1"})
    previous_graph = None
    if (out / "CURRENT.json").exists():
        previous_graph, _ = load_graph(out)
        if previous_graph["project_id"] != project_id:
            raise ValueError("Use a separate output store for a different project-id")
    target = out / "snapshots" / snapshot_id
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".building-", dir=target.parent))
        try:
            for rel, raw in source_bytes.items():
                path = safe_relative(temporary / "sources", rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            for rel, raw in resource_bytes.items():
                path = safe_relative(temporary / "assets", rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            for node in graph["nodes"]:
                kind = node["kind"]
                if not kind or not all(c.isalnum() or c == "_" for c in kind):
                    raise ValueError(f"Unsafe node kind: {kind}")
                stem = node_filename(node["id"])
                relative = "nodes/" + kind + "/" + stem
                node["record_path"] = relative + ".json"
                if node["latex"]:
                    node["fragment_path"] = relative + ".tex"
                    path = temporary / node["fragment_path"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(node["latex"].encode("utf-8"))
                write_json(temporary / node["record_path"], node)
            write_json(temporary / "graph.json", graph)
            for name, view in views(graph).items():
                write_json(temporary / (name + ".json"), view)
            write_json(temporary / "inputs" / "annotations.json", annotations)
            write_json(temporary / "inputs" / "parser_config.json", config)
            write_json(temporary / "inputs" / "catalog.json", catalog)
            build_sqlite(temporary / "graph.sqlite", graph)
            current_nodes = {n["id"]: n["content_sha256"] for n in graph["nodes"]}
            previous_nodes = {n["id"]: n["content_sha256"] for n in previous_graph["nodes"]} if previous_graph else {}
            report = {"snapshot_id": snapshot_id, "project_id": project_id, "extraction_status": graph["extraction_status"],
                      "node_count": len(graph["nodes"]), "edge_count": len(graph["edges"]),
                      "kinds": dict(sorted(Counter(n["kind"] for n in graph["nodes"]).items())),
                      "relations": dict(sorted(Counter(e["relation"] for e in graph["edges"]).items())),
                      "diagnostics": graph["diagnostics"],
                      "review_queue": [{"edge_id": e["id"], "reason": e["status"]} for e in graph["edges"]
                                       if e["status"] in {"candidate", "stale", "unbound_review", "unresolved"}],
                      "changes": {"previous_snapshot": previous_graph["snapshot_id"] if previous_graph else None,
                                  "added": sorted(current_nodes.keys() - previous_nodes.keys()),
                                  "removed": sorted(previous_nodes.keys() - current_nodes.keys()),
                                  "content_changed": sorted(k for k in current_nodes.keys() & previous_nodes.keys()
                                                            if current_nodes[k] != previous_nodes[k])},
                      "mathematical_verification": "not_performed", "lean_build": "not_performed"}
            write_json(temporary / "report.json", report)
            outputs = [{"path": str(p.relative_to(temporary)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                       for p in sorted(temporary.rglob("*")) if p.is_file()]
            write_json(temporary / "manifest.json", {"format": "qecgraph.manifest.v1", "snapshot_id": snapshot_id,
                        "fingerprint_inputs": fingerprint, "source_files": source_manifest,
                        "resources": resource_manifest, "outputs": outputs,
                        "coordinate_system": "Unicode codepoints, [start,end); line numbers 1-based inclusive"})
            validate_snapshot(temporary, expected_snapshot_id=snapshot_id)
            temporary.rename(target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    else:
        validate_snapshot(target)
    pointer_tmp = out / "CURRENT.new.json"
    write_json(pointer_tmp, {"format": "qecgraph.current.v1", "snapshot_id": snapshot_id,
                             "path": "snapshots/" + snapshot_id})
    os.replace(pointer_tmp, out / "CURRENT.json")
    report = read_json(target / "report.json")
    return {"store": str(out), "snapshot": str(target), "snapshot_id": snapshot_id,
            "node_count": report["node_count"], "edge_count": report["edge_count"],
            "kinds": report["kinds"], "relations": report["relations"],
            "extraction_status": report["extraction_status"], "diagnostics": report["diagnostics"],
            "review_queue_count": len(report["review_queue"])}


def validate_snapshot(snapshot, expected_snapshot_id=None):
    from .validators import validate_graph_types
    snapshot = Path(snapshot)
    manifest = read_json(snapshot / "manifest.json")
    graph = read_json(snapshot / "graph.json")
    validate_graph_types(graph)
    expected = expected_snapshot_id or snapshot.name
    if graph["snapshot_id"] != expected or manifest["snapshot_id"] != expected:
        raise ValueError("Snapshot identity mismatch")
    if hash_text(canonical(manifest["fingerprint_inputs"])) != expected:
        raise ValueError("Snapshot fingerprint mismatch")
    for output in manifest["outputs"]:
        path = safe_relative(snapshot, output["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != output["sha256"]:
            raise ValueError(f"Snapshot file changed: {output['path']}")
    sources = {}
    for source in manifest["source_files"]:
        raw = safe_relative(snapshot / "sources", source["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Source hash mismatch")
        sources[source["path"]] = raw.decode("utf-8")
    nodes = {n["id"]: n for n in graph["nodes"]}
    if len(nodes) != len(graph["nodes"]):
        raise ValueError("Duplicate node IDs")
    for node in nodes.values():
        span = node.get("source")
        if span:
            text = sources[span["path"]]
            start, end = span["char_start"], span["char_end"]
            if not (0 <= start <= end <= len(text)) or text[start:end] != node["latex"]:
                raise ValueError(f"Invalid source slice for {node['id']}")
            if span["line_start"] != text.count("\n", 0, start) + 1:
                raise ValueError(f"Invalid start line for {node['id']}")
            end_line = text.count("\n", 0, max(start, end - 1)) + 1
            if span["line_end"] != end_line:
                raise ValueError(f"Invalid end line for {node['id']}")
            if hash_text(node["latex"]) != node["content_sha256"]:
                raise ValueError("Fragment hash mismatch")
        if node["verification_status"] == "verified":
            raise ValueError("This extractor must not claim mathematical verification")
    for edge in graph["edges"]:
        if edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError("Dangling graph edge")
    for label, ids in graph["labels"].items():
        if any(label not in nodes[i]["labels"] for i in ids):
            raise ValueError("Label ownership mismatch")
    con = sqlite3.connect((snapshot / "graph.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        if con.execute("SELECT value FROM metadata WHERE key='snapshot_id'").fetchone()[0] != expected:
            raise ValueError("SQLite belongs to a different snapshot")
        if con.execute("SELECT count(*) FROM nodes").fetchone()[0] != len(nodes):
            raise ValueError("SQLite node count mismatch")
        if con.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite graph references are broken")
    finally:
        con.close()
    return {"passed": True, "snapshot_id": expected, "nodes": len(nodes), "edges": len(graph["edges"]),
            "source_slices_checked": sum(bool(n.get("source")) for n in nodes.values()),
            "scope": "integrity, structure and provenance; no mathematical or Lean proof verification"}
