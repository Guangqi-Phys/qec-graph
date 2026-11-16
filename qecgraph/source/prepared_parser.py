"""Downstream structural parsing of a prepared, source-bound input.

This layer owns document blocks, source coordinates and completeness checks.
It does not call models or normalize source formats.
"""
from __future__ import annotations
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Mapping
from .assembly import (
    LITERAL_ENVIRONMENTS, AssemblyResult, _DECLARATIONS, _is_conditional,
    _skip_definition, EntryCoordinates, SourceLineIndex, condition_regions,
    document_bounds, entry_source_spans, merge_blocks,
)
from .package import SourceTree
from .parser import parse_project
from .prepare import PreparedInput, PreparedSource

_DEPENDENCY_CODES = frozenset({
    "missing_include", "missing_resource", "unsupported_include_type",
    "path_outside_project",
})

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
        diag_start = source.get("char_start")
        diag_end = source.get("char_end")
        if not isinstance(diag_start, int) or not isinstance(diag_end, int):
            continue
        if diag_start < shift:
            continue
        diagnostic = dict(diagnostic)
        diagnostic["source"] = {
            **source, "char_start": diag_start - shift + parse_offset,
            "char_end": max(diag_start, diag_end) - shift + parse_offset}
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
        # The opening document environment is in the shared preamble. Close it
        # in each temporary parse view; otherwise every healthy chunk reports
        # a synthetic missing-end error.
        chunk = (preamble + text[low:high] + "\n\\end{document}\n").encode("utf-8")
        parsed = _run_parse(path, root, chunk, recover=recover,
                            transparent=transparent)
        chunk_blocks, chunk_diagnostics = _shift_parsed(
            parsed, name, shift, f"part{index}", low)
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
        str((block.get("source") or {}).get("path"))
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
        if source:
            item['source'] = source
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
                        closing_token = "\\end{" + environment + "}"
                        end = text.find(closing_token, probe)
                        index = len(text) if end < 0 else end + len(closing_token)
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
            if name in _LAYOUT_COMMANDS:
                index = _skip_command_arguments(text, after)
                continue
            if name in _FORMATTING_SWITCHES:
                index = after
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


def parse_prepared(prepared: PreparedInput, tree: SourceTree, *,
                   recover_parse_errors: bool = True,
                   transparent_containers: bool = True) -> PreparedSource:
    """Downstream structural extraction; preparation itself does not classify blocks."""
    if prepared.source_tree_hash != tree.digest or prepared.assembly.validate(tree.files):
        raise ValueError('Prepared input does not match the source tree')
    selected, assembly = prepared.entry, prepared.assembly
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


