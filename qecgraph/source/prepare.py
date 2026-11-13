"""Offline recognition and conversion of LaTeX source trees.

This module is the supported offline preparation layer:

1. recognize a TeX entry from content, not only from a ``.tex`` suffix;
2. assemble literal includes and literal zero-argument path macros into an
   entry that is made only of original source bytes;
3. parse the assembled entry once, so entry-level declarations apply to every
   included fragment, and merge its blocks into an entry-ordered document model;
4. report content, structure and dependency completeness separately.

It does not expand arbitrary macros, evaluate conditionals, run TeX, or call
an AI provider. Compilation is not checked and is not a completion condition.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory, mkdtemp
from typing import Mapping
import uuid

from .assembly import (
    LITERAL_ENVIRONMENTS,
    AssemblyResult,
    _DECLARATIONS,
    _is_conditional,
    _skip_definition,
    EntryCoordinates,
    SourceLineIndex,
    assemble_files,
    condition_regions,
    document_bounds,
    entry_source_spans,
    merge_blocks,
)
from .package import Limits, SourceTree, unpack
from .parser import parse_project

_DOCUMENT_CLASS = re.compile(r"\\(?:documentclass|documentstyle)\b")
_BEGIN_DOCUMENT = re.compile(r"\\begin\s*\{document\}")
_BINARY_SUFFIXES = frozenset({
    ".pdf", ".ps", ".eps", ".png", ".jpg", ".jpeg", ".gif",
    ".bbl", ".bib", ".sty", ".cls", ".bst", ".zip", ".gz", ".tar",
})
PREPARE_RULE_VERSION = "prepare-rules-v2"

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


_ENTRY_NAME = "__qecgraph_prepared_entry__.tex"


def _entry_name(files: Mapping[str, bytes]) -> str:
    name = _ENTRY_NAME
    suffix = 0
    while name in files:
        suffix += 1
        name = f"__qecgraph_prepared_entry_{suffix}__.tex"
    return name


def _run_parse(path: Path, root: Path, data: bytes, *, recover: bool,
               transparent: bool) -> dict:
    path.write_bytes(data)
    return parse_project(
        path, project_root=root,
        recover_parse_errors=recover,
        transparent_containers=transparent,
        allow_non_tex_entry=True)


def _shift_parsed(parsed: dict, name: str, shift: int, prefix: str,
                  parse_offset: int = 0,
                  ) -> tuple[list[dict], list[dict]]:
    """Re-base one chunk parse onto parse-copy coordinates and unique keys."""
    blocks: list[dict] = []
    for block in parsed.get("blocks", []):
        source = block.get("source") or {}
        if source.get("path") != name:
            continue
        start = int(source.get("char_start", 0))
        end = int(source.get("char_end", 0))
        if start < shift:
            continue
        block = dict(block)
        block["source"] = {**source, "char_start": start - shift + parse_offset,
                           "char_end": max(start, end) - shift + parse_offset}
        key = block.get("key")
        parent = block.get("parent_key")
        block["key"] = f"{prefix}-{key}" if key else key
        block["parent_key"] = f"{prefix}-{parent}" if parent else parent
        blocks.append(block)
    diagnostics: list[dict] = []
    for diagnostic in parsed.get("diagnostics", []):
        source = diagnostic.get("source")
        if not isinstance(source, dict) or source.get("path") != name:
            continue
        start = source.get("char_start")
        end = source.get("char_end")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start < shift:
            continue
        diagnostic = dict(diagnostic)
        diagnostic["source"] = {
            **source, "char_start": start - shift + parse_offset,
            "char_end": max(start, end) - shift + parse_offset}
        diagnostics.append(diagnostic)
    return blocks, diagnostics


def _salvage_ranges(path: Path, root: Path, assembly: AssemblyResult, name: str,
                    coords: EntryCoordinates, *, recover: bool, transparent: bool
                    ) -> tuple[list[dict], list[dict]] | None:
    """Parse the entry in chunks when one malformed region breaks the walk.

    Each chunk is parsed with the entry preamble prepended, so shared
    declarations still apply, and its blocks are re-based onto parse-copy
    coordinates. Chunks split at resolved top-level includes, which keeps a
    broken file from discarding the structure of every other file.
    """
    _, body_start, end_start = document_bounds(coords.text)
    if body_start is None:
        return None
    body_end = end_start if end_start is not None else len(coords.text)
    text = coords.copy_text()
    body_parse_start = coords.to_parse(body_start)
    body_parse_end = coords.to_parse(body_end)
    preamble = text[:body_parse_start]
    shift = len(preamble)
    boundaries: list[tuple[int, int]] = []
    for event in assembly.events:
        if (event.outcome != "resolved" or event.path != assembly.entry
                or event.out_char_start is None or event.out_char_end is None):
            continue
        boundaries.append((coords.to_parse(event.out_char_start),
                           coords.to_parse(event.out_char_end)))
    boundaries.sort()
    ranges: list[tuple[int, int]] = []
    cursor = body_parse_start
    for low, high in boundaries:
        if low < cursor:
            continue
        if low > cursor:
            ranges.append((cursor, low))
        ranges.append((low, high))
        cursor = high
    if cursor < body_parse_end:
        ranges.append((cursor, body_parse_end))
    if len(ranges) <= 1:
        return None
    blocks: list[dict] = []
    diagnostics: list[dict] = []
    for index, (low, high) in enumerate(ranges):
        chunk = (preamble + text[low:high]).encode("utf-8")
        parsed = _run_parse(path, root, chunk, recover=recover,
                            transparent=transparent)
        chunk_blocks, chunk_diagnostics = _shift_parsed(
            parsed, name, shift, f"part{index}", low - body_parse_start)
        blocks.extend(chunk_blocks)
        diagnostics.extend(chunk_diagnostics)
    return blocks, diagnostics


def _outside_dependencies(parsed: dict, name: str, coords: EntryCoordinates,
                          body_start: int | None, outside: list[str],
                          selected: str) -> list[dict]:
    """Describe parser includes whose content is not inside the entry."""
    include_in_body: dict[str, bool] = {}
    for record in parsed.get("includes", []):
        target = record.get("to")
        source = record.get("source") or {}
        if not isinstance(target, str) or source.get("path") != name:
            continue
        try:
            position = coords.to_entry(int(source.get("char_start", 0)))
        except (TypeError, ValueError):
            continue
        in_body = body_start is None or position >= body_start
        include_in_body[target] = include_in_body.get(target, False) or in_body
    dependencies: list[dict] = []
    for other in outside:
        if not other or Path(other).suffix.lower() in {".bib", ".bbl"}:
            continue
        region = "body" if include_in_body.get(other, True) else "preamble"
        dependencies.append({
            "code": "include_not_in_entry",
            "path": selected,
            "target": other,
            "region": region,
            "message": f"parser read {other!r}, which the entry does not contain",
        })
    return dependencies


def _map_diagnostic(
diagnostic: dict, assembly: AssemblyResult, name: str,
                    lines: SourceLineIndex, coords: EntryCoordinates) -> dict:
    source = diagnostic.get("source")
    if not isinstance(source, dict) or source.get("path") != name:
        return diagnostic
    try:
        start = coords.to_entry(int(source.get("char_start", 0)))
        end = max(start, coords.to_entry(int(source.get("char_end", start))))
    except (TypeError, ValueError):
        return diagnostic
    spans = entry_source_spans(assembly, start, max(end, start + 1))
    if not spans:
        return diagnostic
    path, low, high = spans[0]
    if end <= start:
        high = low
    mapped = dict(diagnostic)
    mapped["source"] = {
        "path": path,
        "char_start": low,
        "char_end": high,
        "line_start": lines.line_at(path, low),
        "line_end": lines.line_at(path, max(low, high - 1)),
    }
    return mapped


def _parse_entry(tree: SourceTree, assembly: AssemblyResult, selected: str,
                 root: Path, coords: EntryCoordinates, *,
                 recover: bool, transparent: bool
                 ) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse the assembled entry once and project diagnostics back to source.

    The entry is written into the materialized tree so the parser sees one
    document context: preamble declarations, theorem environments and macros
    that the entry defines apply to every included fragment. Blocks the parser
    reads from files outside the entry are not part of the assembled document
    and are reported instead of silently mixed in.
    """
    name = _entry_name(tree.files)
    path = root / name
    parse_text = coords.copy_text()
    try:
        parsed = _run_parse(path, root, parse_text.encode("utf-8"),
                            recover=recover, transparent=transparent)
        blocks = list(parsed.get("blocks", []))
        diagnostics = list(parsed.get("diagnostics", []))
        if recover and any(item.get("code") == "latex_parse_error"
                           for item in diagnostics):
            salvaged = _salvage_ranges(path, root, assembly, name, coords,
                                       recover=recover, transparent=transparent)
            if salvaged is not None and len(salvaged[0]) > len(blocks):
                blocks, diagnostics = salvaged
    except (OSError, ValueError, RuntimeError) as exc:
        return [], [{"code": "parse_failed", "path": selected,
                     "message": str(exc)}], []
    lines = SourceLineIndex(tree.files)
    mapped_blocks: list[dict] = []
    for block in blocks:
        source = block.get("source") or {}
        if source.get("path") != name:
            mapped_blocks.append(block)
            continue
        parse_start = int(source.get("char_start", 0))
        parse_end = max(parse_start, int(source.get("char_end", parse_start)))
        start = coords.to_entry(parse_start)
        end = max(start, coords.to_entry(parse_end))
        block_latex = parse_text[parse_start:parse_end]
        anchor = start
        for index, char in enumerate(block_latex):
            if not char.isspace():
                anchor = coords.to_entry(parse_start + index)
                break
        mapped_blocks.append({
            **block,
            "source": {**source, "char_start": start, "char_end": end},
            "latex": block_latex,
            "anchor_entry": anchor,
        })
    blocks = mapped_blocks
    outside = sorted({
        (block.get("source") or {}).get("path")
        for block in blocks
        if (block.get("source") or {}).get("path") != name
        and block.get("kind") != "bib_entry"})
    blocks = [block for block in blocks
              if (block.get("source") or {}).get("path") == name]
    _, body_start, _ = document_bounds(coords.text)
    dependencies = _outside_dependencies(parsed, name, coords, body_start,
                                         outside, selected)
    unresolved: dict[str, list[tuple[int, int]]] = {}
    for event in assembly.events:
        if event.outcome == "resolved":
            continue
        unresolved.setdefault(event.path, []).append(
            (event.source_char_start, event.source_char_end))
    fatal: list[dict] = []
    for diagnostic in diagnostics:
        diagnostic = _map_diagnostic(diagnostic, assembly, name, lines, coords)
        source = diagnostic.get("source") or {}
        position = source.get("char_start")
        if (diagnostic.get("code") in _DEPENDENCY_CODES
                and isinstance(position, int)
                and source.get("path") in unresolved
                and any(low <= position < high
                        for low, high in unresolved[source["path"]])):
            continue
        if diagnostic.get("severity") != "error":
            continue
        item = {"code": diagnostic.get("code"),
                "path": source.get("path") or selected,
                "message": diagnostic.get("message")}
        if diagnostic.get("code") in _DEPENDENCY_CODES:
            dependencies.append(item)
        else:
            fatal.append(item)
    return blocks, fatal, dependencies


_CONTROL_WORD = re.compile(r"\\([A-Za-z@]+)\*?")


def _skip_braced(text: str, index: int) -> int:
    opening = text[index]
    closing = "}" if opening == "{" else "]"
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def _prose_chars(text: str) -> int:
    """Count body letters, ignoring commands, arguments and literal content."""
    count = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "%":
            end = text.find("\n", index)
            index = len(text) if end < 0 else end + 1
            continue
        if char == "\\":
            match = _CONTROL_WORD.match(text, index)
            if not match:
                index += 2
                continue
            index = match.end()
            if match.group(1) == "csname":
                end = text.find("\\endcsname", index)
                index = (len(text) if end < 0
                         else end + len("\\endcsname"))
                continue
            if match.group(1) == "begin":
                probe = index
                while probe < len(text) and text[probe].isspace():
                    probe += 1
                if probe < len(text) and text[probe] == "{":
                    closing = text.find("}", probe)
                    environment = text[probe + 1:closing] if closing >= 0 else ""
                    if environment in LITERAL_ENVIRONMENTS:
                        closing = "\\end{" + environment + "}"
                        end = text.find(closing, probe)
                        index = len(text) if end < 0 else end + len(closing)
                        continue
            while True:
                probe = index
                while probe < len(text) and text[probe].isspace():
                    probe += 1
                if probe < len(text) and text[probe] in "{[":
                    index = _skip_braced(text, probe)
                else:
                    index = probe
                    break
            continue
        if char.isascii() and char.isalpha():
            run = 0
            while (index < len(text) and text[index].isascii()
                   and text[index].isalpha()):
                run += 1
                index += 1
            if run >= 2:
                count += run
            continue
        index += 1
    return count


def _subtract_intervals(intervals: list[tuple[int, int]],
                        holes: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pieces = list(intervals)
    for hole_low, hole_high in holes:
        remaining: list[tuple[int, int]] = []
        for low, high in pieces:
            if hole_high <= low or hole_low >= high:
                remaining.append((low, high))
                continue
            if low < hole_low:
                remaining.append((low, hole_low))
            if hole_high < high:
                remaining.append((hole_high, high))
        pieces = remaining
    return [piece for piece in pieces if piece[1] > piece[0]]


def _uncovered_entry_prose(text: str, blocks: list[dict],
                           inactive: list[tuple[int, int]] | None = None,
                           body_bounds: tuple[int, int] | None = None) -> int:
    """Count body letters that no block covers and no condition disables."""
    if body_bounds is None:
        _, body_start, end_start = document_bounds(text)
        if body_start is None:
            body_start = 0
        body_end = end_start if end_start is not None else len(text)
    else:
        body_start, body_end = body_bounds
    spans = sorted((int(block["entry"]["char_start"]),
                    int(block["entry"]["char_end"])) for block in blocks)
    gaps: list[tuple[int, int]] = []
    cursor = body_start
    for low, high in spans:
        if high <= cursor:
            continue
        low = max(low, body_start)
        high = min(high, body_end)
        if low >= high:
            continue
        if low > cursor:
            gaps.append((cursor, low))
        cursor = max(cursor, high)
        if cursor >= body_end:
            break
    if cursor < body_end:
        gaps.append((cursor, body_end))
    gaps = _subtract_intervals(gaps, inactive or [])
    return sum(_prose_chars(text[low:high]) for low, high in gaps)


_LAYOUT_COMMANDS = frozenset({
    "vspace", "hspace", "vskip", "hskip", "kern", "mkern", "mskip",
    "setlength", "addtolength", "settowidth", "setcounter", "addtocounter",
    "stepcounter", "refstepcounter", "pagestyle", "thispagestyle",
    "pagenumbering", "linespread", "fontsize", "color", "pagecolor",
    "definecolor", "vfill", "hfill", "vfil", "hfil", "vss", "hss",
    "smallskip", "medskip", "bigskip", "hrule", "vrule", "newpage",
    "clearpage", "cleardoublepage", "pagebreak", "nopagebreak", "label",
})

_FORMATTING_SWITCHES = frozenset({
    "bfseries", "mdseries", "itshape", "slshape", "scshape", "upshape",
    "rmfamily", "sffamily", "ttfamily", "normalfont", "em", "small",
    "footnotesize", "scriptsize", "tiny", "large", "Large", "LARGE",
    "huge", "Huge", "normalsize", "protect", "relax", "null", "selectfont",
})

_SPACING_SYMBOLS = frozenset({",", ";", ":", "!", "/"})


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _skip_command_arguments(text: str, index: int) -> int:
    index = _skip_whitespace(text, index)
    if index < len(text) and text[index] == "*":
        index += 1
    while True:
        probe = _skip_whitespace(text, index)
        if probe < len(text) and text[probe] in "{[":
            index = _skip_braced(text, probe)
            continue
        return probe


_CONDITIONAL_TEST_TOKENS = frozenset({
    "if", "ifx", "ifcat", "ifnum", "ifdim", "ifodd", "ifcase", "ifdefined",
    "ifcsname", "ifvoid", "ifhbox", "ifvbox", "ifeof",
})


def _one_token(text: str, index: int) -> int:
    index = _skip_whitespace(text, index)
    if index < len(text) and text[index] == "{":
        return _skip_braced(text, index)
    match = _CONTROL_WORD.match(text, index)
    if match:
        if match.group(1) == "csname":
            end = text.find("\\endcsname", match.end())
            return len(text) if end < 0 else end + len("\\endcsname")
        return match.end()
    return index + 1 if index < len(text) else index


def _skip_conditional_test(text: str, index: int, name: str) -> int:
    """Skip the test tokens of a conditional so they do not count as content."""
    if name not in _CONDITIONAL_TEST_TOKENS:
        return index
    if name == "ifcsname":
        end = text.find("\\endcsname", index)
        return len(text) if end < 0 else end + len("\\endcsname")
    if name in {"ifx", "ifcat"}:
        return _one_token(text, _one_token(text, index))
    if name in {"ifnum", "ifdim"}:
        position = _one_token(text, index)
        position = _skip_whitespace(text, position)
        while position < len(text) and text[position] in "<=>":
            position += 1
        return _one_token(text, position)
    return _one_token(text, index)


def _conditional_has_content(text: str) -> bool:
    """Say whether a conditional region contains anything visible.

    Layout commands with their arguments, formatting switches, declarations and
    comments are not content. Math, text, arguments of a text command, Unicode
    and any unknown command are content, so an unrecognised construct cannot
    silently count as a typesetting-only branch.
    """
    index = 0
    while index < len(text):
        char = text[index]
        if char == "%":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
            continue
        if char == "\\":
            match = _CONTROL_WORD.match(text, index)
            if not match:
                if text[index + 1:index + 2] in _SPACING_SYMBOLS:
                    index += 2
                    continue
                return True
            name = match.group(1)
            after = match.end()
            if name == "let":
                probe = _skip_whitespace(text, after)
                if probe < len(text) and text[probe] == "=":
                    probe = _skip_whitespace(text, probe + 1)
                target = _CONTROL_WORD.match(text, probe)
                index = target.end() if target else probe + 1
                continue
            if name == "newif":
                probe = _skip_whitespace(text, after)
                target = _CONTROL_WORD.match(text, probe)
                index = target.end() if target else probe
                continue
            if name in {"else", "fi", "or"}:
                index = after
                continue
            if _is_conditional(name, text, after, frozenset()):
                index = _skip_conditional_test(text, after, name)
                continue
            if name in _DECLARATIONS:
                index = _skip_definition(text, after, name)
                continue
            if name in _LAYOUT_COMMANDS or name in _FORMATTING_SWITCHES:
                index = _skip_command_arguments(text, after)
                continue
            return True
        if char.isspace() or char in "{}[]":
            index += 1
            continue
        return True
    return False


def _conditional_content_count(text: str, uncertain: list[tuple[int, int]],
                               body_start: int, body_end: int) -> int:
    """Count body conditional regions that contain visible content."""
    count = 0
    for low, high in uncertain:
        low = max(low, body_start)
        high = min(high, body_end)
        if low < high and _conditional_has_content(text[low:high]):
            count += 1
    return count


def _conditional_body_prose(text: str, uncertain: list[tuple[int, int]],
                            body_start: int, body_end: int) -> int:
    """Count body letters inside conditionals whose branch is undecidable."""
    total = 0
    for low, high in uncertain:
        low = max(low, body_start)
        high = min(high, body_end)
        if low < high:
            total += _prose_chars(text[low:high])
    return total


def _coverage(assembly: AssemblyResult, document: dict,
              parser_errors: list[dict], dependencies: list[dict],
              uncovered: int = 0, conditional_body: int = 0,
              conditional_content: int = 0) -> dict:
    coverage = assembly.coverage()
    coverage["content_complete"] = coverage["complete"]
    reasons = set(coverage.get("reasons", []))
    outside_body = sum(1 for item in dependencies
                       if item.get("code") == "include_not_in_entry"
                       and item.get("region", "body") != "preamble")
    if outside_body:
        coverage["content_complete"] = False
        reasons.add("include_outside_entry")
    coverage["outside_entry_dependencies"] = outside_body
    coverage["assembly_complete"] = coverage["content_complete"]
    structure = not parser_errors and bool(document["blocks"])
    if parser_errors:
        reasons.add("parser_errors")
    if not document["blocks"]:
        reasons.add("no_blocks")
    if uncovered:
        structure = False
        reasons.add("uncovered_entry_text")
    conditional = sum(1 for item in assembly.diagnostics
                      if item.get("code") == "directive_in_conditional")
    if conditional:
        structure = False
        reasons.add("conditional_directives")
    unclosed = sum(1 for item in assembly.diagnostics
                   if item.get("code") == "unclosed_conditional")
    if unclosed:
        structure = False
        reasons.add("unclosed_conditional")
    if conditional_body or conditional_content:
        structure = False
        reasons.add("conditional_body")
    coverage["structure_complete"] = structure
    coverage["uncovered_entry_chars"] = uncovered
    coverage["conditional_body_chars"] = conditional_body
    coverage["conditional_content_regions"] = conditional_content
    coverage["conditional_directives"] = conditional
    coverage["parser_errors"] = len(parser_errors)
    coverage["parser_error_codes"] = sorted({item.get("code") for item in parser_errors})
    coverage["missing_dependencies"] = len(dependencies)
    coverage["dependency_error_codes"] = sorted({item.get("code") for item in dependencies})
    coverage["document_complete"] = (
        coverage["content_complete"] and coverage["structure_complete"])
    coverage["complete"] = coverage["document_complete"]
    coverage["reasons"] = sorted(reasons)
    return coverage


def prepare_source(tree: SourceTree, entry: str | None = None, *,
                   recover_parse_errors: bool = True,
                   transparent_containers: bool = True) -> PreparedSource:
    selected = select_entry(tree, entry)
    assembly = assemble_files(tree.files, selected)
    problems = assembly.validate(tree.files)
    if problems:
        raise ValueError(f"assembly source map is invalid: {problems[:1]}")
    coords = EntryCoordinates(assembly)
    with TemporaryDirectory(prefix="prepare-") as temporary:
        materialized = Path(temporary) / "tree"
        tree.materialize(materialized)
        blocks, parser_errors, dependencies = _parse_entry(
            tree, assembly, selected, materialized, coords,
            recover=recover_parse_errors,
            transparent=transparent_containers)
    document = merge_blocks(assembly, blocks, source_tree_hash=tree.digest,
                            files=tree.files)
    parse_text = coords.copy_text()
    _, body_start_parse, end_parse = document_bounds(parse_text)
    body_start_parse = body_start_parse or 0
    body_end_parse = (end_parse if end_parse is not None else len(parse_text))
    inactive_parse, uncertain_parse = condition_regions(parse_text)
    body_bounds = (coords.to_entry(body_start_parse),
                   coords.to_entry(body_end_parse))
    inactive = [(coords.to_entry(low), coords.to_entry(high))
                for low, high in inactive_parse]
    uncovered = _uncovered_entry_prose(
        assembly.text, document["blocks"], inactive, body_bounds)
    conditional_body = _conditional_body_prose(
        parse_text, uncertain_parse, body_start_parse, body_end_parse)
    conditional_content = _conditional_content_count(
        parse_text, uncertain_parse, body_start_parse, body_end_parse)
    coverage = _coverage(assembly, document, parser_errors, dependencies,
                         uncovered, conditional_body, conditional_content)
    body_uncertain = [(coords.to_entry(low), coords.to_entry(high))
                      for low, high in uncertain_parse
                      if low < body_end_parse and high > body_start_parse]
    for block in document["blocks"]:
        start = int(block["entry"]["char_start"])
        end = int(block["entry"]["char_end"])
        block["conditional"] = any(low < end and high > start
                                   for low, high in body_uncertain)
    coverage["conditional_ranges"] = [
        {"entry": {"char_start": low, "char_end": high},
         "source_spans": [{"path": path, "char_start": span_start,
                           "char_end": span_end}
                          for path, span_start, span_end
                          in entry_source_spans(assembly, low, high)]}
        for low, high in body_uncertain]
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
        (directory / name).write_bytes(data)


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
    out.parent.mkdir(parents=True, exist_ok=True)
    previous_manifest = _manifest_digest(out) if out.is_dir() else None
    staging = Path(mkdtemp(dir=out.parent, prefix=f".{out.name}.staging-"))
    journal = {"out": out.name, "staging": staging.name, "backup": None,
               "phase": "staged",
               "new_manifest_sha256":
                   hashlib.sha256(artifacts["manifest.json"]).hexdigest(),
               "previous_manifest_sha256": previous_manifest}
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
    return manifest
