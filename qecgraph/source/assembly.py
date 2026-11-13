"""Byte-faithful assembly of LaTeX source trees with an exact source map.

The assembler copies original bytes only. It resolves literal
``\\input``/``\\include``/``\\subfile``/``\\import``/``\\subimport`` directives,
replaces the directive in place with the target bytes, and records where every
output byte came from. It never expands macros, rewrites text, or executes TeX.
Unresolved directives stay in the entry and are reported.

The module accepts a mapping of POSIX relative paths to bytes (normally
``SourceTree.files``) so assembly can be tested without touching the filesystem.
Per-file parser blocks are merged into an entry-ordered document model by
``merge_blocks``; the caller is responsible for parsing each origin file with
the same source tree.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Mapping

from .reading import reading_projection

ONE_ARG = frozenset({"input", "include", "subfile"})
TWO_ARG = frozenset({
    "import", "subimport", "includefrom", "inputfrom",
    "subincludefrom", "subinputfrom",
})
DIRECTIVES = ONE_ARG | TWO_ARG
_LITERAL_ENVIRONMENTS = frozenset({
    "verbatim", "verbatim*", "Verbatim", "BVerbatim", "LVerbatim",
    "lstlisting", "minted", "comment", "filecontents", "filecontents*",
})
_DECLARATIONS = frozenset({
    "def", "gdef", "edef", "xdef", "newcommand", "renewcommand",
    "providecommand", "DeclareRobustCommand", "newenvironment",
    "renewenvironment", "DeclareMathOperator", "let", "futurelet",
})
_CONTROL = re.compile(r"\\([A-Za-z@]+)\*?")
_LITERAL_MACRO = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{\s*\\([A-Za-z@]+)\s*\}"
    r"\s*\{\s*([^{}\\\r\n]*?)\s*\}"
    r"|\\(?:def|gdef|edef|xdef)\s*\\([A-Za-z@]+)\s*\{\s*([^{}\\\r\n]*?)\s*\}")
_SECTION = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)"
                      r"\s*(\*)?")
_SECTION_NAMES = {-1: "part", 0: "chapter", 1: "section", 2: "subsection",
                  3: "subsubsection", 4: "paragraph", 5: "subparagraph"}


@dataclass(frozen=True)
class Segment:
    """One contiguous original-byte slice copied into the assembled entry."""

    path: str
    byte_start: int
    byte_end: int
    char_start: int
    char_end: int
    out_byte_start: int
    out_byte_end: int
    out_char_start: int
    out_char_end: int
    kind: str = "original"

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "out_byte_start": self.out_byte_start,
            "out_byte_end": self.out_byte_end,
            "out_char_start": self.out_char_start,
            "out_char_end": self.out_char_end,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class DirectiveEvent:
    """One include-like directive and its disposition."""

    kind: str
    path: str
    line: int
    literal: tuple[str, ...]
    source_byte_start: int
    source_byte_end: int
    source_char_start: int
    source_char_end: int
    outcome: str
    region: str = "body"
    target: str | None = None
    target_byte_start: int | None = None
    target_byte_end: int | None = None
    target_char_start: int | None = None
    target_char_end: int | None = None
    out_byte_start: int | None = None
    out_byte_end: int | None = None
    out_char_start: int | None = None
    out_char_end: int | None = None
    stripped_document: bool = False
    preamble_dropped: bool = False
    expanded_args: tuple[str, ...] | None = None
    depth: int = 0

    def to_dict(self) -> dict:
        return {key: value for key, value in self.__dict__.items()}


@dataclass
class AssemblyResult:
    entry: str
    data: bytes
    segments: list[Segment] = field(default_factory=list)
    events: list[DirectiveEvent] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.data.decode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def source_map(self) -> dict:
        return {
            "schema": "qecgraph.source_map/1",
            "entry": self.entry,
            "entry_sha256": self.sha256,
            "segments": [segment.to_dict() for segment in self.segments],
            "directives": [event.to_dict() for event in self.events],
        }

    def coverage(self) -> dict:
        counts: dict[str, int] = {}
        kinds: dict[str, int] = {}
        for event in self.events:
            counts[event.outcome] = counts.get(event.outcome, 0) + 1
            kinds[event.kind] = kinds.get(event.kind, 0) + 1
        body_unresolved = sum(1 for event in self.events
                              if event.outcome != "resolved" and event.region == "body")
        preamble_missing = sum(1 for event in self.events
                               if event.outcome != "resolved" and event.region == "preamble")
        preamble_dropped = sum(1 for event in self.events if event.preamble_dropped)
        complete = body_unresolved == 0
        reasons = []
        if body_unresolved:
            reasons.append("unresolved_directives")
        return {
            "complete": complete,
            "reasons": reasons,
            "directives": len(self.events),
            "outcomes": counts,
            "kinds": kinds,
            "origin_files": sorted({segment.path for segment in self.segments}),
            "bytes": len(self.data),
            "segments": len(self.segments),
            "preamble_dropped": preamble_dropped,
            "preamble_missing": preamble_missing,
        }

    def validate(self, files: Mapping[str, bytes]) -> list[dict]:
        """Return source-map violations; an empty list means exact coverage."""
        problems: list[dict] = []
        cursor = 0
        char_cursor = 0
        for segment in self.segments:
            if segment.out_byte_start != cursor or segment.out_char_start != char_cursor:
                problems.append({"code": "segment_gap", "path": segment.path,
                                 "out_byte_start": segment.out_byte_start})
            if (segment.out_byte_end - segment.out_byte_start
                    != segment.byte_end - segment.byte_start):
                problems.append({"code": "segment_length", "path": segment.path})
            if (segment.out_char_end - segment.out_char_start
                    != segment.char_end - segment.char_start):
                problems.append({"code": "segment_char_length", "path": segment.path})
            source = files.get(segment.path)
            if source is None:
                problems.append({"code": "segment_missing_source", "path": segment.path})
            else:
                expected = source[segment.byte_start:segment.byte_end]
                actual = self.data[segment.out_byte_start:segment.out_byte_end]
                if expected != actual:
                    problems.append({"code": "segment_mismatch", "path": segment.path})
            cursor = segment.out_byte_end
            char_cursor = segment.out_char_end
        if cursor != len(self.data):
            problems.append({"code": "entry_tail", "cursor": cursor, "bytes": len(self.data)})
        if char_cursor != len(self.text):
            problems.append({"code": "entry_char_tail", "cursor": char_cursor,
                             "chars": len(self.text)})
        return problems


def _mask_comments(text: str) -> str:
    out = list(text)
    i = 0
    while i < len(text):
        if text[i] == "%" and (i == 0 or text[i - 1] != "\\"):
            end = text.find("\n", i)
            if end < 0:
                end = len(text)
            for position in range(i, end):
                out[position] = " "
            i = end
        else:
            i += 1
    return "".join(out)


def _read_group(text: str, index: int) -> tuple[str, int]:
    if index >= len(text) or text[index] != "{":
        return "", index
    depth = 0
    position = index
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[index + 1:position], position + 1
        position += 1
    return text[index + 1:], len(text)


def _skip_bracket(text: str, index: int) -> tuple[str, int]:
    if index >= len(text) or text[index] != "[":
        return "", index
    depth = 0
    position = index
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[index + 1:position], position + 1
        position += 1
    return text[index + 1:], len(text)


def _skip_space(text: str, index: int) -> int:
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text[index] == "%":
            end = text.find("\n", index)
            index = len(text) if end < 0 else end + 1
        else:
            break
    return index


def _skip_definition(text: str, index: int, name: str) -> int:
    if name in {"def", "gdef", "edef", "xdef"}:
        index = _skip_space(text, index)
        if index < len(text) and text[index] == "\\":
            match = _CONTROL.match(text, index)
            index = match.end() if match else index + 1
        else:
            index += 1
        while index < len(text) and text[index] != "{":
            index += 2 if text[index] == "\\" else 1
        if index < len(text):
            _, index = _read_group(text, index)
        return index
    if name in {"newcommand", "renewcommand", "providecommand", "DeclareRobustCommand"}:
        index = _skip_space(text, index)
        if index < len(text) and text[index] == "*":
            index += 1
        index = _skip_space(text, index)
        if index < len(text) and text[index] == "{":
            _, index = _read_group(text, index)
        for _ in range(2):
            index = _skip_space(text, index)
            if index < len(text) and text[index] == "[":
                _, index = _skip_bracket(text, index)
            else:
                break
        index = _skip_space(text, index)
        if index < len(text) and text[index] == "{":
            _, index = _read_group(text, index)
        return index
    if name in {"newenvironment", "renewenvironment"}:
        index = _skip_space(text, index)
        if index < len(text) and text[index] == "{":
            _, index = _read_group(text, index)
        for _ in range(2):
            index = _skip_space(text, index)
            if index < len(text) and text[index] == "[":
                _, index = _skip_bracket(text, index)
            else:
                break
        for _ in range(2):
            index = _skip_space(text, index)
            if index < len(text) and text[index] == "{":
                _, index = _read_group(text, index)
        return index
    if name == "DeclareMathOperator":
        index = _skip_space(text, index)
        if index < len(text) and text[index] == "*":
            index += 1
        for _ in range(2):
            index = _skip_space(text, index)
            if index < len(text) and text[index] == "{":
                _, index = _read_group(text, index)
        return index
    return index


def _skip_iffalse(text: str, index: int) -> int:
    depth = 1
    while index < len(text):
        if text[index] == "%":
            end = text.find("\n", index)
            index = len(text) if end < 0 else end + 1
            continue
        if text[index] != "\\":
            index += 1
            continue
        match = _CONTROL.match(text, index)
        if not match:
            index += 2
            continue
        name = match.group(1)
        index = match.end()
        if name.startswith("if") and name != "ifthenelse":
            depth += 1
        elif name == "fi":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


@dataclass(frozen=True)
class _Directive:
    name: str
    start: int
    end: int
    args: tuple[str, ...]
    line: int


def _parse_args(text: str, index: int, name: str) -> tuple[tuple[str, ...], int]:
    index = _skip_space(text, index)
    if index < len(text) and text[index] == "*":
        index = _skip_space(text, index + 1)
    count = 1 if name in ONE_ARG else 2
    arguments: list[str] = []
    for _ in range(count):
        index = _skip_space(text, index)
        if index < len(text) and text[index] == "[":
            _, index = _skip_bracket(text, index)
            index = _skip_space(text, index)
        if index < len(text) and text[index] == "{":
            value, index = _read_group(text, index)
        elif index < len(text) and text[index] not in "}\n\r":
            end = index
            while end < len(text) and not text[end].isspace() and text[end] not in "%\\}":
                end += 1
            value, index = text[index:end], end
        else:
            break
        arguments.append(value)
    return tuple(arguments), index


def _scan(text: str) -> tuple[list[_Directive], list[dict]]:
    directives: list[_Directive] = []
    diagnostics: list[dict] = []
    index = 0
    conditionals = 0
    while index < len(text):
        char = text[index]
        if char == "%":
            end = text.find("\n", index)
            index = len(text) if end < 0 else end + 1
            continue
        if char != "\\":
            index += 1
            continue
        match = _CONTROL.match(text, index)
        if not match:
            index += 2
            continue
        name = match.group(1)
        after = match.end()
        if name in {"verb", "verb*", "lstinline"}:
            if after < len(text):
                delimiter = text[after]
                end = text.find(delimiter, after + 1)
                index = len(text) if end < 0 else end + 1
            else:
                index = after
            continue
        if name == "begin":
            environment, after = _parse_group(text, after)
            if environment in _LITERAL_ENVIRONMENTS:
                end = text.find("\\end{" + environment + "}", after)
                index = len(text) if end < 0 else end + len("\\end{" + environment + "}")
                continue
            index = after
            continue
        if name == "iffalse":
            index = _skip_iffalse(text, after)
            diagnostics.append({"code": "iffalse_skipped"})
            continue
        if name == "endinput":
            diagnostics.append({"code": "endinput"})
            break
        if name.startswith("if"):
            conditionals += 1
        if name in _DECLARATIONS:
            index = _skip_definition(text, after, name)
            continue
        if name in DIRECTIVES:
            arguments, after_args = _parse_args(text, after, name)
            if len(arguments) == (1 if name in ONE_ARG else 2):
                directives.append(_Directive(name, index, after_args, arguments,
                                             text.count("\n", 0, index) + 1))
            else:
                diagnostics.append({"code": "unparsed_directive", "name": name})
            index = after_args
            continue
        index = after
    if conditionals:
        diagnostics.append({"code": "conditionals_present", "count": conditionals})
    return directives, diagnostics


def _parse_group(text: str, index: int) -> tuple[str, int]:
    index = _skip_space(text, index)
    if index < len(text) and text[index] == "{":
        return _read_group(text, index)
    return "", index


def _document_bounds(text: str) -> tuple[int | None, int | None, int | None]:
    """Locate ``\\begin{document}``/``\\end{document}`` outside literal content.

    Returns ``(begin_start, body_start, end_start)`` as character offsets.
    ``body_start`` is the offset just after ``\\begin{document}`` and
    ``end_start`` the offset of the first real ``\\end{document}``; both are
    ``None`` when the document markers are absent or unmatched. Comments,
    ``\\verb``-like constructs and literal environments are skipped, so an
    ``\\end{document}`` shown inside ``verbatim`` does not end the body.
    """
    index = 0
    begin_start: int | None = None
    body_start: int | None = None
    while index < len(text):
        char = text[index]
        if char == "%":
            end = text.find("\n", index)
            index = len(text) if end < 0 else end + 1
            continue
        if char != "\\":
            index += 1
            continue
        match = _CONTROL.match(text, index)
        if not match:
            index += 2
            continue
        name = match.group(1)
        after = match.end()
        if name in {"verb", "verb*", "lstinline"}:
            if after < len(text):
                delimiter = text[after]
                end = text.find(delimiter, after + 1)
                index = len(text) if end < 0 else end + 1
            else:
                index = after
            continue
        if name in {"begin", "end"}:
            environment, group_end = _parse_group(text, after)
            environment = environment.strip()
            if name == "begin" and environment in _LITERAL_ENVIRONMENTS:
                end = text.find("\\end{" + environment + "}", group_end)
                index = (len(text) if end < 0
                         else end + len("\\end{" + environment + "}"))
                continue
            if name == "begin" and environment == "document" and begin_start is None:
                begin_start, body_start = index, group_end
                index = group_end
                continue
            if name == "end" and environment == "document" and begin_start is not None:
                return begin_start, body_start, index
            index = group_end
            continue
        index = after
    return begin_start, body_start, None


def _document_body(raw: bytes) -> tuple[int, int, bool, bool]:
    """Return body byte range, has-document flag, and preamble-dropped flag."""
    text = raw.decode("utf-8")
    begin_start, body_start, end_start = _document_bounds(text)
    if begin_start is None or body_start is None:
        return 0, len(raw), False, False
    char_end = end_start if end_start is not None else len(text)
    char_end = max(body_start, char_end)
    byte_start = len(text[:body_start].encode("utf-8"))
    byte_end = len(text[:char_end].encode("utf-8"))
    preamble = _mask_comments(text[:begin_start])
    preamble = re.sub(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", "", preamble)
    dropped = bool(re.sub(r"\s", "", preamble))
    return byte_start, byte_end, True, dropped


def _safe_literal(value: str) -> str | None:
    value = value.strip()
    if not value or value.startswith("/") or "\\" in value or "\x00" in value:
        return None
    parts = [part for part in value.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _escapes_tree(value: str) -> bool:
    value = value.strip()
    if value.startswith("/") or "\x00" in value:
        return True
    return any(part == ".." for part in value.split("/"))


def _with_suffix(value: str) -> list[str]:
    suffix = value.rsplit("/", 1)[-1].rsplit(".", 1)
    if len(suffix) == 2 and suffix[1]:
        return [value]
    return [value, value + ".tex"]


class Assembler:
    def __init__(self, files: Mapping[str, bytes]):
        self.files = dict(files)
        self.events: list[DirectiveEvent] = []
        self.diagnostics: list[dict] = []
        self.macros: dict[str, str] = {}

    def assemble(self, entry: str, *, diagnostics: list[dict] | None = None) -> AssemblyResult:
        clean_entry = _safe_literal(entry)
        if clean_entry is None or clean_entry not in self.files:
            raise ValueError(f"entry is not a regular source file: {entry!r}")
        data, segments, events, local_diagnostics = self._assemble_range(
            clean_entry, 0, len(self.files[clean_entry]), (), whole=True)
        result = AssemblyResult(clean_entry, data, segments, events,
                                [*local_diagnostics, *(diagnostics or [])])
        return result

    def _assemble_range(self, rel: str, base: int, end: int,
                        stack: tuple[str, ...], *, whole: bool
                        ) -> tuple[bytes, list[Segment], list[DirectiveEvent], list[dict]]:
        raw = self.files[rel]
        try:
            text = raw[base:end].decode("utf-8")
        except UnicodeDecodeError:
            return (raw[base:end],
                    [Segment(rel, base, end, 0, len(raw[:end].decode("utf-8", "replace")),
                             0, end - base, 0, end - base)],
                    [], [{"code": "unsupported_encoding", "path": rel}])
        base_char = len(raw[:base].decode("utf-8"))
        self._learn_literal_macros(text)
        _, body_start, _ = _document_bounds(text)
        preamble_end = body_start
        directives, diagnostics = _scan(text)
        for diagnostic in diagnostics:
            diagnostic["path"] = rel
        output = bytearray()
        segments: list[Segment] = []
        events: list[DirectiveEvent] = []
        out_chars = 0

        def add_original(start: int, stop: int) -> None:
            nonlocal out_chars
            if stop <= start:
                return
            byte_start = base + len(text[:start].encode("utf-8"))
            byte_stop = base + len(text[:stop].encode("utf-8"))
            chunk = raw[byte_start:byte_stop]
            segments.append(Segment(
                rel, byte_start, byte_stop, base_char + start, base_char + stop,
                len(output), len(output) + len(chunk), out_chars, out_chars + stop - start))
            output.extend(chunk)
            out_chars += stop - start

        cursor = 0
        for directive in directives:
            start = directive.start
            stop = directive.end
            if start < cursor:
                continue
            add_original(cursor, start)
            source_byte_start = base + len(text[:start].encode("utf-8"))
            source_byte_end = base + len(text[:stop].encode("utf-8"))
            event = DirectiveEvent(
                kind=directive.name, path=rel, line=directive.line,
                literal=directive.args,
                source_byte_start=source_byte_start,
                source_byte_end=source_byte_end,
                source_char_start=base_char + start,
                source_char_end=base_char + stop,
                outcome="unresolved",
                region="preamble" if preamble_end is not None and start < preamble_end else "body",
                out_byte_start=len(output), out_char_start=out_chars,
            )
            expanded_args = tuple(self._expand_literal(argument)
                                  for argument in directive.args)
            if expanded_args != directive.args:
                event = _replace(event, expanded_args=expanded_args)
            resolution = self._resolve(rel, directive, expanded_args)
            if resolution is None:
                add_original(start, stop)
                event = _replace(event, outcome="dynamic_path",
                                 out_byte_end=len(output), out_char_end=out_chars)
                events.append(event)
                cursor = stop
                continue
            target, target_range, stripped, preamble_dropped, outcome, candidates = resolution
            if outcome != "resolved":
                add_original(start, stop)
                event = _replace(event, outcome=outcome, out_byte_end=len(output),
                                 out_char_end=out_chars)
                events.append(event)
                cursor = stop
                continue
            if target in stack or target == rel:
                add_original(start, stop)
                event = _replace(event, outcome="cycle", out_byte_end=len(output),
                                 out_char_end=out_chars)
                events.append(event)
                cursor = stop
                continue
            target_base, target_end = target_range
            child_data, child_segments, child_events, child_diagnostics = self._assemble_range(
                target, target_base, target_end, stack + (rel,), whole=stripped is False)
            offset_bytes = len(output)
            offset_chars = out_chars
            for segment in child_segments:
                segments.append(_shift_segment(segment, offset_bytes, offset_chars))
            for child_event in child_events:
                events.append(_shift_event(child_event, offset_bytes, offset_chars))
            output.extend(child_data)
            out_chars += len(child_data.decode("utf-8"))
            diagnostics.extend(child_diagnostics)
            event = _replace(
                event, outcome="resolved", target=target,
                target_byte_start=target_base, target_byte_end=target_end,
                target_char_start=len(self.files[target][:target_base].decode("utf-8")),
                target_char_end=len(self.files[target][:target_end].decode("utf-8")),
                out_byte_end=len(output), out_char_end=out_chars,
                stripped_document=stripped, preamble_dropped=preamble_dropped,
            )
            events.append(event)
            cursor = stop
        add_original(cursor, len(text))
        return bytes(output), segments, events, diagnostics

    def _resolve(self, rel: str, directive: _Directive, args: tuple[str, ...]
                 ) -> tuple[str, tuple[int, int], bool, bool, str, list[str] | None] | None:
        name = directive.name
        if any(not argument or any(char in argument for char in "\\#{}$%")
               for argument in args):
            return None
        if any(_escapes_tree(argument) for argument in args):
            return ("", (0, 0), False, False, "outside_root", None)
        current = rel.rsplit("/", 1)[0] if "/" in rel else ""
        candidates: list[str] = []
        if name in ONE_ARG:
            literal = _safe_literal(args[0])
            if literal is None:
                return None
            bases = [""] if name == "subfile" else ["", current]
            for base in bases:
                joined = self._join(base, literal)
                for candidate in _with_suffix(joined):
                    if candidate not in candidates:
                        candidates.append(candidate)
        else:
            directory = _safe_literal(args[0])
            filename = _safe_literal(args[1])
            if directory is None or filename is None:
                return None
            roots = ([current, ""] if name in {"subimport", "subincludefrom", "subinputfrom"}
                     else ["", current])
            for root in roots:
                joined = self._join(root, self._join(directory, filename))
                for candidate in _with_suffix(joined):
                    if candidate not in candidates:
                        candidates.append(candidate)
        unique: list[str] = []
        for candidate in candidates:
            normalized = _safe_literal(candidate)
            if normalized is None:
                return ("", (0, 0), False, False, "outside_root", None)
            if normalized not in unique:
                unique.append(normalized)
        existing = [candidate for candidate in unique if candidate in self.files]
        if not existing:
            return ("", (0, 0), False, False, "missing", None)
        chosen = existing[0]
        raw = self.files[chosen]
        body_start, body_end, has_document, preamble_dropped = _document_body(raw)
        strip_body = name == "subfile" or (
            has_document and name in {"import", "subimport", "input", "include"})
        if strip_body and has_document:
            target_range = (body_start, body_end)
            stripped = True
        else:
            target_range = (0, len(raw))
            stripped = False
            preamble_dropped = False
        return (chosen, target_range, stripped, preamble_dropped, "resolved",
                existing[1:] or None)

    def _learn_literal_macros(self, text: str) -> None:
        masked = _mask_comments(text)
        for match in _LITERAL_MACRO.finditer(masked):
            name = match.group(1) or match.group(3)
            value = match.group(2) if match.group(2) is not None else match.group(4)
            if name and value and value.strip():
                self.macros[name] = value.strip()

    def _expand_literal(self, value: str) -> str:
        def replace(match: re.Match) -> str:
            name = match.group(1)
            return self.macros.get(name, match.group(0))
        return re.sub(r"\\([A-Za-z@]+)", replace, value)

    @staticmethod
    def _join(base: str, value: str) -> str:
        return f"{base}/{value}" if base else value


def _replace(event: DirectiveEvent, **fields) -> DirectiveEvent:
    data = event.__dict__.copy()
    data.update(fields)
    return DirectiveEvent(**data)


def _shift_segment(segment: Segment, byte_offset: int, char_offset: int) -> Segment:
    return Segment(
        segment.path, segment.byte_start, segment.byte_end,
        segment.char_start, segment.char_end,
        segment.out_byte_start + byte_offset, segment.out_byte_end + byte_offset,
        segment.out_char_start + char_offset, segment.out_char_end + char_offset,
        segment.kind)


def _shift_event(event: DirectiveEvent, byte_offset: int, char_offset: int) -> DirectiveEvent:
    fields = {}
    for key in ("out_byte_start", "out_byte_end"):
        value = getattr(event, key)
        if value is not None:
            fields[key] = value + byte_offset
    for key in ("out_char_start", "out_char_end"):
        value = getattr(event, key)
        if value is not None:
            fields[key] = value + char_offset
    fields["depth"] = event.depth + 1
    return _replace(event, **fields)


def assemble_files(files: Mapping[str, bytes], entry: str) -> AssemblyResult:
    return Assembler(files).assemble(entry)


def _section_metadata(latex: str, raw_level: int | None) -> tuple[str, bool]:
    match = _SECTION.match(latex.lstrip())
    if match:
        return match.group(1), not bool(match.group(2))
    return _SECTION_NAMES.get(raw_level if raw_level is not None else 1, "section"), True


def _plain(value: str, *, kind: str = "paragraph") -> str:
    projected, citations = reading_projection(value, kind=kind)
    if not citations:
        return projected.strip()
    marked = value
    for start, end, _macro, keys in reversed(citations):
        marked = marked[:start] + "[" + ",".join(keys) + "]" + marked[end:]
    return reading_projection(marked, kind=kind)[0].strip()


def _block_text(value: str, kind: str | None, environment: str | None) -> str:
    if kind == "equation":
        return value.strip()
    if environment:
        opening = re.compile(r"\s*\\begin\{" + re.escape(environment)
                             + r"\}(?:\[[^\]]*\])?(?:\{[^{}]*\})?", re.S)
        value = opening.sub("", value, count=1)
        end = value.rfind("\\end{" + environment + "}")
        if end >= 0:
            value = value[:end]
    return _plain(value)


def merge_blocks(result: AssemblyResult, blocks_by_file: Mapping[str, list[dict]],
                 *, source_tree_hash: str) -> dict:
    """Merge per-file parser blocks into an entry-ordered document model.

    The model preserves the parser's block hierarchy and adds a separate
    document-level section tree. Section levels are normalized per entry:
    the highest sectioning level present becomes 1. Blocks carry plain reading
    text plus exact source and entry spans.
    """
    entry_text = result.text
    char_to_byte = [0] * (len(entry_text) + 1)
    byte_cursor = 0
    for index, char in enumerate(entry_text):
        char_to_byte[index] = byte_cursor
        byte_cursor += len(char.encode("utf-8"))
    char_to_byte[len(entry_text)] = byte_cursor

    segments = result.segments
    by_path: dict[str, list[Segment]] = {}
    for segment in segments:
        by_path.setdefault(segment.path, []).append(segment)
    for values in by_path.values():
        values.sort(key=lambda item: item.char_start)

    def map_position(path: str, position: int) -> int | None:
        for segment in by_path.get(path, []):
            if segment.char_start <= position < segment.char_end:
                return segment.out_char_start + (position - segment.char_start)
            if position == segment.char_end:
                return segment.out_char_end
        return None

    replaced: dict[str, list[tuple[int, int]]] = {}
    for event in result.events:
        if event.outcome != "resolved" or event.target is None:
            continue
        replaced.setdefault(event.path, []).append(
            (event.source_char_start, event.source_char_end))
    for ranges in replaced.values():
        ranges.sort()

    def block_record(path: str, block: dict, start: int, end: int, *,
                     text: str, source_start: int | None = None,
                     source_end: int | None = None) -> dict | None:
        entry_start = map_position(path, start)
        entry_end = map_position(path, max(start, end - 1))
        if entry_start is None or entry_end is None:
            return None
        entry_end += 1
        source = block.get("source") or {}
        kind = block.get("kind")
        raw_level = block.get("section_level")
        command, numbered = _section_metadata(text, raw_level) if kind == "section" else (None, None)
        title_tex = block.get("title_tex", "")
        title_text = _plain(title_tex) if kind == "section" else ""
        body_text = _block_text(text, kind, block.get("environment"))
        if kind in {"paragraph", "unknown"} and not body_text:
            return None
        return {
            "kind": kind,
            "environment": block.get("environment"),
            "level": None,
            "source_level": raw_level,
            "command": command,
            "numbered": numbered,
            "appendix": False,
            "title": title_text,
            "title_tex": title_tex,
            "text": body_text,
            "labels": list(block.get("labels") or []),
            "references": list(block.get("references") or []),
            "source": {
                "path": path,
                "char_start": start if source_start is None else source_start,
                "char_end": end if source_end is None else source_end,
                "line_start": source.get("line_start"),
                "line_end": source.get("line_end"),
            },
            "entry": {
                "char_start": entry_start,
                "char_end": entry_end,
                "byte_start": char_to_byte[entry_start],
                "byte_end": char_to_byte[entry_end],
            },
            "origin_block_key": block.get("key"),
            "origin_parent_key": block.get("parent_key"),
            "spans_include": False,
        }

    merged: list[dict] = []
    for path in sorted(blocks_by_file):
        for block in blocks_by_file[path]:
            source = block.get("source") or {}
            if source.get("path") != path:
                continue
            start = int(source.get("char_start", 0))
            end = int(source.get("char_end", 0))
            if end <= start:
                continue
            block_text = block.get("latex", "")
            cuts = [span for span in replaced.get(path, [])
                    if span[0] < end and span[1] > start]
            if not cuts or block.get("kind") not in {"paragraph", "unknown"}:
                record = block_record(path, block, start, end, text=block_text)
                if record is not None:
                    record["spans_include"] = bool(cuts)
                    merged.append(record)
                continue
            cursor = start
            for cut_start, cut_end in cuts:
                left = max(cursor, start)
                right = min(cut_start, end)
                if right > left:
                    offset = left - start
                    length = right - left
                    piece = block_text[offset:offset + length]
                    if piece.strip():
                        record = block_record(path, block, left, right, text=piece)
                        if record is not None:
                            merged.append(record)
                cursor = max(cursor, min(cut_end, end))
            if cursor < end:
                piece = block_text[cursor - start:]
                if piece.strip():
                    record = block_record(path, block, cursor, end, text=piece)
                    if record is not None:
                        merged.append(record)
    merged.sort(key=lambda item: item["entry"]["char_start"])
    for index, block in enumerate(merged, start=1):
        block["order"] = index
        block["key"] = f"block-{index}"

    origin_map: dict[tuple[str, object], str] = {
        (block["source"]["path"], block.get("origin_block_key")): block["key"]
        for block in merged if block.get("origin_block_key")}
    section_blocks = [block for block in merged if block["kind"] == "section"]
    raw_levels = [int(block["source_level"]) for block in section_blocks
                  if isinstance(block.get("source_level"), int)]
    min_level = min(raw_levels) if raw_levels else 1
    section_ids: dict[str, str] = {}
    for index, block in enumerate(section_blocks, start=1):
        section_ids[block["key"]] = f"s{index}"

    appendix_match = re.search(r"\\appendix\b", _mask_comments(entry_text))
    appendix_at = appendix_match.start() if appendix_match else -1

    sections: list[dict] = []
    stack: list[tuple[int, str]] = []
    for block in merged:
        if block["kind"] != "section":
            continue
        raw_level = block.get("source_level")
        raw_level = raw_level if isinstance(raw_level, int) else min_level
        level = raw_level - min_level + 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        section_id = section_ids[block["key"]]
        parent_id = stack[-1][1] if stack else None
        stack.append((level, section_id))
        block["level"] = level
        block["command"] = block.get("command") or _SECTION_NAMES.get(raw_level, "section")
        block["numbered"] = bool(block.get("numbered", True))
        block["appendix"] = appendix_at >= 0 and block["entry"]["char_start"] > appendix_at
        block["section_id"] = section_id
        sections.append({
            "id": section_id,
            "parent_id": parent_id,
            "level": level,
            "source_level": raw_level,
            "command": block["command"],
            "numbered": block["numbered"],
            "appendix": block["appendix"],
            "title": block["title"],
            "title_tex": block["title_tex"],
            "source": block["source"],
            "entry": block["entry"],
            "block_ids": [block["key"]],
        })

    section_by_id = {section["id"]: section for section in sections}
    section_block_keys = {section_id: block_key
                          for block_key, section_id in section_ids.items()}
    section_stack: list[str] = []
    for block in merged:
        block["document_id"] = "d1"
        if block["kind"] == "section":
            while (section_stack
                   and section_by_id[section_stack[-1]]["level"] >= block["level"]):
                section_stack.pop()
            section_stack.append(block["section_id"])
            continue
        origin_parent = origin_map.get((block["source"]["path"],
                                        block.get("origin_parent_key")))
        block["parent_key"] = origin_parent or (
            section_block_keys.get(section_stack[-1]) if section_stack else None)
        block["section_id"] = section_stack[-1] if section_stack else None
        if section_stack:
            section_by_id[section_stack[-1]]["block_ids"].append(block["key"])

    counts: dict[str, int] = {}
    for block in merged:
        counts[block["kind"]] = counts.get(block["kind"], 0) + 1
    document_id = hashlib.sha256(
        (source_tree_hash + "\0" + result.entry).encode("utf-8")).hexdigest()
    return {
        "schema": "qecgraph.document/2",
        "document_id": document_id,
        "entry": result.entry,
        "source_tree_hash": source_tree_hash,
        "text_projection": "reading-v1",
        "documents": [{"id": "d1", "document_id": document_id,
                       "role": "main", "root": result.entry}],
        "sections": sections,
        "blocks": merged,
        "counts": counts,
        "coverage": result.coverage(),
        "diagnostics": result.diagnostics,
    }
