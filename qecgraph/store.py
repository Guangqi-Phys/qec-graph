"""Immutable extraction snapshots with a rebuildable SQLite query projection."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from dataclasses import dataclass

from . import __version__
from .graph import build_graph, canonical, hash_text, node_filename, read_json, strict_json_loads, views
from .source_coordinates import SourceLines
from .transactions import atomic_json, writer_lock


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _project_source_hash(entry, sources, resources, config):
    return hash_text(canonical({"entry": entry, "sources": sources, "resources": resources,
                                "parser_config": config}))


def safe_relative(root, relative):
    return _safe_relative_to_resolved(root.resolve(), relative)


def _safe_relative_to_resolved(root, relative):
    relative = Path(relative)
    if relative.is_absolute():
        raise ValueError("Expected a relative archive path")
    path = (root / relative).resolve()
    # Both paths are resolved on a POSIX filesystem. Compare whole components.
    root_parts = root.parts
    if path.parts[:len(root_parts)] != root_parts:
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
    snapshot: Path | None = None


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
        return store.graph, store.snapshot
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
            CREATE TABLE labels(label TEXT NOT NULL, node_id TEXT NOT NULL REFERENCES nodes(id));
            CREATE VIRTUAL TABLE node_fts USING fts5(id UNINDEXED, title, text);
        """)

        def node_rows():
            for node in graph["nodes"]:
                source = node.get("source") or {}
                yield (node["id"], node["kind"], node["title"], node["review_status"],
                       source.get("path"), source.get("line_start"), canonical(node))

        con.executemany("INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?)", node_rows())
        con.executemany("INSERT INTO node_fts VALUES (?, ?, ?)", (
            (node["id"], node["title"], " ".join(node["labels"]) + "\n" + node["latex"] + "\n" + canonical(node["data"]))
            for node in graph["nodes"]
        ))
        con.executemany("INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)", (
            (edge["id"], edge["source"], edge["target"], edge["relation"], edge["status"], canonical(edge))
            for edge in graph["edges"]
        ))
        con.executemany("INSERT INTO labels VALUES (?, ?)", (
            (label, node_id) for label, ids in graph["labels"].items() for node_id in ids
        ))
        con.execute("CREATE INDEX outgoing_edges ON edges(source, relation)")
        con.execute("CREATE INDEX incoming_edges ON edges(target, relation)")
        con.execute("CREATE INDEX label_lookup ON labels(label)")
        con.execute("INSERT INTO metadata VALUES ('snapshot_id', ?)", (graph["snapshot_id"],))
        con.commit()
    finally:
        con.close()


def check_output_directory(out, *, allow_lock=False):
    out = Path(out).expanduser().resolve()
    if out.exists() and not out.is_dir():
        raise ValueError('--out must be a directory')
    if out.is_dir():
        marker = out / '.qecgraph-store.json'
        if marker.is_symlink():
            raise ValueError('The store marker must be a regular local file')
        if marker.exists():
            if read_json(marker) != {'format': 'qecgraph.store.v1'}:
                raise ValueError('Incompatible qecgraph store marker')
        elif any(not (allow_lock and path.name == '.writer.lock') for path in out.iterdir()):
            raise ValueError('Refusing to write into an unrecognized nonempty directory; choose a new --out')
        for name in ('snapshots', 'staging', 'cache'):
            path = out / name
            if path.is_symlink() or path.exists() and not path.is_dir():
                raise ValueError(f'The {name} directory must be a regular local directory')
        for name in ('CURRENT.json', '.qecgraph-project.json'):
            if (out / name).is_symlink():
                raise ValueError(f'{name} must be a regular local pointer')
    return out


def ingest(entry, project_id, out, project_root=None, config_path=None, annotations_path=None, catalog_dir=None, *, strict=False, incremental=False):
    out = check_output_directory(out)
    with writer_lock(out):
        check_output_directory(out, allow_lock=True)
        if not (out / '.qecgraph-store.json').exists():
            atomic_json(out / '.qecgraph-store.json', {'format': 'qecgraph.store.v1'})
        return _ingest_locked(entry, project_id, out, project_root, config_path, annotations_path, catalog_dir,
                              strict=strict, incremental=incremental)


def _ingest_locked(entry, project_id, out, project_root=None, config_path=None, annotations_path=None, catalog_dir=None, *, strict=False, incremental=False):
    from .parser import parse_project

    started = time.perf_counter()
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

    node_cache = None
    if incremental:
        from .incremental import ParseCache
        node_cache = ParseCache(out, root, config)
    parsed = parse_project(entry, project_root=root, config=config, node_cache=node_cache)
    source_bytes = {}
    for item in parsed["files"]:
        raw = item["text"].encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError(f"Parser did not preserve original UTF-8 bytes: {item['path']}")
        source_bytes[item["path"]] = raw
    resource_bytes, resource_digests = {}, {}
    for resource in parsed.get("resources", []):
        path = resource.get("path")
        if not path:
            continue
        if path not in resource_bytes:
            resolved = safe_relative(root, path)
            if not resolved.is_file():
                raise ValueError(f'Input changed during build: {path}; retry')
            raw = resolved.read_bytes()
            resource_bytes[path] = raw
            resource_digests[path] = hashlib.sha256(raw).hexdigest()
        resource["sha256"] = resource_digests[path]
        resource["size_bytes"] = len(resource_bytes[path])
    source_manifest = [{"path": path, "sha256": hashlib.sha256(raw).hexdigest()} for path, raw in sorted(source_bytes.items())]
    resource_manifest = [{"path": path, "sha256": digest} for path, digest in sorted(resource_digests.items())]
    project_source_hash = _project_source_hash(parsed["entry"], source_manifest, resource_manifest, config)
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
    project_marker = out / '.qecgraph-project.json'
    if project_marker.exists():
        if read_json(project_marker) != {'format': 'qecgraph.store-project.v1', 'project_id': project_id}:
            raise ValueError('Use a separate output store for a different project-id')
    else:
        atomic_json(project_marker, {'format': 'qecgraph.store-project.v1', 'project_id': project_id})
    staged = bool(strict and graph['extraction_status'] == 'partial')
    target = safe_relative(out, ('staging/' if staged else 'snapshots/') + snapshot_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".building-", dir=target.parent))
        try:
            write_json(temporary / '.qecgraph-building.json', {'format': 'qecgraph.building.v1', 'snapshot_id': snapshot_id})
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
            (temporary / '.qecgraph-building.json').unlink()
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
    # Editors may save again while parsing. Publish only if the inputs that
    # this snapshot actually read still match; a watcher can retry a newer save.
    for captured in (source_bytes, resource_bytes):
        for relative, raw in captured.items():
            if safe_relative(root, relative).read_bytes() != raw:
                raise ValueError(f'Input changed during build: {relative}; retry')
    if config_path and read_json(config_path) != config or annotations_path and read_json(annotations_path) != annotations:
        raise ValueError('Config/annotations changed during build; retry')
    if catalog_dir:
        current_catalog = [{'path': str(path.relative_to(Path(catalog_dir))), 'sha256': hash_text(canonical(read_json(path)))}
                           for path in sorted(Path(catalog_dir).rglob('*.json'))]
        if current_catalog != catalog_inputs:
            raise ValueError('Catalog changed during build; retry')
    if not staged:
        atomic_json(out / 'CURRENT.json', {'format': 'qecgraph.current.v1', 'snapshot_id': snapshot_id,
                                           'path': 'snapshots/' + snapshot_id})
    report = read_json(target / "report.json")
    result = {"store": str(out), "snapshot": str(target), "snapshot_id": snapshot_id,
            "node_count": report["node_count"], "edge_count": report["edge_count"],
            "kinds": report["kinds"], "relations": report["relations"],
            "extraction_status": report["extraction_status"], "diagnostics": report["diagnostics"],
            "review_queue_count": len(report["review_queue"]), 'published': not staged,
            'publication_status': 'staged_partial' if staged else 'published'}
    if node_cache:
        try:
            node_cache.finish(parsed, result)
        except (OSError, ValueError) as exc:
            node_cache.stats['cache_state_error'] = str(exc)
        result['incremental'] = {**node_cache.stats, 'elapsed_seconds': time.perf_counter() - started,
                                 'semantic_rebuild': 'full discovery, resolution, graph, reviews and projections'}
    return result


def recover_store(store, *, remove_abandoned=False):
    store = check_output_directory(store)
    if not (store / '.qecgraph-store.json').exists():
        raise ValueError('Recovery requires a managed store')
    with writer_lock(store):
        result = {'store': str(store), 'abandoned': [], 'removed': [], 'unrecognized': [], 'current': None}
        if (store / 'CURRENT.json').exists():
            result['current'] = validate_snapshot(current_snapshot(store))
        for parent in ('snapshots', 'staging'):
            for path in sorted((store / parent).glob('.building-*')):
                if path.is_symlink() or not path.is_dir():
                    result['unrecognized'].append(str(path))
                    continue
                marker = path / '.qecgraph-building.json'
                owned = False
                try:
                    if marker.exists():
                        owned = read_json(marker).get('format') == 'qecgraph.building.v1'
                    elif (path / 'manifest.json').exists():
                        validate_snapshot(path, read_json(path / 'graph.json')['snapshot_id'])
                        owned = True
                except (OSError, ValueError, KeyError):
                    pass
                if not owned:
                    result['unrecognized'].append(str(path))
                    continue
                result['abandoned'].append(str(path))
                if remove_abandoned:
                    shutil.rmtree(path)
                    result['removed'].append(str(path))
        return result


def validate_snapshot(snapshot, expected_snapshot_id=None):
    _, report = load_validated_snapshot(snapshot, expected_snapshot_id)
    return report


def source_span_index(graph):
    """Keep original parser span identities independent of graph projection."""
    return graph["project_id"], {
        node["id"]: (node["content_sha256"], span["path"], span["char_start"], span["char_end"])
        for node in graph["nodes"]
        if node.get("origin") == "parser" and (span := node.get("source"))
    }


def load_validated_snapshot(snapshot, expected_snapshot_id=None):
    """Return the graph decoded from the bytes checked during validation."""
    from .validators import validate_graph_types
    snapshot = Path(snapshot)
    manifest = read_json(snapshot / "manifest.json")
    output_root = snapshot.resolve()
    graph_path = _safe_relative_to_resolved(output_root, "graph.json")
    graph_bytes = graph_path.read_bytes()
    graph = strict_json_loads(graph_bytes.decode("utf-8"), source=str(graph_path))
    validate_graph_types(graph)
    expected = expected_snapshot_id or snapshot.name
    if graph["snapshot_id"] != expected or manifest["snapshot_id"] != expected:
        raise ValueError("Snapshot identity mismatch")
    fingerprint = manifest["fingerprint_inputs"]
    if hash_text(canonical(fingerprint)) != expected:
        raise ValueError("Snapshot fingerprint mismatch")
    config_relative = "inputs/parser_config.json"
    config_path = _safe_relative_to_resolved(output_root, config_relative)
    config_bytes = config_path.read_bytes()
    config = strict_json_loads(config_bytes.decode("utf-8"), source=str(config_path))
    source_hash = _project_source_hash(graph["entry"], manifest["source_files"], manifest["resources"], config)
    if (source_hash != fingerprint["project_source_hash"] or source_hash != graph["project_source_hash"]
            or graph["project_id"] != fingerprint["project_id"]):
        raise ValueError("Project source fingerprint mismatch")
    captured = {"graph.json": hashlib.sha256(graph_bytes).hexdigest(),
                config_relative: hashlib.sha256(config_bytes).hexdigest()}
    sources = {}
    source_root = _safe_relative_to_resolved(output_root, "sources")
    for source in manifest["source_files"]:
        path = source["path"]
        raw = _safe_relative_to_resolved(source_root, path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != source["sha256"]:
            raise ValueError("Source hash mismatch")
        sources[path] = raw.decode("utf-8")
        captured["sources/" + path] = digest
    resources = {"assets/" + row["path"]: row["sha256"] for row in manifest["resources"]}
    sqlite_relative = "graph.sqlite"
    sqlite_path = _safe_relative_to_resolved(output_root, sqlite_relative)
    seen_outputs = set()
    for output in manifest["outputs"]:
        relative = output["path"]
        if relative in seen_outputs:
            raise ValueError(f"Duplicate snapshot output: {relative}")
        seen_outputs.add(relative)
        digest = captured.get(relative)
        if digest is None:
            path = sqlite_path if relative == sqlite_relative else _safe_relative_to_resolved(output_root, relative)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != output["sha256"]:
            raise ValueError(f"Snapshot file changed: {output['path']}")
        if digest != resources.get(relative, digest):
            raise ValueError(f"Resource hash mismatch: {relative}")
    missing = {sqlite_relative, *captured, *resources} - seen_outputs
    if missing:
        raise ValueError(f"Required snapshot outputs missing: {', '.join(sorted(missing))}")
    source_lines = {}
    nodes = {n["id"]: n for n in graph["nodes"]}
    if len(nodes) != len(graph["nodes"]):
        raise ValueError("Duplicate node IDs")
    for node in nodes.values():
        span = node.get("source")
        if span:
            path = span["path"]
            text = sources[path]
            start, end = span["char_start"], span["char_end"]
            if not (0 <= start <= end <= len(text)) or text[start:end] != node["latex"]:
                raise ValueError(f"Invalid source slice for {node['id']}")
            if path not in source_lines:
                source_lines[path] = SourceLines(text)
            lines = source_lines[path]
            if span["line_start"] != lines.line_at(start):
                raise ValueError(f"Invalid start line for {node['id']}")
            end_line = lines.line_at(max(start, end - 1))
            if span["line_end"] != end_line:
                raise ValueError(f"Invalid end line for {node['id']}")
            if hash_text(node["latex"]) != node["content_sha256"]:
                raise ValueError("Fragment hash mismatch")
        if node["verification_status"] == "verified":
            raise ValueError("This extractor must not claim mathematical verification")
    for label, ids in graph["labels"].items():
        if any(label not in nodes[i]["labels"] for i in ids):
            raise ValueError("Label ownership mismatch")
    con = sqlite3.connect(sqlite_path.as_uri() + "?mode=ro", uri=True)
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
    report = {"passed": True, "snapshot_id": expected, "nodes": len(nodes), "edges": len(graph["edges"]),
              "source_slices_checked": sum(bool(n.get("source")) for n in nodes.values()),
              "scope": "integrity, structure and provenance; no mathematical or Lean proof verification"}
    return graph, report
