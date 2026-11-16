"""Source-format transformations only; no block classification or extraction."""

from __future__ import annotations

import base64
from difflib import SequenceMatcher
from dataclasses import dataclass
import gzip
import hashlib
import io
from pathlib import Path
import re
import tarfile

from jsonschema import Draft202012Validator
from .encoding import project_encoding
from .package import Limits, PackageError, SourceTree, read_bounded, unpack


@dataclass(frozen=True)
class NormalizedInput:
    tree: SourceTree
    entry: str
    provenance: dict


def known_format_plan(tree: SourceTree, entry=None):
    """Choose only fixed, literal grammar adapters; no model or parser calls."""
    from .prepare import select_entry

    dialects, aliases = _known_adapters(tree, entry)
    if entry is None:
        try:
            entry = select_entry(tree)
        except ValueError:
            entry = dialects[0] if len(dialects) == 1 else None
    if entry is None or (not aliases and entry not in dialects):
        return None
    return dict(
        status="ready",
        entry=entry,
        encodings=[],
        edits=[],
        unresolved=[],
        declaration_aliases=aliases,
        dialect="harvmac" if entry in dialects else "latex",
    )


def _known_adapters(tree, entry):
    from .dialects import declaration_alias_edits, harvmac_edits

    dialects, aliases = [], []
    for path, raw in tree.files.items():
        if not path.endswith(".tex") and path != entry:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        try:
            if declaration_alias_edits(text):
                aliases.append(path)
        except ValueError:
            pass
        if r"\input" in text and "harvmac" in text:
            try:
                harvmac_edits(text)
            except ValueError:
                continue
            dialects.append(path)
    return dialects, aliases


def load_for_preparation(
    source: Path, *, repair_legacy_tar=False
) -> tuple[SourceTree, list[dict]]:
    """Retain strict archive checks; repair only a verified missing tar footer."""
    from .prepare import load_directory

    if source.is_dir():
        return load_directory(source), []
    with source.open("rb") as stream:
        raw = read_bounded(stream, Limits().input_bytes)
    try:
        # latin1 is only a format-recognition probe. unpack returns ORIGINAL bytes;
        # no encoding conversion is accepted until an explicit plan is validated.
        return unpack(raw, encoding="latin1"), []
    except PackageError as exc:
        if (
            not repair_legacy_tar
            or str(exc) != "Tar missing a valid zero-block trailer"
        ):
            raise
    data = raw
    if raw.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            data = read_bounded(stream, Limits().expanded_bytes)
    if len(data) % 512:
        raise ValueError("Legacy tar repair requires complete 512-byte records")
    # The strict reader already checked every visible member. Legacy writers may
    # leave nonzero record padding after the first end marker. Keep those bytes
    # in the audit record and reject a second archive rather than silently merge.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        list(archive)
        end = archive.offset
    tail = data[end:]
    for offset in range(0, len(tail) - 511, 512):
        try:
            header = tarfile.TarInfo.frombuf(
                tail[offset : offset + 512], "utf-8", "surrogateescape"
            )
        except tarfile.HeaderError:
            continue
        if header.name and data[:end].find(tail[offset : offset + 512]) < 0:
            raise ValueError(
                "Additional archive headers after the end marker require review"
            )
    repaired = data[:end] + bytes(1024)
    tree = unpack(repaired)
    return tree, [
        {
            "operation": "normalize_tar_zero_footer",
            "original_package_sha256": hashlib.sha256(raw).hexdigest(),
            "derived_tar_sha256": hashlib.sha256(repaired).hexdigest(),
            "appended_bytes": 1024,
            "retained_original_trailer_base64": base64.b64encode(tail).decode("ascii"),
        }
    ]


_CONDITION = re.compile(
    r"\\(?:ifdefined\s*\\[A-Za-z@]+|ifx\s*\\[A-Za-z@]+\s*\\undefined|if\s+0)\s*"
)
_DELIMITERS = re.compile(r"^[\s{}$\[\]\\()]*$")
_DRAWING = {
    "\\begin{tikzpicture}": "\\begin{verbatim}",
    "\\end{tikzpicture}": "\\end{verbatim}",
}
_TOKENS = re.compile(r"\\[A-Za-z@]+|[A-Za-z0-9]+|[^\s{}$\[\]\\()]")


def _check_edit(edit, text, evidence_text=None):
    old, new = edit["old"], edit["new"]
    if not old or len(old) > 2048 or len(new) > 2048 or old not in text:
        raise ValueError(
            "Normalization edit does not match a bounded supplied source slice"
        )
    occurrence = edit.get("occurrence")
    if text.count(old) != 1 and occurrence is None:
        raise ValueError(
            "Normalization edit is ambiguous; include unique surrounding syntax"
        )
    if occurrence is not None and not 1 <= occurrence <= text.count(old):
        raise ValueError("Normalization edit occurrence does not exist")
    if old == new:
        raise ValueError("Normalization edit does not change syntax")
    # Literal wrapper conversion preserves drawing code without asking the model
    # to execute TikZ or choose colors/branches. Never wrap arbitrary source.
    if _DRAWING.get(old) == new:
        return
    if any(marker in old for marker in _DRAWING):
        raise ValueError(
            "Drawing conversion accepts only exact begin/end tikzpicture tokens from syntax_sites; "
            "replace each with the corresponding verbatim token. Keep all surrounding whitespace, "
            "options and comments unchanged; use occurrence to locate repeated wrappers."
        )
    if _CONDITION.fullmatch(old) and new.strip() in {"\\iftrue", "\\iffalse"}:
        _check_guard(edit, text, evidence_text)
        return
    if _CONDITION.match(old):
        raise ValueError(
            "Compilation edits must replace only the guard header from syntax_sites; "
            "quote surrounding context in evidence, and keep both branch bodies unchanged"
        )
    if _CONDITION.match(old):
        raise ValueError(
            "Guard edits must use only the header in old and iftrue/iffalse in new; "
            "quote surrounding source in evidence and use syntax_sites occurrence"
        )
    _check_delimiters(old, new)


def _check_guard(edit, text, evidence_text):
    old, new = edit["old"], edit["new"].strip()
    if not edit["evidence"] or edit["evidence"] not in (evidence_text or text):
        raise ValueError(
            "A compilation-view choice requires literal same-file evidence"
        )
    if re.fullmatch(r"\\if\s+0\s*", old):
        from .assembly import _mask_comments

        start = list(re.finditer(re.escape(old), text))[
            edit.get("occurrence", 1) - 1
        ].end()
        following = _mask_comments(text[start:]).lstrip()
        if not following or following[0] in "0\\" or new != "\\iffalse":
            raise ValueError("Only a literal false if-0 comparison can be normalized")
    else:
        # Only a document-wrapper switch may be selected. A scientific
        # conditional without document boundaries is never a format repair.
        matched = False
        for occurrence in re.finditer(re.escape(old), text):
            close = text.find("\\fi", occurrence.end())
            branch = text[occurrence.end() : close if close >= 0 else len(text)]
            matched |= any(
                marker in branch
                for marker in (
                    "\\documentclass",
                    "\\begin{document}",
                    "\\end{document}",
                )
            )
        if not matched:
            raise ValueError("Only compilation-wrapper conditionals may be normalized")


def _check_delimiters(old, new):
    # Repairs may insert/remove delimiters, but cannot change words, macro names,
    # numbers, formulas, comments or even whitespace around a comment.
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(old), len(new)) - prefix
        and old[-suffix - 1] == new[-suffix - 1]
    ):
        suffix += 1
    old_delta = old[prefix : len(old) - suffix if suffix else len(old)]
    new_delta = new[prefix : len(new) - suffix if suffix else len(new)]
    if (
        "%" in old
        or _TOKENS.findall(old) != _TOKENS.findall(new)
        or not _DELIMITERS.fullmatch(old_delta)
        or not _DELIMITERS.fullmatch(new_delta)
    ):
        raise ValueError(
            "Normalization may repair delimiters, not rewrite source content"
        )


def apply_plan(tree: SourceTree, plan: dict, schema: dict) -> NormalizedInput:
    """Apply a bounded proposed format plan to a derived copy; retain originals."""
    Draft202012Validator(schema).validate(plan)
    if plan["status"] != "ready" or plan["unresolved"]:
        raise ValueError(
            "Preparation plan requires review: " + "; ".join(plan["unresolved"])
        )
    if plan["entry"] not in tree.files:
        raise ValueError("Preparation plan selects a missing entry")
    files = dict(tree.files)
    originals, changes = {}, []
    seen = set()
    for choice in plan["encodings"]:
        path = choice["path"]
        if path in seen or path not in files:
            raise ValueError("Encoding plan has a duplicate or missing source")
        seen.add(path)
        files[path], mapping = project_encoding(files[path], choice["encoding"])
        if mapping:
            originals[path] = tree.files[path]
            changes.append({"operation": "encoding", "path": path, **mapping})
    by_path = _collect_edits(files, plan)
    _apply_edits(tree, files, by_path, originals, changes)
    normalized = SourceTree(tree.format, files)
    for path, raw in files.items():
        if path.endswith(".tex") or path == plan["entry"]:
            raw.decode("utf-8")
    provenance = {
        "schema": "qecgraph.preparation_normalization/1",
        "status": "proposed",
        "original_tree_sha256": tree.digest,
        "normalized_tree_sha256": normalized.digest,
        "entry": plan["entry"],
        "plan": plan,
        "changes": changes,
        "original_files": {
            path: {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes_base64": base64.b64encode(raw).decode("ascii"),
            }
            for path, raw in originals.items()
        },
    }
    codecs = {choice["path"]: choice["encoding"] for choice in plan["encodings"]}
    provenance["source_projections"] = {
        path: _source_projection(
            raw, files[path], by_path.get(path, []), codecs.get(path, "utf-8")
        )
        for path, raw in originals.items()
    }
    return NormalizedInput(normalized, plan["entry"], provenance)


def _collect_edits(files, plan):
    # Validate edits against the initial decoded copy, then apply them right-to-left
    # so an earlier replacement cannot redirect a later edit.
    by_path: dict[str, list] = {}
    for edit in plan["edits"]:
        path = edit["path"]
        if path not in files:
            raise ValueError("Preparation edit references a missing file")
        text = files[path].decode("utf-8")
        evidence_path = edit.get("evidence_path", path)
        if evidence_path not in {path, plan["entry"]}:
            raise ValueError(
                "Compilation evidence must come from this file or the selected entry"
            )
        _check_edit(edit, text, files[evidence_path].decode("utf-8"))
        start = list(re.finditer(re.escape(edit["old"]), text))[
            edit.get("occurrence", 1) - 1
        ].start()
        by_path.setdefault(path, []).append((start, start + len(edit["old"]), edit))
    if plan.get("dialect") == "harvmac":
        from .dialects import harvmac_edits

        path = plan["entry"]
        for start, end, edit in harvmac_edits(files[path].decode("utf-8")):
            by_path.setdefault(path, []).append((start, end, {**edit, "path": path}))
    for path in plan.get("declaration_aliases", []):
        from .dialects import declaration_alias_edits

        if path not in files:
            raise ValueError("Declaration conversion references a missing file")
        for start, end, edit in declaration_alias_edits(files[path].decode("utf-8")):
            by_path.setdefault(path, []).append((start, end, {**edit, "path": path}))
    return by_path


def _apply_edits(tree, files, by_path, originals, changes):
    for path, edits in by_path.items():
        text = files[path].decode("utf-8")
        _check_drawing_pairs(text, edits)
        cursor = len(text)
        originals[path] = tree.files[path]
        for start, end, edit in sorted(edits, reverse=True, key=lambda row: row[0]):
            if end > cursor:
                raise ValueError("Overlapping preparation edits")
            text = text[:start] + edit["new"] + text[end:]
            changes.append(
                {"operation": "syntax", "char_start": start, "char_end": end, **edit}
            )
            cursor = start
        files[path] = text.encode("utf-8")


def _check_drawing_pairs(text, edits):
    selected = {start for start, _, edit in edits if edit["old"] in _DRAWING}
    if not selected:
        return
    stack = []
    for match in re.finditer(r"\\(begin|end)\{tikzpicture\}", text):
        if match[1] == "begin":
            stack.append(match.start())
        elif stack:
            opening = stack.pop()
            if (opening in selected) != (match.start() in selected):
                raise ValueError(
                    "Drawing conversion must use the matching original wrapper pair"
                )
            selected.discard(opening)
            selected.discard(match.start())
    if selected:
        raise ValueError("Drawing conversion requires a closed original wrapper pair")


def _source_projection(original, normalized, edits, encoding):
    """Map copied characters to authoritative byte spans; inserted syntax has no origin."""
    text = original.decode(encoding)
    byte_offsets = [0]
    for char in text:
        byte_offsets.append(byte_offsets[-1] + len(char.encode(encoding)))
    spans, cursor, out = [], 0, 0
    for start, end, edit in sorted(edits, key=lambda item: item[0]):
        if start > cursor:
            length = start - cursor
            spans.append(
                {
                    "char_start": out,
                    "char_end": out + length,
                    "original_bytes": [byte_offsets[cursor], byte_offsets[start]],
                }
            )
            out += length
        for tag, a, b, c, d in SequenceMatcher(
            None, text[start:end], edit["new"], autojunk=False
        ).get_opcodes():
            span = {"char_start": out + c, "char_end": out + d, "original_bytes": None}
            original_span = [byte_offsets[start + a], byte_offsets[start + b]]
            span["original_bytes" if tag == "equal" else "replaces_original_bytes"] = (
                original_span
            )
            spans.append(span)
        out += len(edit["new"])
        cursor = end
    if cursor < len(text):
        spans.append(
            {
                "char_start": out,
                "char_end": out + len(text) - cursor,
                "original_bytes": [byte_offsets[cursor], byte_offsets[-1]],
            }
        )
    return {
        "original_encoding": encoding,
        "normalized_sha256": hashlib.sha256(normalized).hexdigest(),
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "segments": spans,
    }
