"""Source-only recognition, assembly and managed artifact publication.

prepare_input never parses blocks or calls a model. prepare_source and
parse_prepared are compatibility facades for the independent prepared_parser.
Compilation is not checked. Original bytes remain the authoritative source.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import mkdtemp
from typing import Mapping
import uuid

from .assembly import AssemblyResult, assemble_files
from .entry import select_main_document
from .package import Limits, SourceTree, unpack

_DOCUMENT_CLASS = re.compile(r"\\(?:documentclass|documentstyle)\b")
_BEGIN_DOCUMENT = re.compile(r"\\begin\s*\{document\}")
_BINARY_SUFFIXES = frozenset({
    ".pdf", ".ps", ".eps", ".png", ".jpg", ".jpeg", ".gif",
    ".bbl", ".bib", ".sty", ".cls", ".bst", ".zip", ".gz", ".tar",
})
PREPARE_RULE_VERSION = "prepare-rules-v7"

@dataclass
class PreparedInput:
    """Source-only handoff; constructing it never invokes the parser or AI."""
    entry: str
    source_tree_hash: str
    assembly: AssemblyResult


def prepare_input(tree: SourceTree, entry: str | None = None) -> PreparedInput:
    selected = select_entry(tree, entry)
    assembly = assemble_files(tree.files, selected)
    problems = assembly.validate(tree.files)
    if problems:
        raise ValueError(f"assembly source map is invalid: {problems[:1]}")
    return PreparedInput(selected, tree.digest, assembly)


@dataclass
class PreparedSource:
    entry: str
    source_tree_hash: str
    assembly: AssemblyResult
    document: dict
    coverage: dict
    parser_errors: list[dict]
    dependency_warnings: list[dict]
    normalization: dict | None = None

    @property
    def diagnostics(self) -> list[dict]:
        return [*self.assembly.diagnostics, *self.parser_errors,
                *self.dependency_warnings]

    @property
    def source_map(self) -> dict:
        mapping = self.assembly.source_map()
        if self.normalization and self.normalization.get('original_tree_sha256'):
            mapping.update(source_layer='derived_normalized',
                           original_tree_sha256=self.normalization['original_tree_sha256'],
                           normalization='normalization.json')
        return mapping

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
    selected, _method = select_main_document(tree.files, candidates)
    if selected is not None:
        return selected
    raise ValueError("multiple TeX entry candidates; pass an explicit entry: "
                     + ", ".join(candidates[:8]))


def prepare_source(tree: SourceTree, entry: str | None = None, *,
                   recover_parse_errors: bool = True,
                   transparent_containers: bool = True) -> PreparedSource:
    """Compatibility facade: prepare input, then validate with the downstream parser."""
    return parse_prepared(prepare_input(tree, entry), tree,
                          recover_parse_errors=recover_parse_errors,
                          transparent_containers=transparent_containers)


def parse_prepared(prepared: PreparedInput, tree: SourceTree, *,
                   recover_parse_errors: bool = True,
                   transparent_containers: bool = True) -> PreparedSource:
    """Compatibility entry point for the independent downstream parser."""
    from .prepared_parser import parse_prepared as parse
    return parse(prepared, tree, recover_parse_errors=recover_parse_errors,
                 transparent_containers=transparent_containers)


_MANAGED_SCHEMA_PREFIX = "qecgraph.prepare/"


def _managed_output(directory: Path) -> bool:
    """Return true when a non-empty directory holds a prepare manifest."""
    manifest = directory / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(payload, dict)
            and str(payload.get("schema", "")).startswith(_MANAGED_SCHEMA_PREFIX))


def _check_output_root(out: Path, source: Path | None, overwrite: bool) -> None:
    if out.is_symlink():
        raise ValueError(f"refusing symbolic-link output directory: {out}")
    if out.exists() and not out.is_dir():
        raise ValueError(f"output path is not a directory: {out}")
    if source is not None:
        target = out.resolve()
        origin = source.resolve()
        if origin == target or origin in target.parents:
            raise ValueError(f"output directory is inside the source: {out}")
        if target == origin or target in origin.parents:
            raise ValueError(f"source is inside the output directory: {out}")
    if out.is_dir() and any(out.iterdir()):
        if not overwrite and not _managed_output(out):
            raise ValueError(
                f"refusing to replace unmanaged output directory: {out}; "
                "pass --overwrite to replace it")


def _journal_path(out: Path) -> Path:
    return out.parent / f".{out.name}.transaction.json"


def _write_journal(out: Path, payload: dict) -> None:
    journal = _journal_path(out)
    temporary = journal.with_name(journal.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(temporary, journal)


def _remove_journal(out: Path) -> None:
    try:
        _journal_path(out).unlink()
    except FileNotFoundError:
        pass


def _sibling(out: Path, name: str, prefix: str) -> Path | None:
    """Return a journal-named sibling created by this writer, or None."""
    if (not isinstance(name, str) or "/" in name
            or not name.startswith(prefix)):
        return None
    candidate = out.parent / name
    return candidate if candidate.parent == out.parent else None


def _manifest_digest(directory: Path) -> str | None:
    manifest = directory / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        return hashlib.sha256(manifest.read_bytes()).hexdigest()
    except OSError:
        return None


def _artifacts_match(directory: Path, expected: dict) -> bool:
    for name, digest in expected.items():
        path = directory / name
        if not path.is_file():
            return False
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                return False
        except OSError:
            return False
    return True


def recover_output(out: Path) -> str | None:
    """Restore or clean up an interrupted publish described by the journal.

    Returns ``"restored"`` when the previous complete directory was put back,
    ``"committed"`` when the expected new directory is in place, ``"aborted"``
    when the old directory was never moved, ``"cleaned"`` when only staged
    leftovers were removed, ``"conflict"`` when the target is neither the
    expected new version nor the recorded old one, or None when there is no
    journal.

    A conflict keeps the journal and the backup so the only copy of the old
    result is never deleted because a directory merely exists.
    """
    journal = _journal_path(out)
    if not journal.is_file():
        return None
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    staging = _sibling(out, payload.get("staging", ""),
                       f".{out.name}.staging-")
    backup = (_sibling(out, payload.get("backup", ""),
                       f".{out.name}.backup-")
              if payload.get("backup") else None)
    expected = payload.get("new_manifest_sha256")
    previous = payload.get("previous_manifest_sha256")

    def clean_staging() -> None:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)

    if out.is_dir():
        current = _manifest_digest(out)
        if expected is not None and current == expected:
            recorded = payload.get("artifacts")
            if (isinstance(recorded, dict) and recorded
                    and not _artifacts_match(out, recorded)):
                return "conflict"
            clean_staging()
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
            _remove_journal(out)
            return "committed"
        if previous is not None and current == previous:
            clean_staging()
            _remove_journal(out)
            return "aborted"
        return "conflict"
    if backup is not None and backup.is_dir():
        os.replace(backup, out)
        clean_staging()
        _remove_journal(out)
        return "restored"
    if staging is not None and staging.is_dir():
        os.replace(staging, out)
        _remove_journal(out)
        return "cleaned"
    _remove_journal(out)
    return "cleaned"


def _write_artifacts(directory: Path, artifacts: Mapping[str, bytes]) -> None:
    for name, data in artifacts.items():
        path = directory / name
        if Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
            raise ValueError("Unsafe managed artifact path")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def write_outputs(prepared: PreparedSource, out: Path, *, source: Path | None = None,
                  parser_version: str = "", parse_options: Mapping | None = None,
                  overwrite: bool = False,
                  prepare_version: str = PREPARE_RULE_VERSION) -> dict:
    """Write the prepare artifacts, replacing a managed output directory whole.

    A non-empty directory without a prepare manifest is refused unless
    ``overwrite`` is set. Artifacts are built in a staging directory and the
    directory is replaced through a journaled backup, so a normal failure keeps
    the previous complete result and an interrupted publish is recoverable with
    :func:`recover_output` (also called before the next write).
    """
    recovered = recover_output(out)
    if recovered == "conflict":
        raise ValueError(
            f"interrupted publish conflicts with the current contents of {out}; "
            f"the previous result is kept at {out.parent} (see "
            f"{_journal_path(out).name}); move the unexpected directory aside "
            "and run --recover again")
    _check_output_root(out, source, overwrite)
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
        "prepare_version": prepare_version,
        "parse_options": dict(parse_options or {}),
    }
    if prepared.normalization is not None:
        manifest['normalization_sha256'] = hashlib.sha256(json.dumps(
            prepared.normalization, sort_keys=True, separators=(',', ':'),
            ensure_ascii=False).encode('utf-8')).hexdigest()
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    artifacts = {
        "entry.tex": prepared.assembly.data,
        "source-map.json": json.dumps(
            prepared.source_map, indent=1, ensure_ascii=False).encode("utf-8"),
        "document.json": json.dumps(
            prepared.document, indent=1, ensure_ascii=False).encode("utf-8"),
        "coverage.json": json.dumps(
            prepared.coverage, indent=1, ensure_ascii=False).encode("utf-8"),
        "diagnostics.json": json.dumps(
            prepared.diagnostics, indent=1, ensure_ascii=False).encode("utf-8"),
        "manifest.json": json.dumps(
            manifest, indent=1, ensure_ascii=False).encode("utf-8"),
    }
    if prepared.normalization is not None:
        artifacts['normalization.json'] = json.dumps(
            prepared.normalization, indent=1, ensure_ascii=False).encode('utf-8')
    publish_artifacts(artifacts, out, source=source, overwrite=overwrite)
    return manifest


def publish_artifacts(artifacts: Mapping[str, bytes], out: Path, *, source=None, overwrite=False):
    """Shared journaled publication for versioned preparation material formats."""
    if recover_output(out) == "conflict":
        raise ValueError("Interrupted material publication conflicts with existing output")
    _check_output_root(out, source, overwrite)
    out.parent.mkdir(parents=True, exist_ok=True)
    previous_manifest = _manifest_digest(out) if out.is_dir() else None
    staging = Path(mkdtemp(dir=out.parent, prefix=f".{out.name}.staging-"))
    journal = {"out": out.name, "staging": staging.name, "backup": None,
               "phase": "staged",
               "new_manifest_sha256":
                   hashlib.sha256(artifacts["manifest.json"]).hexdigest(),
               "previous_manifest_sha256": previous_manifest,
               "artifacts": {
                   name: hashlib.sha256(data).hexdigest()
                   for name, data in artifacts.items()}}
    backup: Path | None = None
    try:
        _write_artifacts(staging, artifacts)
        _write_journal(out, journal)
        if out.exists():
            backup = out.parent / f".{out.name}.backup-{uuid.uuid4().hex[:12]}"
            journal["backup"] = backup.name
            journal["phase"] = "backup"
            _write_journal(out, journal)
            os.replace(out, backup)
            try:
                os.replace(staging, out)
            except BaseException:
                os.replace(backup, out)
                _remove_journal(out)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            os.replace(staging, out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if out.is_dir():
            _remove_journal(out)
