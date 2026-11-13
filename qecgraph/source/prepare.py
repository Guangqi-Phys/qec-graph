"""Offline recognition and conversion of LaTeX source trees.

This module is the supported offline preparation layer:

1. recognize a TeX entry from content, not only from a ``.tex`` suffix;
2. assemble literal includes and literal zero-argument path macros into an
   entry that is made only of original source bytes;
3. parse each origin file separately and merge the blocks into an
   entry-ordered document model;
4. report content, structure and dependency completeness separately.

It does not expand arbitrary macros, evaluate conditionals, run TeX, or call
an AI provider. Compilation is not checked and is not a completion condition.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Mapping

from .assembly import AssemblyResult, assemble_files, merge_blocks
from .package import Limits, SourceTree, unpack
from .parser import parse_project

_DOCUMENT_CLASS = re.compile(r"\\(?:documentclass|documentstyle)\b")
_BEGIN_DOCUMENT = re.compile(r"\\begin\s*\{document\}")
_BINARY_SUFFIXES = frozenset({
    ".pdf", ".ps", ".eps", ".png", ".jpg", ".jpeg", ".gif",
    ".bbl", ".bib", ".sty", ".cls", ".bst", ".zip", ".gz", ".tar",
})
_DEPENDENCY_CODES = frozenset({
    "missing_include", "missing_resource", "unsupported_include_type",
    "path_outside_project",
})


@dataclass
class PreparedSource:
    entry: str
    source_tree_hash: str
    assembly: AssemblyResult
    document: dict
    coverage: dict
    parser_errors: list[dict]
    dependency_warnings: list[dict]

    @property
    def diagnostics(self) -> list[dict]:
        return [*self.assembly.diagnostics, *self.parser_errors,
                *self.dependency_warnings]

    @property
    def source_map(self) -> dict:
        return self.assembly.source_map()

    def summary(self) -> dict:
        return {
            "entry": self.entry,
            "entry_bytes": len(self.assembly.data),
            "blocks": len(self.document.get("blocks", [])),
            "sections": len(self.document.get("sections", [])),
            "parser_errors": len(self.parser_errors),
            "dependencies": len(self.dependency_warnings),
            "coverage": self.coverage,
        }


def looks_like_tex(raw: bytes) -> bool:
    """Return true when raw bytes contain a recognizable TeX document."""
    if b"\x00" in raw:
        return False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return bool(_DOCUMENT_CLASS.search(text) and _BEGIN_DOCUMENT.search(text))


def load_directory(root: Path) -> SourceTree:
    root = root.resolve()
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"refusing symlink in source tree: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith("../"):
            raise ValueError(f"source path escapes tree: {relative}")
        files[relative] = path.read_bytes()
    if not files:
        raise ValueError(f"source directory is empty: {root}")
    return SourceTree("directory", files)


def load_source(source: Path) -> SourceTree:
    if source.is_dir():
        return load_directory(source)
    return unpack(source.read_bytes(), Limits())


def entry_candidates(tree: SourceTree) -> list[str]:
    candidates: list[str] = []
    readme = tree.files.get("00README.json")
    if readme is not None:
        try:
            payload = json.loads(readme)
            for item in payload.get("sources", []):
                if not isinstance(item, dict) or item.get("usage") != "toplevel":
                    continue
                name = item.get("filename")
                if isinstance(name, str) and name in tree.files:
                    if looks_like_tex(tree.files[name]):
                        candidates.append(name)
        except (ValueError, TypeError):
            pass
    if candidates:
        return candidates
    for name, raw in sorted(tree.files.items()):
        suffix = Path(name).suffix.lower()
        if suffix in _BINARY_SUFFIXES:
            continue
        if suffix != ".tex" and suffix:
            continue
        if looks_like_tex(raw):
            candidates.append(name)
    return candidates


def select_entry(tree: SourceTree, requested: str | None = None) -> str:
    if requested:
        if requested not in tree.files:
            raise ValueError(f"entry not found in source tree: {requested}")
        return requested
    candidates = entry_candidates(tree)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("no TeX document candidate; pass an explicit entry")
    raise ValueError("multiple TeX entry candidates; pass an explicit entry: "
                     + ", ".join(candidates[:8]))


def _parse_origin_files(tree: SourceTree, origin_files: list[str], root: Path, *,
                        recover: bool, transparent: bool
                        ) -> tuple[dict[str, list[dict]], list[dict], list[dict]]:
    blocks_by_file: dict[str, list[dict]] = {}
    fatal: list[dict] = []
    dependencies: list[dict] = []
    for relative in origin_files:
        path = root / relative
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".tex":
            allow_non_tex = False
        elif not suffix and looks_like_tex(path.read_bytes()):
            allow_non_tex = True
        else:
            continue
        try:
            parsed = parse_project(
                path, project_root=root,
                recover_parse_errors=recover,
                transparent_containers=transparent,
                allow_non_tex_entry=allow_non_tex)
        except (OSError, ValueError, RuntimeError) as exc:
            fatal.append({"code": "parse_failed", "path": relative,
                          "message": str(exc)})
            continue
        blocks_by_file[relative] = [
            block for block in parsed.get("blocks", [])
            if block.get("source", {}).get("path") == relative
        ]
        for diagnostic in parsed.get("diagnostics", []):
            if diagnostic.get("severity") != "error":
                continue
            item = {"code": diagnostic.get("code"),
                    "path": relative,
                    "message": diagnostic.get("message")}
            if diagnostic.get("code") in _DEPENDENCY_CODES:
                dependencies.append(item)
            else:
                fatal.append(item)
    return blocks_by_file, fatal, dependencies


def _coverage(assembly: AssemblyResult, document: dict,
              parser_errors: list[dict], dependencies: list[dict]) -> dict:
    coverage = assembly.coverage()
    coverage["content_complete"] = coverage["complete"]
    coverage["assembly_complete"] = coverage["content_complete"]
    coverage["structure_complete"] = not parser_errors and bool(document["blocks"])
    coverage["parser_errors"] = len(parser_errors)
    coverage["parser_error_codes"] = sorted({item.get("code") for item in parser_errors})
    coverage["missing_dependencies"] = len(dependencies)
    coverage["dependency_error_codes"] = sorted({item.get("code") for item in dependencies})
    coverage["document_complete"] = (
        coverage["content_complete"] and coverage["structure_complete"])
    coverage["complete"] = coverage["document_complete"]
    if parser_errors:
        coverage["reasons"] = sorted(set(coverage.get("reasons", [])) | {"parser_errors"})
    return coverage


def prepare_source(tree: SourceTree, entry: str | None = None, *,
                   recover_parse_errors: bool = True,
                   transparent_containers: bool = True) -> PreparedSource:
    selected = select_entry(tree, entry)
    assembly = assemble_files(tree.files, selected)
    problems = assembly.validate(tree.files)
    if problems:
        raise ValueError(f"assembly source map is invalid: {problems[:1]}")
    with TemporaryDirectory(prefix="prepare-") as temporary:
        materialized = Path(temporary) / "tree"
        tree.materialize(materialized)
        blocks_by_file, parser_errors, dependencies = _parse_origin_files(
            tree, assembly.coverage()["origin_files"], materialized,
            recover=recover_parse_errors,
            transparent=transparent_containers)
    document = merge_blocks(assembly, blocks_by_file, source_tree_hash=tree.digest)
    coverage = _coverage(assembly, document, parser_errors, dependencies)
    document["coverage"] = coverage
    document["diagnostics"] = [*assembly.diagnostics, *parser_errors, *dependencies]
    return PreparedSource(
        entry=selected,
        source_tree_hash=tree.digest,
        assembly=assembly,
        document=document,
        coverage=coverage,
        parser_errors=parser_errors,
        dependency_warnings=dependencies,
    )


def write_outputs(prepared: PreparedSource, out: Path, *, source: Path | None = None,
                  parser_version: str = "", parse_options: Mapping | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "entry.tex").write_bytes(prepared.assembly.data)
    (out / "source-map.json").write_text(
        json.dumps(prepared.source_map, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "document.json").write_text(
        json.dumps(prepared.document, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "coverage.json").write_text(
        json.dumps(prepared.coverage, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "diagnostics.json").write_text(
        json.dumps(prepared.diagnostics, indent=1, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "schema": "qecgraph.prepare/2",
        "source": str(source) if source is not None else None,
        "entry": prepared.entry,
        "source_tree_hash": prepared.source_tree_hash,
        "entry_sha256": hashlib.sha256(prepared.assembly.data).hexdigest(),
        "entry_bytes": len(prepared.assembly.data),
        "coverage": prepared.coverage,
        "documents": prepared.document["documents"],
        "blocks": len(prepared.document["blocks"]),
        "sections": len(prepared.document["sections"]),
        "parser_version": parser_version,
        "parse_options": dict(parse_options or {}),
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return manifest
