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
from .normalized import normalize_latex
from .roundtrip import verify_roundtrip
from ..source.normalization import load_for_preparation
from ..source.prepare import select_entry, publish_artifacts, _check_output_root
from ..core.transactions import writer_lock
from ..source.package import read_bounded, Limits


def prepare_material(
    source: Path,
    out: Path,
    *,
    entry=None,
    engine=None,
    support=(),
    overwrite=False,
    compiler=compile_tree,
):
    """Prepare material only; no source graph, research record or model publication."""
    source, out = source.resolve(), out.absolute()
    _check_output_root(out, source, overwrite)
    out.parent.mkdir(parents=True, exist_ok=True)
    with writer_lock(out.parent / ("." + out.name + ".writer.lock")):
        original = None
        if source.is_file():
            with source.open("rb") as stream:
                original = read_bounded(stream, Limits().input_bytes)
        with TemporaryDirectory(prefix="qecgraph-compile-", dir=out.parent) as temp:
            load_path = source
            if original is not None:
                load_path = Path(temp) / "original.package"
                load_path.write_bytes(original)
            tree, loading = load_for_preparation(load_path, repair_legacy_tar=True)
            selected = select_entry(tree, entry)
            files, manifest = _material(
                tree, selected, Path(temp), engine, support, compiler, loading
            )
        if original is not None:
            files["original.package"] = original
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
        return {
            "out": str(destination),
            "previous_retained": destination != out,
            **{
                k: manifest[k]
                for k in (
                    "status",
                    "stages",
                    "source_tree_sha256",
                    "entry",
                    "rule_version",
                )
            },
        }


def _material(tree, entry, work, engine, support, compiler, loading):
    files = {"sources/" + path: raw for path, raw in tree.files.items()}
    document = {
        "schema": "qecgraph.prepared_syntax/1",
        "nodes": [],
        "roots": [],
        "outline": [],
        "citations": [],
        "assets": [],
        "body_range": [None, None],
    }
    entry_data = b""
    references = {"bindings": [], "entries": [], "complete": False}
    coverage = {"complete": False, "reasons": ["compile_failed"], "diagnostics": []}
    build_report = {"success": False, "steps": []}
    diagnostics = []
    normalization = {
        "complete": False,
        "native_compile": "not_run",
        "pdf_text": "not_run",
    }
    try:
        build = compiler(tree, entry, work, engine=engine, support=support)
        files.update({"build/" + p: raw for p, raw in build.artifacts.items()})
        build_report = {
            "success": build.success,
            "engine": build.engine,
            "steps": build.steps,
            "inputs": build.inputs,
            "outputs": build.outputs,
            "dependencies": build.dependencies,
        }
        diagnostics.extend(build.diagnostics)
        if build.success:
            references = adapt_references(build, tree)
            assembly, document, coverage = convert_source(
                tree, entry, references, used_files=build.inputs
            )
            entry_data = assembly.data
            files["source-map.json"] = json_bytes(assembly.source_map())
            normalization = _normalize_view(
                build,
                tree,
                assembly,
                document,
                references,
                support,
                compiler,
                files,
                diagnostics,
            )
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        diagnostics.append({"code": "preparation_failed", "message": str(exc)[:800]})
        coverage = {
            "complete": False,
            "reasons": [
                "conversion_failed" if build_report["success"] else "compile_failed"
            ],
            "diagnostics": [],
        }
        if (work / "command.log").is_file():
            files["build/logs/last-command.log"] = (work / "command.log").read_bytes()
    diagnostics.extend(coverage.get("diagnostics", []))
    stages = {
        "compile": "complete" if build_report["success"] else "failed",
        "conversion": "complete" if coverage["complete"] else "partial",
        "references": "complete" if references["complete"] else "partial",
        "normalized_latex": "complete" if normalization["complete"] else "partial",
        "source_fidelity": "checked_at_publication",
    }
    ready = (
        build_report["success"]
        and coverage["complete"]
        and references["complete"]
        and normalization["complete"]
        and not diagnostics
    )
    files.update(
        {
            "entry.tex": entry_data,
            "content.json": json_bytes(document),
            "references.json": json_bytes(references),
            "build.json": json_bytes(build_report),
            "coverage.json": json_bytes(coverage),
            "diagnostics.json": json_bytes(diagnostics),
            "normalization.json": json_bytes(normalization),
        }
    )
    manifest = {
        "schema": SCHEMA,
        "rule_version": PREPARATION_VERSION,
        "status": "ready" if ready else "partial",
        "entry": entry,
        "source_tree_sha256": tree.digest,
        "sources": tree.manifest,
        "stages": stages,
        "loading": loading,
        "model_calls": 0,
        "capabilities": {
            "originals": True,
            "syntax": bool(document["nodes"]),
            "scientific_extraction": False,
            "arbitrary_macro_expansion": False,
            "normalized_latex": "normalized.tex" in files,
        },
        "limitations": [
            "Native compilation is one build view; unmapped conditionals remain partial.",
            "The normalized handoff preserves original TeX syntax; it is not rendered semantic text.",
            "No theorem truth, experiment binding, numeric curve extraction or nine-question answers are produced.",
        ],
    }
    return files, manifest


def _compiled_bbl(build, files):
    name = Path(build.entry).stem + ".bbl"
    if name not in build.inputs:
        return None
    for path in ("build/files/" + name, "sources/" + name):
        if path in files:
            return path, files[path]
    return None


def _normalize_view(
    build, tree, assembly, document, references, support, compiler, files, diagnostics
):
    report = {"complete": False, "native_compile": "not_run", "pdf_text": "not_run"}
    try:
        data, mapping, report = normalize_latex(
            assembly.text, document, references, _compiled_bbl(build, files)
        )
        files["normalized.tex"] = data
        files["normalized-map.json"] = json_bytes(mapping)
        files.update(verify_roundtrip(build, tree, data, report, support, compiler))
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        report["error"] = str(exc)[:800]
    if not report["complete"]:
        diagnostics.append(
            {
                "code": "normalized_latex_roundtrip_failed",
                "message": "Derived LaTeX failed syntax, recompilation or per-page PDF text checks.",
            }
        )
    return report
