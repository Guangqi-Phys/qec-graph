"""Immutable extraction snapshots with a rebuildable SQLite query projection."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from importlib.metadata import version
from itertools import groupby
from pathlib import Path
from dataclasses import dataclass

from . import __version__
from .core.graph import build_graph, canonical, hash_text, node_filename, read_json, strict_json_loads, views
from .core.coordinates import SourceLines
from .core.transactions import ManagedDataError, atomic_json, publish_pointer, read_pointer, writer_lock


CURRENT_FORMAT = 'qecgraph.current.v1'


def _is_snapshot_id(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _project_source_hash(entry, sources, resources, config):
    return hash_text(canonical({"entry": entry, "sources": sources, "resources": resources,
                                "parser_config": config}))


def extraction_tool_identity():
    """Capture the exact extraction implementation and dependency versions."""
    parser_version = version("pylatexenc")
    if parser_version != "2.10":
        raise ValueError(f"This release requires pylatexenc==2.10; found {parser_version}")
    package_root = Path(__file__).parent
    tool_sources = {str(path.relative_to(package_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(package_root.rglob('*')) if path.suffix in {'.py', '.json'}}
    return {"tool_version": __version__, "tool_sources": tool_sources,
            "pylatexenc": parser_version, "jsonschema": version("jsonschema")}


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


class SnapshotChanged(ValueError):
    """A pinned session detected different manifest bytes for its snapshot."""


@dataclass(frozen=True)
class GraphInput:
    """An already fixed, read-only corpus projection for the shared query layer."""
    graph: dict
    snapshot: Path | None = None


def _stored_snapshot_path(store, snapshot_id):
    snapshots = Path(store).expanduser().resolve() / 'snapshots'
    snapshot = snapshots / snapshot_id
    if snapshots.is_symlink() or snapshot.is_symlink():
        raise ManagedDataError(snapshot, 'Snapshot paths must be local directories')
    return snapshot


def snapshot_reference(store, snapshot_id=None):
    """Resolve the snapshot location before a caller validates or loads its graph."""
    if snapshot_id is None:
        snapshot = current_snapshot(store)
    else:
        if not _is_snapshot_id(snapshot_id):
            raise ValueError('Invalid snapshot ID')
        snapshot = _stored_snapshot_path(store, snapshot_id)
    return SnapshotReference(snapshot, snapshot.name)


def pin_snapshot(store, snapshot_id=None):
    reference = snapshot_reference(store, snapshot_id)
    graph = read_json(reference.path / 'graph.json')
    if graph['snapshot_id'] != reference.snapshot_id:
        raise ValueError('Snapshot identity mismatch')
    return reference


def current_snapshot(store):
    if isinstance(store, SnapshotReference):
        return store.path
    store = Path(store).resolve()
    path = store / 'CURRENT.json'
    if path.is_symlink():
        raise ManagedDataError(path, 'CURRENT must be a local file')
    pointer = read_pointer(path, CURRENT_FORMAT)
    relative, identity = pointer.get('path'), pointer.get('snapshot_id')
    if not isinstance(relative, str) or not isinstance(identity, str):
        raise ManagedDataError(path, 'CURRENT is missing a snapshot path or identity')
    if not _is_snapshot_id(identity) or relative != 'snapshots/' + identity:
        raise ManagedDataError(path, 'CURRENT does not identify a stored snapshot')
    return _stored_snapshot_path(store, identity)


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


def ingest(entry, project_id, out, project_root=None, config_path=None, annotations_path=None, catalog_dir=None,
           *, strict=False, incremental=False, _tool_identity=None, _split_policy=None):
    out = check_output_directory(out, allow_lock=True)
    with writer_lock(out):
        check_output_directory(out, allow_lock=True)
        previous_enriched = None
        if _split_policy is not None and (out / "CURRENT.json").exists():
            snapshot = current_snapshot(out)
            manifest_path = safe_relative(snapshot, "manifest.json")
            raw = _read_snapshot_file(manifest_path, None, "manifest.json")
            manifest = strict_json_loads(raw.decode("utf-8"), source=str(manifest_path))
            fingerprint = manifest["fingerprint_inputs"]
            if manifest["snapshot_id"] != snapshot.name or hash_text(canonical(fingerprint)) != snapshot.name:
                raise ValueError("CURRENT snapshot fingerprint mismatch")
            if fingerprint["annotations"] or fingerprint["catalog_inputs"]:
                if _split_policy == "protect":
                    raise ValueError("CURRENT includes annotations or a catalog. Choose a separate --out or pass --force.")
                previous_enriched = snapshot.name
        if not (out / '.qecgraph-store.json').exists():
            atomic_json(out / '.qecgraph-store.json', {'format': 'qecgraph.store.v1'})
        result = _ingest_locked(entry, project_id, out, project_root, config_path, annotations_path, catalog_dir,
                                strict=strict, incremental=incremental, tool_identity=_tool_identity)
        if previous_enriched is not None:
            result["previous_snapshot_id"] = previous_enriched
        return result


def _ingest_locked(entry, project_id, out, project_root=None, config_path=None, annotations_path=None, catalog_dir=None,
                   *, strict=False, incremental=False, tool_identity=None):
    from .source.parser import parse_project

    started = time.perf_counter()
    if tool_identity is None:
        tool_identity = extraction_tool_identity()
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
        from .source.incremental import ParseCache
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
    fingerprint = {"project_id": project_id, "project_source_hash": project_source_hash,
                   "annotations": annotations, "catalog_inputs": catalog_inputs, **tool_identity}
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
        output_hashes = {}

        def write_output(relative, raw):
            path = temporary / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(raw)
            output_hashes[relative] = hashlib.sha256(raw).hexdigest()

        def write_output_json(relative, value):
            write_output(relative, _json_bytes(value))

        try:
            write_json(temporary / '.qecgraph-building.json', {'format': 'qecgraph.building.v1', 'snapshot_id': snapshot_id})
            for directory, files in (("sources", source_bytes), ("assets", resource_bytes)):
                for rel, raw in files.items():
                    path = safe_relative(temporary / directory, rel)
                    write_output(path.relative_to(temporary).as_posix(), raw)
            for node in graph["nodes"]:
                kind = node["kind"]
                if not kind or not all(c.isalnum() or c == "_" for c in kind):
                    raise ValueError(f"Unsafe node kind: {kind}")
                stem = node_filename(node["id"])
                relative = "nodes/" + kind + "/" + stem
                node["record_path"] = relative + ".json"
                if node["latex"]:
                    node["fragment_path"] = relative + ".tex"
                    write_output(node["fragment_path"], node["latex"].encode("utf-8"))
                write_output_json(node["record_path"], node)
            write_output_json("graph.json", graph)
            for name, view in views(graph).items():
                write_output_json(name + ".json", view)
            write_output_json("inputs/annotations.json", annotations)
            write_output_json("inputs/parser_config.json", config)
            write_output_json("inputs/catalog.json", catalog)
            build_sqlite(temporary / "graph.sqlite", graph)
            with _open_regular_snapshot_file(temporary / "graph.sqlite") as database:
                output_hashes["graph.sqlite"] = hashlib.file_digest(database, "sha256").hexdigest()
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
            write_output_json("report.json", report)
            (temporary / '.qecgraph-building.json').unlink()
            outputs = [{"path": relative, "sha256": output_hashes[relative]}
                       for relative in sorted(output_hashes, key=lambda relative: Path(relative).parts)]
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
        publish_pointer(out / 'CURRENT.json', CURRENT_FORMAT, snapshot_id=snapshot_id,
                        path='snapshots/' + snapshot_id)
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


def _recoverable_build(path):
    marker = path / '.qecgraph-building.json'
    try:
        with _open_regular_snapshot_file(marker) as stream:
            if os.fstat(stream.fileno()).st_nlink != 1:
                return False
            raw = stream.read(4097)
        if len(raw) > 4096:
            return False
        binding = strict_json_loads(raw.decode('utf-8'), source=str(marker))
        return (isinstance(binding, dict) and binding.get('format') == 'qecgraph.building.v1'
                and _is_snapshot_id(binding.get('snapshot_id')))
    except FileNotFoundError:
        if not (path / 'manifest.json').is_file():
            return False
        graph_path = path / 'graph.json'
        graph = strict_json_loads(_read_snapshot_file(graph_path, None, 'graph.json').decode('utf-8'), source=str(graph_path))
        return _is_snapshot_id(graph['snapshot_id']) and validate_snapshot(path, graph['snapshot_id'])['passed']


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
                try:
                    owned = _recoverable_build(path)
                except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                    owned = False
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


def _snapshot_database_path(snapshot):
    path = safe_relative(snapshot, "graph.sqlite")
    if not path.is_file():
        raise ValueError("Expected a regular snapshot output: graph.sqlite")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(path.name + suffix)
        try:
            sidecar.lstat()
        except FileNotFoundError:
            continue
        raise ValueError(f"Unbound SQLite sidecar: {sidecar.name}")
    return path


@contextmanager
def snapshot_database(snapshot):
    """Open only the standalone SQLite file belonging to a published snapshot."""
    path = _snapshot_database_path(snapshot)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal":
            raise ValueError("Snapshot database cannot use WAL journal mode")
        yield connection
    finally:
        connection.close()


def _open_regular_snapshot_file(path, *, dir_fd=None):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    output = os.fdopen(os.open(path, flags, dir_fd=dir_fd), "rb")
    if not stat.S_ISREG(os.fstat(output.fileno()).st_mode):
        output.close()
        raise ValueError(f"Expected a regular snapshot output: {path}")
    return output


def _snapshot_copy_path(root, relative):
    path = Path(relative)
    if not path.parts or path.is_absolute() or '..' in path.parts or path.as_posix() != relative:
        raise ValueError(f"Expected a canonical snapshot output path: {relative}")
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _read_snapshot_file(path, copy_to, relative):
    with _open_regular_snapshot_file(path) as output:
        data = output.read()
    if copy_to is not None:
        with _snapshot_copy_path(copy_to, relative).open("xb") as destination:
            destination.write(data)
    return data


def _hash_snapshot_output(root, relative, directory_fd, copy_to):
    name = relative.rpartition("/")[2]
    try:
        output = _open_regular_snapshot_file(name, dir_fd=directory_fd)
    except OSError as exc:
        if exc.errno != errno.ELOOP:
            raise
        # Older standalone stores may use links that resolve inside the snapshot.
        output = _open_regular_snapshot_file(_safe_relative_to_resolved(root, relative))
    with output:
        if copy_to is not None:
            digest = hashlib.sha256()
            with _snapshot_copy_path(copy_to, relative).open("xb") as destination:
                while chunk := output.read(256 << 10):
                    destination.write(chunk)
                    digest.update(chunk)
            return digest.hexdigest()
        if os.fstat(output.fileno()).st_size > 1 << 20:
            return hashlib.file_digest(output, "sha256").hexdigest()
        return hashlib.sha256(output.read()).hexdigest()


def _validate_output_hashes(root, outputs, captured, required, copy_to):
    seen = set()
    for folder, group in groupby(outputs, key=lambda row: row["path"].rpartition("/")[0]):
        directory_fd = None
        try:
            for output in group:
                relative = output["path"]
                if relative in seen:
                    raise ValueError(f"Duplicate snapshot output: {relative}")
                seen.add(relative)
                digest = captured.get(relative)
                if digest is None:
                    if relative.startswith("/"):
                        raise ValueError("Expected a relative archive path")
                    if directory_fd is None:
                        directory = _safe_relative_to_resolved(root, folder)
                        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    digest = _hash_snapshot_output(root, relative, directory_fd, copy_to)
                if digest != output["sha256"]:
                    raise ValueError(f"Snapshot file changed: {relative}")
                expected_digest = required.get(relative)
                if expected_digest is not None and digest != expected_digest:
                    raise ValueError(f"Snapshot output does not match the archived source: {relative}")
        finally:
            if directory_fd is not None:
                os.close(directory_fd)
    missing = {*captured, *required} - seen
    if missing:
        raise ValueError(f"Required snapshot outputs missing: {', '.join(sorted(missing))}")


def load_validated_snapshot(snapshot, expected_snapshot_id=None, *, manifest_hashes=None, copy_to=None):
    """Validate captured bytes, optionally writing them to a private staging directory."""
    from .validators import validate_graph_types
    snapshot = Path(snapshot)
    expected = expected_snapshot_id or snapshot.name
    output_root = snapshot.resolve()
    manifest_path = _safe_relative_to_resolved(output_root, "manifest.json")
    manifest_bytes = _read_snapshot_file(manifest_path, copy_to, "manifest.json")
    if manifest_hashes is not None:
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if expected in manifest_hashes and manifest_hashes[expected] != manifest_hash:
            raise SnapshotChanged("Snapshot manifest changed within the pinned session")
    manifest = strict_json_loads(manifest_bytes.decode("utf-8"), source=str(manifest_path))
    graph_path = _safe_relative_to_resolved(output_root, "graph.json")
    graph_bytes = _read_snapshot_file(graph_path, copy_to, "graph.json")
    graph = strict_json_loads(graph_bytes.decode("utf-8"), source=str(graph_path))
    validate_graph_types(graph)
    if graph["snapshot_id"] != expected or manifest["snapshot_id"] != expected:
        raise ValueError("Snapshot identity mismatch")
    fingerprint = manifest["fingerprint_inputs"]
    if hash_text(canonical(fingerprint)) != expected:
        raise ValueError("Snapshot fingerprint mismatch")
    config_relative = "inputs/parser_config.json"
    config_path = _safe_relative_to_resolved(output_root, config_relative)
    config_bytes = _read_snapshot_file(config_path, copy_to, config_relative)
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
        relative = "sources/" + path
        raw = _read_snapshot_file(_safe_relative_to_resolved(source_root, path), copy_to, relative)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != source["sha256"]:
            raise ValueError("Source hash mismatch")
        sources[path] = raw.decode("utf-8")
        captured[relative] = digest
    required = {"assets/" + row["path"]: row["sha256"] for row in manifest["resources"]}
    required["graph.sqlite"] = None
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
        if record_path := node.get("record_path"):
            required.setdefault(record_path, None)
        if fragment_path := node.get("fragment_path"):
            fragment_hash = node["content_sha256"] if span else hash_text(node["latex"])
            if required.setdefault(fragment_path, fragment_hash) != fragment_hash:
                raise ValueError(f"Conflicting snapshot output bindings: {fragment_path}")
    _validate_output_hashes(output_root, manifest["outputs"], captured, required, copy_to)
    for label, ids in graph["labels"].items():
        if any(label not in nodes[i]["labels"] for i in ids):
            raise ValueError("Label ownership mismatch")
    if copy_to is not None:
        _snapshot_database_path(output_root)
    with snapshot_database(output_root if copy_to is None else copy_to) as con:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        if con.execute("SELECT value FROM metadata WHERE key='snapshot_id'").fetchone()[0] != expected:
            raise ValueError("SQLite belongs to a different snapshot")
        if con.execute("SELECT count(*) FROM nodes").fetchone()[0] != len(nodes):
            raise ValueError("SQLite node count mismatch")
        if con.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite graph references are broken")
    report = {"passed": True, "snapshot_id": expected, "nodes": len(nodes), "edges": len(graph["edges"]),
              "source_slices_checked": sum(bool(n.get("source")) for n in nodes.values()),
              "scope": "integrity, structure and provenance; no mathematical or Lean proof verification"}
    if manifest_hashes is not None:
        manifest_hashes[expected] = manifest_hash
    return graph, report
