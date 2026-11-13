"""Byte-faithful assembly of LaTeX source trees with an exact source map.

The assembler copies original bytes only. It resolves literal
``\\input``/``\\include``/``\\subfile``/``\\import``/``\\subimport`` directives,
replaces the directive in place with the target bytes, and records where every
output byte came from. It never expands macros, rewrites text, or executes TeX.
Unresolved directives stay in the entry and are reported.

The module accepts a mapping of POSIX relative paths to bytes (normally
``SourceTree.files``) so assembly can be tested without touching the filesystem.
``merge_blocks`` turns one parse of the assembled entry into an entry-ordered
document model and projects each block back onto the original source files
through the source map.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import bisect
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
_NOT_CONDITIONALS = frozenset({
    "ifthenelse", "ifboolexpr", "iff", "iftoggle", "ifdef", "ifundef",
    "ifdefmacro", "ifdefparam", "ifdefprotected", "ifdefltxprotect",
    "ifdefstring", "ifdefempty", "ifdefvoid", "ifcsdef", "ifcsundef",
    "ifcsmacro", "ifcsparam", "ifcsprotected", "ifcsltxprotect",
    "ifcsstring", "ifcsvoid", "ifcsempty", "ifstrequal", "ifstrempty",
    "ifblank", "ifnumcomp", "ifnumequal", "ifnumgreater", "ifnumless",
    "ifdimcomp", "ifdimequal", "ifdimgreater", "ifdimless", "ifinlist",
    "ifrmnum", "ifpatchable", "iffieldundef", "ifentrytype",
})


def _is_conditional(name: str, text: str, after: int,
                    defined: frozenset[str] | set[str] = frozenset()) -> bool:
    """Say whether a control word opens a fi-terminated conditional.

    Math and argument-taking macros share the ``if`` prefix (``iff``,
    ``iftoggle{...}{...}``), as do user macros such as ``ifff`` that a
    declaration defines. Known macro names, a following brace argument, and
    learned declarations mark a macro rather than a conditional primitive.
    """
    if name in _NOT_CONDITIONALS or name in defined:
        return False
    probe = after
    while probe < len(text) and text[probe].isspace():
        probe += 1
    if probe < len(text) and text[probe] == "{":
        return False
    return name.startswith("if")


LITERAL_ENVIRONMENTS = frozenset({
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
    r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{?\s*"
    r"\\([A-Za-z@]+)\s*\}?\s*\{\s*([^{}\\\r\n]*?)\s*\}"
    r"|\\(?:def|gdef|edef|xdef)\s*\\([A-Za-z@]+)\s*\{\s*([^{}\\\r\n]*?)\s*\}")
_NEWCOMMAND_NAME = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)\*?\s*"
    r"\{?\s*\\([A-Za-z@]+)\s*\}?")
_DEF_NAME = re.compile(r"\\(?:def|gdef|edef|xdef)\s*\\([A-Za-z@]+)")
_LET_NAME = re.compile(r"\\let\s*\\([A-Za-z@]+)")
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


def _is_control_word_char(char: str) -> bool:
    return ("a" <= char <= "z") or ("A" <= char <= "Z") or char == "@"


def _comment_open(text: str, offset: int) -> bool:
    """Return true when an unescaped ``%`` on the current line precedes offset."""
    start = text.rfind("\n", 0, offset) + 1
    index = start
    while index < offset:
        if text[index] == "%":
            backslashes = 0
            probe = index - 1
            while probe >= start and text[probe] == "\\":
                backslashes += 1
                probe -= 1
            if backslashes % 2 == 0:
                return True
        index += 1
    return False


class EntryCoordinates:
    """Map between the assembled entry and a parse copy with separators.

    Splicing an include can join two tokens that the source kept apart. Joining
    the last letter of a control word to the first letter of included content
    turns ``\\fi`` + ``ACTIVE`` into ``\\fiACTIVE``; a child file that ends in a
    ``%`` comment would swallow the parent text that follows it. The parse copy
    inserts one space or newline at those joints, and coordinates map back to
    the untouched entry, so entry bytes and the source map stay exact.
    """

    def __init__(self, result: AssemblyResult):
        text = result.text
        self.text = text
        self.separators: list[int] = []
        self.separator_text: list[str] = []
        self.parse_separators: list[int] = []
        for segment in result.segments:
            offset = segment.out_char_end
            if not 0 < offset < len(text):
                continue
            if self.separators and self.separators[-1] == offset:
                continue
            separator = self._separator_at(text, offset)
            if separator is None:
                continue
            self.parse_separators.append(offset + len(self.separators))
            self.separators.append(offset)
            self.separator_text.append(separator)

    @staticmethod
    def _separator_at(text: str, offset: int) -> str | None:
        if _comment_open(text, offset) and text[offset] != "\n":
            return "\n"
        if (_is_control_word_char(text[offset - 1])
                and _is_control_word_char(text[offset])):
            return " "
        return None

    def to_parse(self, entry_offset: int) -> int:
        """Return the parse-copy offset of an entry character offset."""
        return entry_offset + bisect.bisect_right(self.separators, entry_offset)

    def to_entry(self, parse_offset: int) -> int:
        """Return the entry character offset of a parse-copy offset."""
        return parse_offset - bisect.bisect_left(self.parse_separators, parse_offset)

    def copy_text(self) -> str:
        if not self.separators:
            return self.text
        parts: list[str] = []
        cursor = 0
        for offset, separator in zip(self.separators, self.separator_text):
            parts.append(self.text[cursor:offset])
            parts.append(separator)
            cursor = offset
        parts.append(self.text[cursor:])
        return "".join(parts)


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
        elif index < len(text) and text[index] == "\\":
            match = _CONTROL.match(text, index)
            index = match.end() if match else index + 1
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


def _conditional_branches(text: str, index: int, kind: str,
                          defined: frozenset[str] | set[str] = frozenset(),
                          stop: int | None = None,
                          ) -> tuple[list[tuple[int, int]], int, int, bool]:
    """Split a conditional body into branch ranges with lexical context.

    ``index`` is the offset just after the opening control word and ``kind``
    its name, so ``ifcase`` splits at ``\\or`` as well as ``\\else``. Comments,
    ``\\verb``-like macros, literal environments, declaration bodies and
    ``\\newif`` declarations are skipped, so a ``\\fi`` shown in one of them does
    not close the conditional. Returns ``(branches, fi_start, fi_end)``; when no
    matching ``\\fi`` exists ``fi_start`` equals the stop offset.
    """
    limit = len(text) if stop is None else stop
    branches: list[tuple[int, int]] = []
    branch_start = index
    has_else = False
    depth = 0
    while index < limit:
        char = text[index]
        if char == "%":
            newline = text.find("\n", index)
            index = limit if newline < 0 else newline + 1
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
            if after < limit:
                delimiter = text[after]
                newline = text.find(delimiter, after + 1, limit)
                index = limit if newline < 0 else newline + 1
            else:
                index = after
            continue
        if name == "begin":
            environment, group_end = _parse_group(text, after)
            if environment in LITERAL_ENVIRONMENTS:
                closing = "\\end{" + environment + "}"
                end = text.find(closing, group_end, limit)
                index = limit if end < 0 else end + len(closing)
                continue
            index = group_end
            continue
        if name == "newif":
            probe = _skip_space(text, after)
            flag = _CONTROL.match(text, probe)
            if flag:
                defined.update({flag.group(1) + "true", flag.group(1) + "false"})
                index = flag.end()
            else:
                index = probe
            continue
        if name in _DECLARATIONS:
            definition = _definition_event(text, index, name)
            if definition is not None:
                defined.add(definition.name)
            index = _skip_definition(text, after, name)
            continue
        if _is_conditional(name, text, after, defined):
            depth += 1
        elif name == "fi":
            if depth == 0:
                branches.append((branch_start, index))
                return branches, index, after, has_else
            depth -= 1
        elif depth == 0 and name == "else":
            branches.append((branch_start, index))
            branch_start = after
            has_else = True
        elif depth == 0 and name == "or" and kind == "ifcase":
            branches.append((branch_start, index))
            branch_start = after
        elif name == "endinput":
            break
        index = after
    branches.append((branch_start, limit))
    return branches, limit, limit, has_else


def _conditional_bounds(text: str, index: int,
                        defined: frozenset[str] | set[str] = frozenset(),
                        stop: int | None = None,
                        ) -> tuple[int | None, int, int]:
    """Return ``(else_start, fi_start, fi_end)`` for a conditional body.

    ``index`` is the offset just after the opening ``\\if...`` control word.
    ``else_start`` is the offset just after the first matching branch separator
    or None; without a matching ``\\fi`` the scan stops at ``stop``.
    """
    branches, fi_start, fi_end, has_else = _conditional_branches(
        text, index, "", defined, stop)
    else_start = branches[1][0] if has_else else None
    return else_start, fi_start, fi_end


@dataclass(frozen=True)
class _Directive:
    name: str
    start: int
    end: int
    args: tuple[str, ...]
    line: int


class _UncertainType:
    """Marker for a macro whose path value is not a definite literal."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNCERTAIN"


UNCERTAIN = _UncertainType()


@dataclass(frozen=True)
class _MacroDef:
    name: str
    value: str | None
    start: int
    provide_only: bool = False
    global_scope: bool = False

    def state(self) -> object:
        return UNCERTAIN if self.value is None else self.value


@dataclass(frozen=True)
class _ScopeEvent:
    opening: bool
    start: int


@dataclass(frozen=True)
class _ConditionalEvent:
    kind: str
    start: int
    names: tuple[str, ...] = ()


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


def _definition_event(text: str, index: int, name: str) -> _MacroDef | None:
    """Return a macro definition event, with None when the value is dynamic."""
    if name in {"def", "gdef", "edef", "xdef"}:
        match = _DEF_NAME.match(text, index)
        if not match:
            return None
        literal = _LITERAL_MACRO.match(text, index)
        value = None
        if literal is not None:
            value = literal.group(2) if literal.group(2) is not None else literal.group(4)
            value = value.strip() if value is not None else None
        return _MacroDef(match.group(1), value, index,
                         global_scope=name in {"gdef", "xdef"})
    if name in {"newcommand", "renewcommand", "providecommand",
                "DeclareRobustCommand"}:
        match = _NEWCOMMAND_NAME.match(text, index)
        if not match:
            return None
        literal = _LITERAL_MACRO.match(text, index)
        value = None
        if literal is not None:
            value = literal.group(2) if literal.group(2) is not None else literal.group(4)
            value = value.strip() if value is not None else None
        return _MacroDef(match.group(1), value, index,
                         provide_only=name == "providecommand")
    if name == "let":
        match = _LET_NAME.match(text, index)
        if not match:
            return None
        return _MacroDef(match.group(1), None, index)
    return None


def _scan(text: str) -> tuple[list, list[dict]]:
    """Scan one file into ordered scope, definition and directive events.

    Active branches of statically decidable ``\\iffalse``/``\\iftrue`` are
    scanned; the other branch is skipped. Other conditionals are undecidable,
    so both branches are kept and a directive inside one is marked uncertain.
    """
    items: list = []
    diagnostics: list[dict] = []
    conditionals = 0
    uncertain_directives = 0
    conditional_names: list[set[str]] = []
    defined_names: set[str] = set()

    def walk(start: int, stop: int, uncertain: int) -> None:
        nonlocal conditionals, uncertain_directives
        index = start
        while index < stop:
            char = text[index]
            if char == "%":
                end = text.find("\n", index)
                index = stop if end < 0 else end + 1
                continue
            if char == "{":
                items.append(_ScopeEvent(True, index))
                index += 1
                continue
            if char == "}":
                items.append(_ScopeEvent(False, index))
                index += 1
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
                if after < stop:
                    delimiter = text[after]
                    end = text.find(delimiter, after + 1, stop)
                    index = stop if end < 0 else end + 1
                else:
                    index = after
                continue
            if name == "begin":
                environment, group_end = _parse_group(text, after)
                if environment in LITERAL_ENVIRONMENTS:
                    closing = "\\end{" + environment + "}"
                    end = text.find(closing, group_end, stop)
                    index = stop if end < 0 else end + len(closing)
                    continue
                index = group_end
                continue
            if name in {"iffalse", "iftrue"}:
                else_start, fi_start, fi_end = _conditional_bounds(
                    text, after, defined_names)
                if fi_start >= stop:
                    diagnostics.append({"code": "unclosed_conditional",
                                        "name": name})
                    index = after
                    continue
                fi_start = min(fi_start, stop)
                fi_end = min(fi_end, stop)
                if name == "iffalse":
                    if else_start is None:
                        diagnostics.append({"code": "iffalse_skipped"})
                    else:
                        diagnostics.append({"code": "iffalse_else_branch"})
                        walk(min(else_start, stop), fi_start, uncertain)
                    index = fi_end
                    continue
                if else_start is None:
                    index = after
                else:
                    walk(after, min(else_start, stop), uncertain)
                    index = fi_end
                continue
            if name == "endinput":
                diagnostics.append({"code": "endinput"})
                break
            if _is_conditional(name, text, after, defined_names):
                branches, fi_start, fi_end, has_else = _conditional_branches(
                    text, after, name, defined_names, stop)
                if fi_start >= stop:
                    diagnostics.append({"code": "unclosed_conditional",
                                        "name": name})
                    index = after
                    continue
                if not has_else:
                    branches.append((fi_start, fi_start))
                conditionals += 1
                names: set[str] = set()
                conditional_names.append(names)
                items.append(_ConditionalEvent("enter", index))
                for position, (branch_start, branch_stop) in enumerate(branches):
                    if position:
                        items.append(_ConditionalEvent("switch", branch_start))
                    walk(branch_start, branch_stop, uncertain + 1)
                items.append(_ConditionalEvent("leave", fi_end,
                                               tuple(sorted(names))))
                conditional_names.pop()
                if conditional_names:
                    conditional_names[-1].update(names)
                index = fi_end
                continue
            if name == "fi":
                index = after
                continue
            if name in {"begingroup", "bgroup"}:
                items.append(_ScopeEvent(True, index))
                index = after
                continue
            if name in {"endgroup", "egroup"}:
                items.append(_ScopeEvent(False, index))
                index = after
                continue
            if name == "newif":
                probe = _skip_space(text, after)
                flag = _CONTROL.match(text, probe)
                if flag:
                    defined_names.update({flag.group(1) + "true",
                                          flag.group(1) + "false"})
                    index = flag.end()
                else:
                    index = probe
                continue
            if name in _DECLARATIONS:
                definition = _definition_event(text, index, name)
                if definition is not None:
                    items.append(definition)
                    defined_names.add(definition.name)
                    for names in conditional_names:
                        names.add(definition.name)
                index = _skip_definition(text, after, name)
                continue
            if name in DIRECTIVES:
                arguments, after_args = _parse_args(text, after, name)
                if len(arguments) == (1 if name in ONE_ARG else 2):
                    if uncertain > 0:
                        uncertain_directives += 1
                    items.append(_Directive(
                        name, index, after_args, arguments,
                        text.count("\n", 0, index) + 1))
                else:
                    diagnostics.append({"code": "unparsed_directive", "name": name})
                index = after_args
                continue
            index = after

    walk(0, len(text), 0)
    if conditionals:
        diagnostics.append({"code": "conditionals_present", "count": conditionals})
    if uncertain_directives:
        diagnostics.append({"code": "directive_in_conditional",
                            "count": uncertain_directives})
    return items, diagnostics


def _parse_group(text: str, index: int) -> tuple[str, int]:
    index = _skip_space(text, index)
    if index < len(text) and text[index] == "{":
        return _read_group(text, index)
    return "", index


def document_bounds(text: str) -> tuple[int | None, int | None, int | None]:
    """Locate ``\\begin{document}``/``\\end{document}`` outside literal content.

    Returns ``(begin_start, body_start, end_start)`` as character offsets.
    ``body_start`` is the offset just after ``\\begin{document}`` and
    ``end_start`` the offset of the first real ``\\end{document}``; both are
    ``None`` when the document markers are absent or unmatched. Comments,
    ``\\verb``-like constructs, literal environments, declaration bodies and
    inactive branches of statically decidable conditionals are skipped, so a
    marker shown in a definition or a disabled branch does not cut the body.
    """
    begin_start: int | None = None
    body_start: int | None = None
    end_start: int | None = None
    defined_names: set[str] = set()

    def walk(start: int, stop: int) -> None:
        nonlocal begin_start, body_start, end_start
        index = start
        while index < stop and end_start is None:
            char = text[index]
            if char == "%":
                newline = text.find("\n", index)
                index = stop if newline < 0 else newline + 1
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
                if after < stop:
                    delimiter = text[after]
                    newline = text.find(delimiter, after + 1, stop)
                    index = stop if newline < 0 else newline + 1
                else:
                    index = after
                continue
            if name in {"begin", "end"}:
                environment, group_end = _parse_group(text, after)
                environment = environment.strip()
                if name == "begin" and environment in LITERAL_ENVIRONMENTS:
                    closing = "\\end{" + environment + "}"
                    newline = text.find(closing, group_end, stop)
                    index = stop if newline < 0 else newline + len(closing)
                    continue
                if (name == "begin" and environment == "document"
                        and begin_start is None):
                    begin_start, body_start = index, group_end
                    index = group_end
                    continue
                if (name == "end" and environment == "document"
                        and begin_start is not None):
                    end_start = index
                    return
                index = group_end
                continue
            if name == "newif":
                probe = _skip_space(text, after)
                flag = _CONTROL.match(text, probe)
                if flag:
                    defined_names.update({flag.group(1) + "true",
                                          flag.group(1) + "false"})
                    index = flag.end()
                else:
                    index = probe
                continue
            if name in _DECLARATIONS:
                definition = _definition_event(text, index, name)
                if definition is not None:
                    defined_names.add(definition.name)
                index = _skip_definition(text, after, name)
                continue
            if name in {"iffalse", "iftrue"}:
                else_start, fi_start, fi_end = _conditional_bounds(
                    text, after, defined_names)
                if fi_start >= stop:
                    index = after
                    continue
                fi_start = min(fi_start, stop)
                fi_end = min(fi_end, stop)
                else_start = (min(else_start, stop)
                              if else_start is not None else None)
                if name == "iffalse":
                    if else_start is not None:
                        walk(else_start, fi_start)
                else:
                    walk(after, else_start if else_start is not None else fi_start)
                index = fi_end
                continue
            if _is_conditional(name, text, after, defined_names):
                _, fi_start, fi_end = _conditional_bounds(
                    text, after, defined_names)
                if fi_start >= stop:
                    index = after
                    continue
                index = min(fi_end, stop)
                continue
            index = after

    walk(0, len(text))
    return begin_start, body_start, end_start


def condition_regions(text: str) -> tuple[list[tuple[int, int]],
                                            list[tuple[int, int]]]:
    """Return inactive and uncertain character ranges for conditional content.

    ``inactive`` lists branches of statically decidable ``\\iffalse``/``\\iftrue``
    that are not part of the active document. ``uncertain`` lists regions of
    conditionals whose branch cannot be decided; both branches are kept there,
    so content inside one is not confirmed prose.
    """
    inactive: list[tuple[int, int]] = []
    uncertain: list[tuple[int, int]] = []
    defined: set[str] = set()

    def walk(start: int, stop: int) -> None:
        index = start
        while index < stop:
            char = text[index]
            if char == "%":
                newline = text.find("\n", index)
                index = stop if newline < 0 else newline + 1
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
                if after < stop:
                    delimiter = text[after]
                    newline = text.find(delimiter, after + 1, stop)
                    index = stop if newline < 0 else newline + 1
                else:
                    index = after
                continue
            if name == "begin":
                environment, group_end = _parse_group(text, after)
                if environment in LITERAL_ENVIRONMENTS:
                    closing = "\\end{" + environment + "}"
                    end = text.find(closing, group_end, stop)
                    index = stop if end < 0 else end + len(closing)
                    continue
                index = group_end
                continue
            if name == "newif":
                probe = _skip_space(text, after)
                flag = _CONTROL.match(text, probe)
                if flag:
                    defined.update({flag.group(1) + "true",
                                    flag.group(1) + "false"})
                    index = flag.end()
                else:
                    index = probe
                continue
            if name in _DECLARATIONS:
                definition = _definition_event(text, index, name)
                if definition is not None:
                    defined.add(definition.name)
                index = _skip_definition(text, after, name)
                continue
            if name in {"iffalse", "iftrue"}:
                else_start, fi_start, fi_end = _conditional_bounds(
                    text, after, defined)
                if fi_start >= stop:
                    uncertain.append((index, stop))
                    return
                fi_start = min(fi_start, stop)
                fi_end = min(fi_end, stop)
                else_start = (min(else_start, stop)
                              if else_start is not None else None)
                if name == "iffalse":
                    if else_start is None:
                        inactive.append((after, fi_start))
                    else:
                        inactive.append((after, else_start))
                        walk(else_start, fi_start)
                else:
                    walk(after, else_start if else_start is not None else fi_start)
                    if else_start is not None:
                        inactive.append((else_start, fi_start))
                index = fi_end
                continue
            if _is_conditional(name, text, after, defined):
                _, fi_start, fi_end = _conditional_bounds(text, after, defined)
                if fi_start >= stop:
                    uncertain.append((index, stop))
                    return
                uncertain.append((index, min(fi_end, stop)))
                index = min(fi_end, stop)
                continue
            index = after

    walk(0, len(text))
    return inactive, uncertain


def _document_body(raw: bytes) -> tuple[int, int, bool, bool]:
    """Return body byte range, has-document flag, and preamble-dropped flag."""
    text = raw.decode("utf-8")
    begin_start, body_start, end_start = document_bounds(text)
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


def _unique_dirs(values: list[str]) -> list[str]:
    """Return search directories once each, preserving first-seen order."""
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


class Assembler:
    def __init__(self, files: Mapping[str, bytes]):
        self.files = dict(files)
        self.events: list[DirectiveEvent] = []
        self.diagnostics: list[dict] = []
        self.scopes: list[dict[str, object]] = [{}]
        self.conditional_frames: list[dict] = []

    def assemble(self, entry: str, *, diagnostics: list[dict] | None = None) -> AssemblyResult:
        clean_entry = _safe_literal(entry)
        if clean_entry is None or clean_entry not in self.files:
            raise ValueError(f"entry is not a regular source file: {entry!r}")
        self.scopes = [{}]
        self.conditional_frames = []
        data, segments, events, local_diagnostics = self._assemble_range(
            clean_entry, 0, len(self.files[clean_entry]), (), whole=True,
            context="")
        result = AssemblyResult(clean_entry, data, segments, events,
                                [*local_diagnostics, *(diagnostics or [])])
        return result

    def _assemble_range(self, rel: str, base: int, end: int,
                        stack: tuple[str, ...], *, whole: bool, context: str = ""
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
        _, body_start, _ = document_bounds(text)
        preamble_end = body_start
        items, diagnostics = _scan(text)
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
        for item in items:
            if isinstance(item, _ScopeEvent):
                if item.opening:
                    self.scopes.append({})
                elif len(self.scopes) > 1:
                    self.scopes.pop()
                continue
            if isinstance(item, _MacroDef):
                self._define(item)
                continue
            if isinstance(item, _ConditionalEvent):
                self._conditional(item)
                continue
            directive = item
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
            resolution = self._resolve(rel, directive, expanded_args, context)
            if resolution is None:
                add_original(start, stop)
                uncertain = self._uncertain_reference(expanded_args)
                event = _replace(
                    event,
                    outcome="uncertain_path" if uncertain else "dynamic_path",
                    out_byte_end=len(output), out_char_end=out_chars)
                events.append(event)
                cursor = stop
                continue
            (target, target_range, stripped, preamble_dropped, outcome, candidates,
             child_context) = resolution
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
            depth_before = len(self.scopes)
            frames_before = len(self.conditional_frames)
            child_data, child_segments, child_events, child_diagnostics = self._assemble_range(
                target, target_base, target_end, stack + (rel,),
                whole=stripped is False, context=child_context)
            del self.scopes[depth_before:]
            del self.conditional_frames[frames_before:]
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

    def _resolve(self, rel: str, directive: _Directive, args: tuple[str, ...],
                 context: str = ""
                 ) -> tuple[str, tuple[int, int], bool, bool, str, list[str] | None,
                          str] | None:
        name = directive.name
        if any(not argument or any(char in argument for char in "\\#{}$%")
               for argument in args):
            return None
        if any(_escapes_tree(argument) for argument in args):
            return ("", (0, 0), False, False, "outside_root", None, "")
        current = rel.rsplit("/", 1)[0] if "/" in rel else ""
        candidates: list[str] = []
        if name in ONE_ARG:
            literal = _safe_literal(args[0])
            if literal is None:
                return None
            bases = [context, "", current]
            for base in _unique_dirs(bases):
                joined = self._join(base, literal)
                for candidate in _with_suffix(joined):
                    if candidate not in candidates:
                        candidates.append(candidate)
        else:
            directory = _safe_literal(args[0])
            filename = _safe_literal(args[1])
            if directory is None or filename is None:
                return None
            sub = name in {"subimport", "subincludefrom", "subinputfrom"}
            roots = _unique_dirs([context, current, ""] if sub else ["", current])
            for root in roots:
                joined = self._join(root, self._join(directory, filename))
                for candidate in _with_suffix(joined):
                    if candidate not in candidates:
                        candidates.append(candidate)
        unique: list[str] = []
        for candidate in candidates:
            normalized = _safe_literal(candidate)
            if normalized is None:
                return ("", (0, 0), False, False, "outside_root", None, "")
            if normalized not in unique:
                unique.append(normalized)
        existing = [candidate for candidate in unique if candidate in self.files]
        if not existing:
            return ("", (0, 0), False, False, "missing", None, "")
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
        if name in {"input", "include"}:
            child_context = context
        else:
            child_context = chosen.rsplit("/", 1)[0] if "/" in chosen else ""
        return (chosen, target_range, stripped, preamble_dropped, "resolved",
                existing[1:] or None, child_context)

    def _macro(self, name: str) -> object | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    @staticmethod
    def _lookup_in(scopes: list[dict[str, object]], name: str) -> object | None:
        for scope in reversed(scopes):
            if name in scope:
                return scope[name]
        return None

    def _copy_scopes(self) -> list[dict[str, object]]:
        return [dict(scope) for scope in self.scopes]

    def _define(self, definition: _MacroDef) -> None:
        if (definition.provide_only
                and self._macro(definition.name) is not None):
            return
        state = definition.state()
        if definition.global_scope:
            if self.conditional_frames:
                frame = self.conditional_frames[-1]
                frame["current_globals"][definition.name] = state
            for scope in self.scopes:
                scope.pop(definition.name, None)
            self.scopes[0][definition.name] = state
            return
        self.scopes[-1][definition.name] = state

    def _conditional(self, event: _ConditionalEvent) -> None:
        if event.kind == "enter":
            self.conditional_frames.append({
                "snapshot": self._copy_scopes(),
                "states": [],
                "globals": [],
                "current_globals": {},
            })
            return
        if event.kind == "switch":
            if not self.conditional_frames:
                return
            frame = self.conditional_frames[-1]
            frame["states"].append(self._copy_scopes())
            frame["globals"].append(dict(frame["current_globals"]))
            frame["current_globals"] = {}
            self.scopes = [dict(scope) for scope in frame["snapshot"]]
            return
        if event.kind == "leave":
            if not self.conditional_frames:
                return
            frame = self.conditional_frames.pop()
            frame["states"].append(self._copy_scopes())
            frame["globals"].append(dict(frame["current_globals"]))
            self.scopes = [dict(scope) for scope in frame["snapshot"]]
            self._merge_branches(event.names, frame)

    def _merge_branches(self, names: tuple[str, ...], frame: dict) -> None:
        states: list[list[dict[str, object]]] = frame["states"]
        writes: list[dict[str, object]] = frame["globals"]
        if not states:
            return
        for name in names:
            values = [self._lookup_in(branch, name) for branch in states]
            first = values[0]
            if all(isinstance(value, str) and value == first
                   for value in values):
                state: object = first
            elif all(value is None for value in values):
                continue
            else:
                state = UNCERTAIN
            if any(name in branch for branch in writes):
                for scope in self.scopes:
                    scope.pop(name, None)
                self.scopes[0][name] = state
                if self.conditional_frames:
                    self.conditional_frames[-1]["current_globals"][name] = state
            else:
                self.scopes[-1][name] = state

    def _uncertain_reference(self, arguments: tuple[str, ...]) -> bool:
        for argument in arguments:
            for match in re.finditer(r"\\([A-Za-z@]+)", argument):
                if self._macro(match.group(1)) is UNCERTAIN:
                    return True
        return False

    def _expand_literal(self, value: str) -> str:
        def replace(match: re.Match) -> str:
            name = match.group(1)
            found = self._macro(name)
            return found if isinstance(found, str) else match.group(0)
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


_OPTIONAL_ARGUMENT_KINDS = frozenset({
    "theorem", "lemma", "proposition", "corollary", "conjecture", "definition",
    "proof", "remark", "example", "claim", "assumption", "notation",
    "statement_other", "table", "figure", "algorithm",
})


def _block_text(value: str, kind: str | None, environment: str | None) -> str:
    """Strip an environment's own arguments and return plain reading text.

    Only the optional title/placement argument of a known argument-taking
    environment is removed. A brace group directly after ``\begin{...}`` is
    body text, not an argument, and is kept.
    """
    if kind == "equation":
        return value.strip()
    if environment:
        optional = (r"(?:\[[^\]]*\])?"
                    if kind in _OPTIONAL_ARGUMENT_KINDS else "")
        opening = re.compile(r"\s*\\begin\{" + re.escape(environment)
                             + r"\}" + optional, re.S)
        value = opening.sub("", value, count=1)
        end = value.rfind("\\end{" + environment + "}")
        if end >= 0:
            value = value[:end]
    return _plain(value)


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


class SourceLineIndex:
    """Map a source character offset to a 1-based line number."""

    def __init__(self, files: Mapping[str, bytes] | None):
        self._starts: dict[str, list[int]] = {}
        for path, raw in (files or {}).items():
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            self._starts[path] = _line_starts(text)

    def line_at(self, path: str, position: int) -> int | None:
        starts = self._starts.get(path)
        if not starts:
            return None
        return bisect.bisect_right(starts, max(0, int(position)))


def entry_source_spans(result: AssemblyResult, start: int,
                       end: int) -> list[tuple[str, int, int]]:
    """Map an entry character range to the original source ranges it covers.

    The assembled entry is a tiling of source segments, so a range inside one
    included file maps to one source range, while a range that crosses an
    include boundary maps to several ranges in entry order.
    """
    segments = result.segments
    if not segments or end <= start:
        return []
    starts = [segment.out_char_start for segment in segments]
    index = max(0, bisect.bisect_right(starts, start) - 1)
    spans: list[tuple[str, int, int]] = []
    while index < len(segments) and segments[index].out_char_start < end:
        segment = segments[index]
        low = max(start, segment.out_char_start)
        high = min(end, segment.out_char_end)
        if low < high:
            offset = low - segment.out_char_start
            spans.append((segment.path, segment.char_start + offset,
                          segment.char_start + offset + (high - low)))
        index += 1
    return spans


def merge_blocks(result: AssemblyResult, blocks: list[dict], *,
                 source_tree_hash: str,
                 files: Mapping[str, bytes] | None = None) -> dict:
    """Build an entry-ordered document model from one parse of the entry.

    The parser reads the assembled entry, so a block's character range is an
    entry range; every block is projected back onto the original source files
    through the source map. A block whose range crosses an include boundary
    keeps its first source range as ``source`` and lists every range, in entry
    order, in ``source_spans``. Section levels are normalized per entry: the
    highest sectioning level present becomes 1. Blocks carry plain reading text
    plus exact source and entry spans.
    """
    entry_text = result.text
    char_to_byte = [0] * (len(entry_text) + 1)
    byte_cursor = 0
    for index, char in enumerate(entry_text):
        char_to_byte[index] = byte_cursor
        byte_cursor += len(char.encode("utf-8"))
    char_to_byte[len(entry_text)] = byte_cursor
    lines = SourceLineIndex(files)

    merged: list[dict] = []
    for block in blocks:
        source = block.get("source") or {}
        start = int(source.get("char_start", 0))
        end = int(source.get("char_end", 0))
        if end <= start:
            continue
        kind = block.get("kind")
        block_text = block.get("latex", "")
        body_text = _block_text(block_text, kind, block.get("environment"))
        if kind in {"paragraph", "unknown"} and not body_text:
            continue
        spans = entry_source_spans(result, start, end)
        if not spans:
            raise ValueError("block does not map to the source tree: "
                             f"{source.get('path')!r} [{start}, {end})")
        anchor_entry = block.get("anchor_entry")
        if not isinstance(anchor_entry, int):
            anchor_entry = start
            for index, char in enumerate(block_text):
                if not char.isspace():
                    anchor_entry = start + index
                    break
        anchor_entry = max(start, min(anchor_entry, max(start, end - 1)))
        anchor_spans = entry_source_spans(result, anchor_entry, end)
        first = anchor_spans[0] if anchor_spans else spans[0]
        record = {
            "kind": kind,
            "environment": block.get("environment"),
            "level": None,
            "source_level": block.get("section_level"),
            "command": None,
            "numbered": None,
            "appendix": False,
            "title": "",
            "title_tex": block.get("title_tex", ""),
            "text": body_text,
            "labels": list(block.get("labels") or []),
            "references": list(block.get("references") or []),
            "source": {
                "path": first[0],
                "char_start": first[1],
                "char_end": first[2],
                "line_start": lines.line_at(first[0], first[1]),
                "line_end": lines.line_at(first[0], max(first[1], first[2] - 1)),
            },
            "source_spans": [
                {"path": path, "char_start": low, "char_end": high,
                 "line_start": lines.line_at(path, low),
                 "line_end": lines.line_at(path, max(low, high - 1))}
                for path, low, high in spans],
            "entry": {
                "char_start": start,
                "char_end": end,
                "byte_start": char_to_byte[start],
                "byte_end": char_to_byte[end],
            },
            "origin_block_key": block.get("key"),
            "origin_parent_key": block.get("parent_key"),
            "spans_include": len(spans) > 1,
        }
        if kind == "section":
            record["command"], record["numbered"] = _section_metadata(
                block_text, record["source_level"])
            record["title"] = _plain(block.get("title_tex", ""))
        merged.append(record)

    for index, block in enumerate(merged, start=1):
        block["order"] = index
        block["key"] = f"block-{index}"
    key_map = {block["origin_block_key"]: block["key"]
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
            "source_spans": block["source_spans"],
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
        origin_parent = key_map.get(block.get("origin_parent_key"))
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
