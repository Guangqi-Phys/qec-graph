"""Compile -> syntax conversion -> verified material publication, with no AI."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from . import PREPARATION_VERSION
from .build import compile_tree
from .contract import SCHEMA, digest, json_bytes, validate_material
from .convert import convert_source
from .references import adapt_references
from ..source.normalization import load_for_preparation
from ..source.prepare import select_entry, publish_artifacts, _check_output_root
from ..core.transactions import writer_lock


def prepare_material(source: Path, out: Path, *, entry=None, engine=None, support=(),
                     overwrite=False, compiler=compile_tree):
    """Prepare material only; no source graph, research record or model publication."""
    source, out = source.resolve(), out.absolute()
    _check_output_root(out, source, overwrite)
    out.parent.mkdir(parents=True, exist_ok=True)
    with writer_lock(out.parent / ("." + out.name + ".writer.lock")):
        tree, loading = load_for_preparation(source, repair_legacy_tar=True)
        selected = select_entry(tree, entry)
        with TemporaryDirectory(prefix="qecgraph-compile-", dir=out.parent) as temp:
            files, manifest = _material(tree, selected, Path(temp), engine, support, compiler, loading)
        if source.is_file():
            files["original.package"] = source.read_bytes()
            manifest["package_sha256"] = digest(files["original.package"])
        manifest["artifacts"] = {p: digest(raw) for p, raw in sorted(files.items())}
        files["manifest.json"] = json_bytes(manifest)
        validate_material(files)
        destination = out
        previous = out / "manifest.json"
        if previous.is_file() and manifest["status"] != "ready":
            prior = json.loads(previous.read_bytes())
            if prior.get("schema") == SCHEMA and prior.get("status") == "ready":
                destination = out.with_name(out.name + ".attempt")
        publish_artifacts(files, destination, source=source, overwrite=overwrite)
        return {"out": str(destination), "previous_retained": destination != out,
                **{k: manifest[k] for k in ("status", "stages", "source_tree_sha256", "entry", "rule_version")}}


def _material(tree, entry, work, engine, support, compiler, loading):
    files = {"sources/" + path: raw for path, raw in tree.files.items()}
    document = {"schema": "qecgraph.prepared_syntax/1", "nodes": [], "roots": [], "outline": [],
                "citations": [], "assets": [], "body_range": [None, None]}
    entry_data = b""
    references = {"bindings": [], "entries": [], "complete": False}
    coverage = {"complete": False, "reasons": ["compile_failed"], "diagnostics": []}
    build_report = {"success": False, "steps": []}
    diagnostics = []
    try:
        build = compiler(tree, entry, work, engine=engine, support=support)
        files.update({"build/" + p: raw for p, raw in build.artifacts.items()})
        build_report = {"success": build.success, "engine": build.engine, "steps": build.steps,
                        "inputs": build.inputs, "outputs": build.outputs, "dependencies": build.dependencies}
        diagnostics.extend(build.diagnostics)
        if build.success:
            references = adapt_references(build, tree)
            assembly, document, coverage = convert_source(tree, entry, references)
            entry_data = assembly.data
            files["source-map.json"] = json_bytes(assembly.source_map())
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        diagnostics.append({"code": "preparation_failed", "message": str(exc)[:800]})
        if (work / "command.log").is_file():
            files["build/logs/last-command.log"] = (work / "command.log").read_bytes()
    diagnostics.extend(coverage.get("diagnostics", []))
    stages = {"compile": "complete" if build_report["success"] else "failed",
              "conversion": "complete" if coverage["complete"] else "partial",
              "references": "complete" if references["complete"] else "partial",
              "source_fidelity": "checked_at_publication"}
    ready = build_report["success"] and coverage["complete"] and references["complete"] and not diagnostics
    files.update({"entry.tex": entry_data, "content.json": json_bytes(document),
                  "references.json": json_bytes(references), "build.json": json_bytes(build_report),
                  "coverage.json": json_bytes(coverage), "diagnostics.json": json_bytes(diagnostics)})
    manifest = {"schema": SCHEMA, "rule_version": PREPARATION_VERSION, "status": "ready" if ready else "partial",
                "entry": entry, "source_tree_sha256": tree.digest, "sources": tree.manifest,
                "stages": stages, "loading": loading, "model_calls": 0,
                "capabilities": {"originals": True, "syntax": bool(document["nodes"]),
                                 "scientific_extraction": False, "arbitrary_macro_expansion": False},
                "limitations": ["Native compilation is one build view; unmapped conditionals remain partial.",
                                "The normalized handoff preserves original TeX syntax; it is not rendered semantic text.",
                                "No theorem truth, experiment binding, numeric curve extraction or nine-question answers are produced."]}
    return files, manifest
