"""Source-only LaTeX splitting on top of the shared ingestion pipeline.

The files written by :func:`qecgraph.store.ingest` are the split output.  This
module only provides a focused API and an inventory of their exact paths; it
does not maintain another parser or copy fragments into a second directory.
"""
from __future__ import annotations

from pathlib import Path
import sys

from ..core.graph import read_json
from ..store import ingest, safe_relative


def split_project(
    entry: str | Path,
    project_id: str,
    out: str | Path,
    project_root: str | Path | None = None,
    config_path: str | Path | None = None,
    *, strict: bool = False, incremental: bool = False, force: bool = False,
) -> dict:
    """Split a LaTeX project into source-provenanced semantic fragments.

    The result is JSON-serializable.  ``fragments_by_kind`` contains each
    category's count, directory and exact ``.tex``/``.json`` paths.  Paths named
    ``fragment_path`` and ``record_path`` are relative to ``snapshot``; paths
    named ``tex_file`` and ``record_file`` are absolute convenience paths.

    The shared pipeline creates immutable snapshots and the queryable graph.
    This source-only operation deliberately accepts no annotations or catalog.
    Tables remain extracted source tables, with no mathematical verification.
    Use `force` to explicitly replace CURRENT when it includes annotations or
    a catalog. The previous immutable snapshot remains addressable.

    Parsing can produce a valid *partial* snapshot.  In that case the API
    returns ``extraction_status='partial'`` and ``suggested_exit_code=2``.  The
    two CLI entry points use that exit code.  Fatal I/O/configuration failures
    raise the same exceptions as the shared ingestion pipeline.

    Fragments may overlap or nest.  They are not a disjoint text partition and
    are not guaranteed to compile individually.  ``sources/`` contains the
    preserved original source files.
    """
    result = ingest(
        entry=entry,
        project_id=project_id,
        out=out,
        project_root=project_root,
        config_path=config_path,
        annotations_path=None,
        catalog_dir=None,
        strict=strict,
        incremental=incremental,
        _split_policy="force" if force else "protect",
    )
    # Read the exact returned immutable snapshot, not CURRENT: another writer
    # may advance CURRENT after ingestion without changing this result.
    snapshot = Path(result["snapshot"])
    graph = read_json(snapshot / "graph.json")
    manifest = read_json(snapshot / "manifest.json")
    if graph["snapshot_id"] != result["snapshot_id"]:
        raise ValueError("Splitter result and graph snapshot identity disagree")

    grouped: dict[str, dict] = {}
    fragments = [node for node in graph["nodes"] if node.get("fragment_path")]
    fragments.sort(key=lambda node: (
        node["kind"], (node.get("source") or {}).get("path", ""),
        (node.get("source") or {}).get("char_start", 0), node["id"],
    ))
    for node in fragments:
        kind = node["kind"]
        relative_directory = "nodes/" + kind
        category = grouped.setdefault(kind, {
            "count": 0,
            "relative_directory": relative_directory,
            "directory": str(safe_relative(snapshot, relative_directory)),
            "fragments": [],
        })
        category["fragments"].append({
            "id": node["id"],
            "labels": node["labels"],
            "title": node["title"],
            "fragment_path": node["fragment_path"],
            "record_path": node["record_path"],
            "tex_file": str(safe_relative(snapshot, node["fragment_path"])),
            "record_file": str(safe_relative(snapshot, node["record_path"])),
            "content_sha256": node["content_sha256"],
            "source": node.get("source"),
        })
        category["count"] += 1

    sources = [
        {**source, "archived_file": str(safe_relative(snapshot / "sources", source["path"]))}
        for source in manifest["source_files"]
    ]
    return {
        "format": "qecgraph.split-result",
        "operation": "split",
        **result,
        "project_id": graph["project_id"],
        "source_only": True,
        "fragment_count": len(fragments),
        "fragments_by_kind": grouped,
        "sources": sources,
        "paths": {
            "source_directory": str(snapshot / "sources"),
            "fragment_root": str(snapshot / "nodes"),
            "graph": str(snapshot / "graph.json"),
            "sourcegraph": str(snapshot / "sourcegraph.json"),
            "datagraph": str(snapshot / "datagraph.json"),
            "lemmagraph": str(snapshot / "lemmagraph.json"),
            "sqlite": str(snapshot / "graph.sqlite"),
            "report": str(snapshot / "report.json"),
            "manifest": str(snapshot / "manifest.json"),
        },
        "fragment_semantics": {
            "may_overlap_or_nest": True,
            "reconstruct_from_fragments": False,
            "standalone_compilation": "not_guaranteed",
            "mathematical_verification": "not_performed",
            "lean_build": "not_performed",
        },
        "suggested_exit_code": 2 if result["extraction_status"] == "partial" else 0,
    }


def main(argv=None):
    """Console entry point for ``qec-latex-split``; share the graph CLI path."""
    from ..cli import main as graph_main

    arguments = sys.argv[1:] if argv is None else list(argv)
    return graph_main(["split", *arguments], entrypoint=('split', 'qec-latex-split'))


if __name__ == "__main__":
    raise SystemExit(main())
