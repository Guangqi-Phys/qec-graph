"""Compile -> syntax conversion -> verified material publication, with no AI."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .build import compile_tree
from .artifacts import SCHEMA, digest, json_bytes
from .material import Material
from .contract import validate_material
from .convert import convert_source
from .references import adapt_references
from .build_view import observe_branches
from .guard_syntax import scan_views
from .normalized import normalize_latex
from .roundtrip import verify_roundtrip
from ..source.normalization import load_for_preparation
from ..source.prepare import publish_artifacts, _check_output_root
from ..core.transactions import writer_lock
from .projection import prepare_projection, bind_origins
from .harvmac import identify
from .entries import select_build_entry
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
            selected = select_build_entry(tree, entry)
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
    material = Material(tree)
    try:
        build = compiler(tree, entry, work, engine=engine, support=support)
        material.retain_build(build)
        if build.success:
            _prepare_compiled(build, tree, entry, support, compiler, material)
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        material.fail(exc)
        if (work / "command.log").is_file():
            material.files["build/logs/last-command.log"] = (
                work / "command.log"
            ).read_bytes()
    return material.finish(tree, entry, loading)


def _prepare_compiled(build, tree, entry, support, compiler, material):
    working = prepare_projection(build, tree, support, compiler, material.files)
    dialect = identify(build, working)
    view, view_files = _observe_view(build, working, support, compiler)
    material.references = adapt_references(
        build, working, source_views=scan_views(working, view), dialect=dialect
    )
    material.files.update(view_files)
    assembly, material.document, material.coverage = convert_source(
        working,
        entry,
        material.references,
        used_files=build.inputs,
        build_view=view,
        dialect=dialect,
    )
    material.entry_data = assembly.data
    material.files["source-map.json"] = json_bytes(assembly.source_map())
    material.normalization = _normalize_view(
        build, working, assembly, material, support, compiler
    )
    bind_origins(material.document, material.references, material.files)


def _observe_view(build, tree, support, compiler):
    try:
        view, artifacts = observe_branches(build, tree, support, compiler)
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        view = {
            "schema": "qecgraph.build_view/1",
            "source_tree_sha256": tree.digest,
            "guards": [],
            "verified": False,
            "error": str(exc)[:800],
        }
        artifacts = {}
    artifacts["build-view.json"] = json_bytes(view)
    return view, artifacts


def _compiled_bbl(build, files):
    name = Path(build.entry).stem + ".bbl"
    if name not in build.inputs:
        return None
    for path in ("build/files/" + name, "sources/" + name):
        if path in files:
            return path, files[path]
    return None


def _normalize_view(build, tree, assembly, material, support, compiler):
    report = {"complete": False, "native_compile": "not_run", "pdf_text": "not_run"}
    try:
        data, mapping, report = normalize_latex(
            assembly.text,
            material.document,
            material.references,
            _compiled_bbl(build, material.files),
        )
        material.files["normalized.tex"] = data
        material.files["normalized-map.json"] = json_bytes(mapping)
        material.files.update(
            verify_roundtrip(build, tree, data, report, support, compiler)
        )
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        report["error"] = str(exc)[:800]
    if not report["complete"]:
        material.diagnostics.append(
            {
                "code": "normalized_latex_roundtrip_failed",
                "message": "Derived LaTeX failed syntax, recompilation or per-page PDF text checks.",
            }
        )
    return report
