"""Conservative, source-preserving LaTeX structure extraction.

This module uses pylatexenc 2.10's AST and recognizes a limited set of
structural declarations without running TeX or expanding arbitrary macros.
Offsets are half-open Python Unicode character offsets in UTF-8-decoded
source.  File digests are SHA-256 of the original bytes, including CRLF/BOM.
"""
from __future__ import annotations

from ..core.progress import phase

from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .. import PARSER_VERSION
from ..core.coordinates import SourceLines
from .reading import CITATION_COMMANDS as _CITATIONS

try:
    from pylatexenc import __version__ as PYLATEXENC_VERSION
    from pylatexenc.latexwalker import (
        LatexWalker, LatexWalkerEndOfStream, LatexWalkerParseError, LatexToken,
        LatexCharsNode, LatexCommentNode,
        LatexEnvironmentNode, LatexGroupNode, LatexMacroNode, LatexMathNode,
        get_default_latex_context_db,
    )
    from pylatexenc.macrospec import (
        EnvironmentSpec, LatexContextDb, MacroSpec, MacroStandardArgsParser, ParsedMacroArgs,
        ParsedVerbatimArgs,
    )
except ImportError as exc:
    raise ImportError("qecgraph's LaTeX parser requires pylatexenc==2.10") from exc


_KINDS = {
    "definition", "lemma", "theorem", "proposition", "corollary", "conjecture",
    "proof", "equation", "table", "figure", "remark", "example",
    "abstract", "algorithm", "assumption", "claim", "notation", "acknowledgments", "statement_other",
    "title", "author_block", "bib_entry",
}
_ENVIRONMENTS = {
    "definition": "definition", "defn": "definition", "dfn": "definition",
    "lemma": "lemma", "lem": "lemma", "theorem": "theorem", "thm": "theorem",
    "proposition": "proposition", "prop": "proposition", "corollary": "corollary",
    "cor": "corollary", "conjecture": "conjecture", "conj": "conjecture",
    "proof": "proof", "remark": "remark", "rem": "remark", "example": "example",
    "exmp": "example", "table": "table", "figure": "figure",
    "equation": "equation", "align": "equation", "alignat": "equation",
    "gather": "equation", "multline": "equation", "flalign": "equation",
    "displaymath": "equation",
}
_ENVIRONMENTS.update({
    'abstract': 'abstract', 'algorithm': 'algorithm', 'algorithmic': 'algorithm', 'algobox': 'algorithm',
    'assumption': 'assumption', 'claim': 'claim', 'fact': 'claim', 'observation': 'claim',
    'notation': 'notation', 'acknowledgments': 'acknowledgments', 'acknowledgements': 'acknowledgments',
})
_SECTIONS = {"part": -1, "chapter": 0, "section": 1, "subsection": 2,
             "subsubsection": 3, "paragraph": 4, "subparagraph": 5}
_COMMAND_DECLARATIONS = {"newcommand", "renewcommand", "providecommand", "DeclareRobustCommand"}
_PRIMITIVE_DEFINITIONS = {"def", "gdef", "edef", "xdef"}
_DECLARATIONS = _COMMAND_DECLARATIONS | _PRIMITIVE_DEFINITIONS | {
    "DeclareMathOperator", "newenvironment", "renewenvironment", "newtheorem",
}
_LITERAL_ENVIRONMENTS = {
    "verbatim", "verbatim*", "Verbatim", "BVerbatim", "LVerbatim",
    "lstlisting", "minted", "comment", "filecontents", "filecontents*",
}
_LITERAL_MACROS = {"verb", "lstinline", "mintinline"}
_LINK_MACROS = {"href", "url", "nolinkurl"}
_METADATA_MACROS = {"label", "uses", "proves", "lean", "leanok", "mathlibok", "notready"}
_REFERENCE_KINDS = {
    "ref": "ref", "eqref": "eqref", "cref": "cref", "Cref": "cref",
    "autoref": "autoref", "Autoref": "autoref", "vref": "ref", "Vref": "ref",
    "pageref": "ref", "nameref": "ref", "uses": "uses", "proves": "proves",
}
_CONDITIONALS = {
    "if", "ifx", "ifnum", "ifdim", "ifcase", "ifdefined", "ifcsname",
    "iftrue", "iffalse", "ifmmode", "ifhmode", "ifvmode", "ifodd", "ifcat",
    "ifeof", "ifvoid", "ifhbox", "ifvbox", "ifinner", "ifthenelse", "ifboolexpr",
}
_CONDITIONAL_MACROS = {"ifthenelse", "ifboolexpr"}
_CONTROL_WORD = re.compile(r"\\([A-Za-z@]+)")
_ENVIRONMENT_ALIAS = re.compile(r"\\(begin|end)\s*\{([A-Za-z0-9* ._-]+)\}")
_STRUCTURAL_TOKEN = re.compile(r"[\\%{}]")


def _next_token(w, pos, parsing_state):
    while True:
        try:
            token = w.get_token(pos, parsing_state=parsing_state, environments=False)
        except LatexWalkerEndOfStream:
            return None
        if token.tok != "comment":
            return token
        pos = token.pos + token.len


def _opaque_group(w, pos, opening, closing, parsing_state):
    """Read balanced tokens while leaving declaration replacement text opaque."""
    stack = [opening]
    current = pos + 1
    while stack:
        token = _next_token(w, current, parsing_state)
        if token is None:
            raise LatexWalkerParseError(s=w.s, pos=pos, msg="Unclosed declaration argument")
        character = token.arg if token.tok in {"char", "brace_open", "brace_close"} else None
        if character == "{":
            stack.append("{")
        elif opening == "[" and character == "[" and stack[-1] == "[":
            stack.append("[")
        elif character == "}" and stack[-1] == "{":
            stack.pop()
        elif character == "]" and stack[-1] == "[":
            stack.pop()
        current = token.pos + token.len
    content = w.make_node(LatexCharsNode, parsing_state=parsing_state,
                          pos=pos + 1, len=token.pos - pos - 1,
                          chars=w.s[pos + 1:token.pos])
    return w.make_node(LatexGroupNode, parsing_state=parsing_state, pos=pos,
                       len=current - pos, nodelist=[content], delimiters=(opening, closing)), current


class _OpaqueDeclarationParser(MacroStandardArgsParser):
    """Parse declaration arguments without treating their bodies as a document."""

    def parse_args(self, w, pos, parsing_state=None):
        original = pos
        args = []
        for expected in self.argspec:
            token = _next_token(w, pos, parsing_state)
            if expected == "*":
                if token is not None and token.tok == "char" and token.arg == "*":
                    args.append(w.make_node(LatexCharsNode, parsing_state=parsing_state,
                                            pos=token.pos, len=token.len, chars="*"))
                    pos = token.pos + token.len
                else:
                    args.append(None)
            elif expected == "[":
                if token is not None and token.tok == "char" and token.arg == "[":
                    group, pos = _opaque_group(w, token.pos, "[", "]", parsing_state)
                    args.append(group)
                else:
                    args.append(None)
            else:
                if token is None:
                    raise LatexWalkerParseError(s=w.s, pos=pos, msg="Missing declaration argument")
                if token.tok == "brace_open":
                    group, pos = _opaque_group(w, token.pos, "{", "}", parsing_state)
                    args.append(group)
                else:
                    node, start, length = w.get_latex_expression(token.pos, parsing_state=parsing_state,
                                                                strict_braces=True)
                    args.append(node)
                    pos = start + length
        return ParsedMacroArgs(argspec=self.argspec, argnlist=args), original, pos - original


_LINK_TARGET_TOKEN = re.compile(r"\\[\\{}]|[{}]")


class _LinkArgsParser(MacroStandardArgsParser):
    """Read braced URLs with literal percent signs, then parse link text as TeX."""

    def __init__(self, *, with_text=False):
        super().__init__(argspec="[{{" if with_text else "{")
        self.with_text = with_text

    def parse_target(self, w, pos, parsing_state):
        args = []
        if self.with_text:
            token = _next_token(w, pos, parsing_state)
            option = None
            if token is not None and token.tok == "char" and token.arg == "[":
                option, start, length = w.get_latex_braced_group(token.pos, brace_type="[",
                                                                 parsing_state=parsing_state)
                pos = start + length
            args.append(option)

        token = _next_token(w, pos, parsing_state)
        if token is None:
            raise LatexWalkerParseError(s=w.s, pos=pos, msg="Missing link target")
        if token.tok != "brace_open":
            target, start, length = w.get_latex_expression(token.pos, strict_braces=True,
                                                           parsing_state=parsing_state)
            return [*args, target], start + length

        start = token.pos
        depth = 1
        for delimiter in _LINK_TARGET_TOKEN.finditer(w.s, start + 1):
            if delimiter[0] == "{":
                depth += 1
            elif delimiter[0] == "}":
                depth -= 1
                if depth == 0:
                    end = delimiter.end()
                    raw = w.s[start + 1:end - 1]
                    chars = w.make_node(LatexCharsNode, parsing_state=parsing_state,
                                        pos=start + 1, len=len(raw), chars=raw)
                    target = w.make_node(LatexGroupNode, parsing_state=parsing_state, pos=start,
                                         len=end - start, nodelist=[chars], delimiters=("{", "}"))
                    return [*args, target], end
        raise LatexWalkerParseError(s=w.s, pos=start, msg="Unclosed link target")

    def parse_args(self, w, pos, parsing_state=None):
        original = pos
        args, pos = self.parse_target(w, pos, parsing_state)
        if self.with_text:
            text, start, length = w.get_latex_expression(pos, strict_braces=True, parsing_state=parsing_state)
            args.append(text)
            pos = start + length
        return ParsedMacroArgs(argspec=self.argspec, argnlist=args), original, pos - original


class _InlineLiteralParser(MacroStandardArgsParser):
    def __init__(self, name):
        super().__init__(argspec="{")
        self.name = name

    def parse_args(self, w, pos, parsing_state=None):
        original = pos
        if pos < len(w.s) and w.s[pos] == "*":
            pos += 1
        if self.name == "lstinline":
            token = _next_token(w, pos, parsing_state)
            if token is not None and token.tok == "char" and token.arg == "[":
                _, pos = _opaque_group(w, token.pos, "[", "]", parsing_state)
        while pos < len(w.s) and w.s[pos] in " \t":
            pos += 1
        if pos >= len(w.s) or w.s[pos] in "\r\n":
            raise LatexWalkerParseError(s=w.s, pos=pos, msg="Missing inline verbatim delimiter")
        opening = w.s[pos]
        closing = "}" if self.name == "lstinline" and opening == "{" else opening
        end = w.s.find(closing, pos + 1)
        if end < 0 or "\n" in w.s[pos + 1:end]:
            raise LatexWalkerParseError(s=w.s, pos=pos, msg="Unclosed inline verbatim text")
        chars = w.make_node(LatexCharsNode, parsing_state=parsing_state,
                            pos=pos + 1, len=end - pos - 1, chars=w.s[pos + 1:end])
        return ParsedVerbatimArgs(chars, verbatim_delimiters=(opening, closing)), original, end + 1 - original


class _LiteralEnvironmentParser(MacroStandardArgsParser):
    """Consume an opaque environment exactly as a verbatim environment does."""

    def __init__(self, name: str):
        super().__init__(argspec="{")
        self.name = name

    def parse_args(self, w, pos, parsing_state=None):
        closing = "\\end{" + self.name + "}"
        end = w.s.find(closing, pos)
        if end < 0:
            raise LatexWalkerParseError(s=w.s, pos=pos, msg=f"Missing {closing}")
        chars = w.make_node(LatexCharsNode, parsing_state=parsing_state,
                            pos=pos, len=end - pos, chars=w.s[pos:end])
        return ParsedVerbatimArgs(chars), pos, end - pos


class _InputParser(MacroStandardArgsParser):
    """Accept both \\input{file} and the conventional \\input file.tex form."""

    def __init__(self):
        super().__init__(argspec="{")

    def parse_args(self, w, pos, parsing_state=None):
        original = pos
        while pos < len(w.s):
            if w.s[pos].isspace():
                pos += 1
            elif w.s[pos] == "%":
                newline = w.s.find("\n", pos)
                pos = len(w.s) if newline < 0 else newline + 1
            else:
                break
        if pos >= len(w.s):
            raise LatexWalkerParseError(s=w.s, pos=pos, msg="Missing input filename")
        if w.s[pos] in "{\\":
            node, start, length = w.get_latex_expression(pos, parsing_state=parsing_state,
                                                        strict_braces=True)
            return ParsedMacroArgs(argspec="{", argnlist=[node]), original, start + length - original
        end = pos
        while end < len(w.s) and not w.s[end].isspace() and w.s[end] not in "%{}\\":
            end += 1
        if end == pos:
            raise LatexWalkerParseError(s=w.s, pos=pos, msg="Invalid input filename")
        node = w.make_node(LatexCharsNode, parsing_state=parsing_state,
                           pos=pos, len=end - pos, chars=w.s[pos:end])
        return ParsedMacroArgs(argspec="{", argnlist=[node]), original, end - original


class _PrimitiveDefinitionParser(MacroStandardArgsParser):
    """Keep a primitive macro definition opaque; do not interpret its body."""

    def __init__(self):
        super().__init__(argspec="{")

    def parse_args(self, w, pos, parsing_state=None):
        start = pos
        # The parameter preamble is intentionally not interpreted or executed.
        while pos < len(w.s):
            tok = w.get_token(pos, parsing_state=parsing_state, environments=False)
            if tok.tok == "brace_open":
                node, end = _opaque_group(w, tok.pos, "{", "}", parsing_state)
                return ParsedMacroArgs(argspec="{", argnlist=[node]), start, end - start
            pos = tok.pos + tok.len
        raise LatexWalkerParseError(s=w.s, pos=start, msg="Missing primitive macro definition body")


def _args(node):
    return list(getattr(getattr(node, "nodeargd", None), "argnlist", []) or [])


def _raw_arg(node, text: str) -> str:
    if node is None:
        return ""
    value = text[node.pos:node.pos + node.len]
    if isinstance(node, LatexGroupNode):
        return value[len(node.delimiters[0]):len(value) - len(node.delimiters[1])]
    return value


def _last_arg(node, text: str) -> str:
    values = [a for a in _args(node) if a is not None]
    return _raw_arg(values[-1], text) if values else ""


def _children(node):
    if isinstance(node, LatexEnvironmentNode) and node.environmentname in _LITERAL_ENVIRONMENTS:
        return []
    if isinstance(node, LatexMacroNode) and node.macroname in _DECLARATIONS | _LITERAL_MACROS:
        return []
    values = []
    values.extend(a for a in _args(node) if a is not None)
    values.extend(getattr(node, "nodelist", None) or [])
    return values


class _StructuralWalker(LatexWalker):
    """Use environment tokens at the original control word's source coordinates."""

    def __init__(self, text, aliases, **kwargs):
        super().__init__(text, **kwargs)
        self.aliases = aliases

    def get_token(self, pos, include_brace_chars=None, environments=True,
                  keep_inline_math=None, parsing_state=None, **kwargs):
        token = super().get_token(pos, include_brace_chars, environments,
                                  keep_inline_math, parsing_state, **kwargs)
        if environments and token.tok == "macro" and token.pos in self.aliases:
            operation, name = self.aliases[token.pos]
            return LatexToken(operation + "_environment", name, token.pos,
                              1 + len(token.arg), token.pre_space)
        return token


class _ProjectLatexContext(LatexContextDb):
    """Avoid probing every special sequence for ordinary text characters."""

    def __init__(self):
        super().__init__()
        default = get_default_latex_context_db()
        for name in default.categories():
            self.add_context_category(name, macros=default.iter_macro_specs([name]),
                                      environments=default.iter_environment_specs([name]),
                                      specials=default.iter_specials_specs([name]))
        # Project-specific context additions supply macros and environments only.
        self._special_starts = frozenset(spec.specials_chars[0] for spec in self.iter_specials_specs()
                                         if spec.specials_chars)

    def test_for_specials(self, s, pos, parsing_state=None):
        if 0 <= pos < len(s) and s[pos] not in self._special_starts:
            return None
        return super().test_for_specials(s, pos, parsing_state)


class _StructuralConditionals:
    def __init__(self):
        self.stack = []
        self.masked = []
        self.selected = []
        self.inactive_start = None

    def uncertain(self):
        return any(value is None for value, _ in self.stack)

    def scan(self, token, pos, walker, state, bindings, *, opens):
        name = token.arg
        was_inactive = self.inactive_start is not None
        if opens:
            decidable = not was_inactive and not self.uncertain()
            decision = {"iftrue": True, "iffalse": False}.get(name) if decidable else None
            if name == "ifdefined" and not was_inactive:
                operand = _next_token(walker, pos, state)
                if operand is not None:
                    pos = operand.pos + operand.len
                    if decidable and operand.tok == "macro" and operand.arg in bindings:
                        decision = True
            elif name == "ifx" and not was_inactive:
                # The compared control tokens are read without expanding them.
                for _ in range(2):
                    operand = _next_token(walker, pos, state)
                    if operand is None:
                        break
                    pos = operand.pos + operand.len
            self.stack.append((decision, False))
            if decision is not None and not was_inactive:
                self.selected.append((token.pos, pos))
        else:
            decision, in_else = self.stack.pop()
            if name == "else":
                if in_else and decision is not None:
                    raise LatexWalkerParseError(s=walker.s, pos=token.pos, msg="Repeated conditional else")
                self.stack.append((None if decision is None else not decision, True))
        inactive = any(value is False for value, _ in self.stack)
        if was_inactive and not inactive:
            self.masked.append((self.inactive_start, pos))
            self.inactive_start = None
        elif inactive and not was_inactive:
            self.inactive_start = token.pos
        elif not inactive and decision is not None:
            self.masked.append((token.pos, pos))
        return pos


def _scan_structure(text, inherited, context, known_conditionals):
    """Find literal environment aliases and statically decidable branch ranges."""
    walker = LatexWalker(text, latex_context=context, tolerant_parsing=False)
    state = walker.make_parsing_state()
    scopes = [(None, dict(inherited))]
    conditionals = _StructuralConditionals()
    conditional_names = known_conditionals - _CONDITIONAL_MACROS
    aliases, include_bindings = {}, {}
    pos = 0
    # Only control sequences, comments and grouping can affect this scan.
    # Argument readers still consume the original token stream.
    while (structural := _STRUCTURAL_TOKEN.search(text, pos)) is not None:
        token = _next_token(walker, structural.start(), state)
        if token is None:
            break
        pos = token.pos + token.len
        bindings = scopes[-1][1]
        name = token.arg if token.tok == "macro" else None
        opens = name in conditional_names
        if opens or (conditionals.stack and name in {"else", "fi"}):
            pos = conditionals.scan(token, pos, walker, state, bindings, opens=opens)
            continue
        if conditionals.inactive_start is not None:
            continue

        uncertain = conditionals.uncertain()
        if name in _LINK_MACROS:
            parser = context.get_macro_spec(name).args_parser
            if isinstance(parser, _LinkArgsParser):
                # Keep the visible link text in the structural token stream.
                _, pos = parser.parse_target(walker, pos, state)
                continue
        if name == "let":
            target = _next_token(walker, pos, state)
            if target is not None and target.tok == "macro":
                bindings[target.arg] = None
                value = _next_token(walker, target.pos + target.len, state)
                if value is not None and value.tok == "char" and value.arg == "=":
                    value = _next_token(walker, value.pos + value.len, state)
                pos = value.pos + value.len if value is not None else len(text)
                continue
        if name in _DECLARATIONS | _LITERAL_MACROS | {"newif", "input", "include"}:
            parser = context.get_macro_spec(name).args_parser
            arguments, start, length = parser.parse_args(walker, pos, parsing_state=state)
            args = arguments.argnlist
            if name in _COMMAND_DECLARATIONS:
                control = _CONTROL_WORD.fullmatch(_raw_arg(args[1], text).strip())
                if control:
                    target = control[1]
                    if uncertain or any(scope == ("brace_close", "{") for scope, _ in scopes):
                        bindings.pop(target, None)
                    elif name != "providecommand" or target not in bindings:
                        replacement = _raw_arg(args[4], text).strip()
                        zero_args = args[2] is None or _raw_arg(args[2], text).strip() == "0"
                        alias = _ENVIRONMENT_ALIAS.fullmatch(replacement) if zero_args else None
                        bindings[target] = alias.groups() if alias and name != "providecommand" else None
            elif name in _PRIMITIVE_DEFINITIONS:
                # A primitive definition can shadow a previously seen declaration.
                target = _next_token(walker, pos, state)
                if target is not None and target.tok == "macro":
                    affected = scopes if name in {"gdef", "xdef"} else scopes[-1:]
                    for _, definitions in affected:
                        # The replacement text stays opaque, but the name is defined
                        # for a later statically decidable \ifdefined.
                        definitions[target.arg] = None
            elif name in {"input", "include"}:
                include_bindings[token.pos] = dict(bindings)
            elif name == "newif":
                custom = _CONTROL_WORD.fullmatch(_raw_arg(args[0], text).strip())
                if custom:
                    conditional_names.add(custom[1])
            pos = start + length
            continue

        operation = None
        if name in {"begin", "end"}:
            environment = walker.get_token(token.pos, parsing_state=state)
            operation, environment_name = name, environment.arg
            pos = environment.pos + environment.len
            if operation == "begin" and environment_name in _LITERAL_ENVIRONMENTS:
                parser = context.get_environment_spec(environment_name).args_parser
                _, start, length = parser.parse_args(walker, pos, parsing_state=state)
                pos = start + length
                continue
        elif not uncertain and name in bindings and bindings[name] is not None:
            operation, environment_name = aliases[token.pos] = bindings[name]
        if operation == "begin":
            scopes.append((("end", environment_name), dict(bindings)))
        elif token.tok == "brace_open":
            scopes.append((("brace_close", token.arg), dict(bindings)))
        elif ((operation == "end" and scopes[-1][0] == ("end", environment_name))
              or (token.tok == "brace_close" and scopes[-1][0] == ("brace_close", "{"))):
            scopes.pop()

    if any(value is not None for value, _ in conditionals.stack):
        raise LatexWalkerParseError(s=text, pos=len(text), msg="Unclosed statically recognized conditional")
    if not conditionals.masked:
        return text, aliases, include_bindings, conditionals.selected
    parts = []
    pos = 0
    for start, end in conditionals.masked:
        parts.extend((text[pos:start], re.sub(r"[^\r\n]", " ", text[start:end])))
        pos = end
    return "".join(parts) + text[pos:], aliases, include_bindings, conditionals.selected


class _ProjectParser:
    def __init__(self, entry: Path, project_root: Path, config: dict[str, Any], node_cache=None):
        self.node_cache = node_cache
        self.root = project_root.resolve()
        self.entry = entry.resolve()
        if not self.entry.is_relative_to(self.root):
            raise ValueError("Entry file must be inside project_root")
        if self.entry.suffix.lower() != ".tex":
            raise ValueError("Entry file must have a .tex suffix")
        self.config = config
        self.environment_map = dict(_ENVIRONMENTS)
        self.environment_headings = {}
        explicit = config.get("environment_map", {})
        if not isinstance(explicit, dict) or any(k not in _KINDS for k in explicit.values()):
            raise ValueError("environment_map must map environment names to supported block kinds")
        self.explicit_environments = explicit
        self.environment_map.update(explicit)
        self.macro_specs: dict[str, str] = {}
        self.files: dict[str, dict] = {}
        self.structures: dict[str, tuple] = {}
        self.source_lines: dict[str, SourceLines] = {}
        self.discovered: set[str] = set()
        self.discovery_stack: list[str] = []
        self.emitted: set[str] = set()
        self.blocks: list[dict] = []
        self.by_key: dict[str, dict] = {}
        self.includes: list[dict] = []
        self.resources: list[dict] = []
        self.include_targets: dict[tuple[str, int], str | None] = {}
        self.diagnostics: list[dict] = []
        self.diagnostic_keys: set[tuple] = set()
        self.context = self._context()
        self._conditional_names = set(_CONDITIONALS)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def span(self, path: str, start: int, end: int) -> dict:
        lines = self.source_lines[path]
        return {"path": path, "char_start": start, "char_end": end,
                "line_start": lines.line_at(start),
                "line_end": lines.line_at(max(start, end - 1))}

    def node_span(self, path: str, node) -> dict:
        return self.span(path, node.pos, node.pos + node.len)

    def diagnostic(self, severity: str, code: str, message: str, source=None):
        key = (code, message, source.get("path") if source else None,
               source.get("char_start") if source else None)
        if key not in self.diagnostic_keys:
            self.diagnostic_keys.add(key)
            self.diagnostics.append({"severity": severity, "code": code,
                                     "message": message, "source": source})

    def _context(self):
        context = _ProjectLatexContext()
        specs = {name: MacroSpec(name, args_parser=signature)
                 for name, signature in self.macro_specs.items()}
        for name in _SECTIONS:
            specs[name] = MacroSpec(name, args_parser="*[{" )
        for name in _REFERENCE_KINDS:
            specs[name] = MacroSpec(name, args_parser="*{")
        for name in _CITATIONS:
            specs[name] = MacroSpec(name, args_parser="*[[{")
        for name in ("title", "author", "date", "keywords"):
            specs[name] = MacroSpec(name, args_parser="[{")
        specs['bibitem'] = MacroSpec('bibitem', args_parser='[{')
        for name in ("label", "lean"):
            specs[name] = MacroSpec(name, args_parser="{")
        for name in ("leanok", "mathlibok", "notready"):
            specs[name] = MacroSpec(name, args_parser="")
        for name in ("input", "include"):
            specs[name] = MacroSpec(name, args_parser=_InputParser())
        specs["newtheorem"] = MacroSpec("newtheorem", args_parser=_OpaqueDeclarationParser("*{[{["))
        for name in _COMMAND_DECLARATIONS:
            specs[name] = MacroSpec(name, args_parser=_OpaqueDeclarationParser("*{[[{"))
        for name in ("newenvironment", "renewenvironment"):
            specs[name] = MacroSpec(name, args_parser=_OpaqueDeclarationParser("*{[[{{"))
        for name in _PRIMITIVE_DEFINITIONS:
            specs[name] = MacroSpec(name, args_parser=_PrimitiveDefinitionParser())
        specs["DeclareMathOperator"] = MacroSpec("DeclareMathOperator", args_parser=_OpaqueDeclarationParser("*{{"))
        for name in sorted(_LINK_MACROS):
            specs.setdefault(name, MacroSpec(name, args_parser=_LinkArgsParser(with_text=name == "href")))
        for name in ("verb", "lstinline"):
            specs[name] = MacroSpec(name, args_parser=_InlineLiteralParser(name))
        specs["mintinline"] = MacroSpec("mintinline", args_parser=_OpaqueDeclarationParser("[{{"))
        specs["includegraphics"] = MacroSpec("includegraphics", args_parser="*[{")
        specs["bibliography"] = MacroSpec("bibliography", args_parser="{")
        specs["addbibresource"] = MacroSpec("addbibresource", args_parser="[{")
        specs["includeonly"] = MacroSpec("includeonly", args_parser="{")
        specs["caption"] = MacroSpec("caption", args_parser="*[{")
        specs["graphicspath"] = MacroSpec("graphicspath", args_parser="{")
        specs["newif"] = MacroSpec("newif", args_parser="{")
        envs = []
        for name, kind in self.environment_map.items():
            variants = [name] if name.endswith("*") else [name, name + "*"]
            for variant in variants:
                if kind == "equation":
                    argspec = "{" if variant.rstrip("*") == "alignat" else ""
                    envs.append(EnvironmentSpec(variant, args_parser=argspec, is_math_mode=True))
                else:
                    envs.append(EnvironmentSpec(variant, args_parser="["))
        envs.extend(EnvironmentSpec(name, args_parser=_LiteralEnvironmentParser(name))
                    for name in sorted(_LITERAL_ENVIRONMENTS))
        context.add_context_category("qecgraph", macros=list(specs.values()),
                                     environments=envs, prepend=True)
        self._applied_context = {'environments': dict(self.environment_map), 'macro_specs': dict(self.macro_specs)}
        return context

    def parse_nodes(self, path: str):
        phase('Parsing LaTeX source', detail=path)
        text, aliases = self.structures[path]
        key = None
        if self.node_cache:
            # Discovery can learn declarations while still using the original walker context.
            key = self.node_cache.key(path, text, {**self._applied_context,
                                                  'conditionals': sorted(self._conditional_names),
                                                  'aliases': sorted(aliases.items())})
            cached = self.node_cache.get(key, text)
            if cached is not None:
                return cached
        try:
            nodes, _, _ = _StructuralWalker(text, aliases, latex_context=self.context,
                                            tolerant_parsing=False).get_latex_nodes()
            if self.node_cache:
                self.node_cache.put(key, nodes)
            return nodes
        except (LatexWalkerParseError, IndexError) as exc:
            pos = max(0, min(getattr(exc, "pos", 0) or 0, len(text)))
            self.diagnostic("error", "latex_parse_error", str(exc), self.span(path, pos, pos))
            return []

    def resolve(self, literal: str, current: str, *, kind: str, source):
        literal = literal.strip()
        if not literal or any(x in literal for x in ("\\", "#", "\x00")):
            self.diagnostic("warning", "dynamic_path", f"Unexpanded {kind} path: {literal!r}", source)
            return None
        name = Path(literal)
        if kind == "include" and not name.suffix:
            name = name.with_suffix(".tex")
        if kind == "include" and name.suffix.lower() != ".tex":
            self.diagnostic("warning", "unsupported_include_type", f"Only .tex includes are read: {literal}", source)
            return None
        if kind == "bibliography" and not name.suffix:
            name = name.with_suffix(".bib")
        candidates = [self.root / name, (self.root / current).parent / name]
        if self.config.get("include_resolution") == "file_first":
            candidates.reverse()
        resolved = []
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate not in resolved:
                resolved.append(candidate)
        if any(not candidate.is_relative_to(self.root) for candidate in resolved):
            self.diagnostic("error" if kind == "include" else "warning", "path_outside_project",
                            f"Rejected {kind} path outside project_root: {literal}", source)
            return None
        expanded = []
        for candidate in resolved:
            expanded.append(candidate)
            if kind == "graphic" and not candidate.suffix:
                expanded.extend(candidate.with_suffix(ext) for ext in
                                (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg", ".webp"))
        existing = [p for p in expanded if p.is_file()]
        if not existing:
            self.diagnostic("error" if kind == "include" else "warning",
                            "missing_include" if kind == "include" else "missing_resource",
                            f"Could not resolve {kind}: {literal}", source)
            return None
        chosen = existing[0]
        if kind == "include" and len(existing) > 1:
            self.diagnostic("warning", "ambiguous_include_path",
                            f"Several include paths exist; selected {self.relative(chosen)}", source)
        if kind == "include" and chosen != resolved[0]:
            self.diagnostic("warning", "include_relative_fallback",
                            f"Include resolved relative to its containing file: {self.relative(chosen)}", source)
        return self.relative(chosen)

    def discover(self, path: Path, source=None, *, inherited=None):
        rel = self.relative(path)
        if rel in self.discovery_stack:
            self.diagnostic("error", "include_cycle", "Include cycle: " + " -> ".join(self.discovery_stack + [rel]), source)
            return
        if rel in self.discovered:
            self.diagnostic("warning", "duplicate_include", f"Repeated include is not expanded twice: {rel}", source)
            return
        self.discovered.add(rel)
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            self.diagnostic("error", "unsupported_source_encoding",
                            f"Non-UTF-8 source {rel}; preserve the archive and provide an explicit encoding migration.", source)
            return
        except OSError as exc:
            self.diagnostic("error", "source_read_error", f"Cannot read UTF-8 source {rel}: {exc}", source)
            return
        self.files[rel] = {"path": rel, "sha256": sha256(raw).hexdigest(), "text": text, "encoding": "utf-8"}
        self.source_lines[rel] = SourceLines(text)
        try:
            projected, aliases, include_bindings, selected = _scan_structure(
                text, inherited or {}, self.context, self._conditional_names
            )
        except (LatexWalkerParseError, LatexWalkerEndOfStream, IndexError) as exc:
            pos = max(0, min(getattr(exc, "pos", 0) or 0, len(text)))
            self.diagnostic("error", "structural_scan_incomplete",
                            "Static LaTeX structure recognition failed; parsing the original token stream.",
                            self.span(rel, pos, pos))
            projected, aliases, include_bindings, selected = text, {}, {}, []
        self.structures[rel] = projected, aliases
        for start, end in selected:
            self.diagnostic("warning", "conditional_branch_selected",
                            "Selected a branch using literal condition syntax and visible source declarations.",
                            self.span(rel, start, end))
        self.discovery_stack.append(rel)
        nodes = self.parse_nodes(rel)

        def visit(values):
            for node in values:
                if isinstance(node, LatexMacroNode):
                    name = node.macroname
                    if name == "newtheorem":
                        self.learn_environment(node, rel)
                        continue
                    if name in _COMMAND_DECLARATIONS:
                        self.learn_macro(node, rel)
                        continue
                    if name == "newif":
                        custom_if = _last_arg(node, text).strip().lstrip("\\")
                        if custom_if:
                            self._conditional_names.add(custom_if)
                    if name in _CONDITIONALS or name in self._conditional_names:
                        self.diagnostic("warning", "conditionals_not_evaluated",
                                        "Conditional branches are indexed syntactically; the active TeX branch is not evaluated.",
                                        self.node_span(rel, node))
                    if name in {"includeonly", "graphicspath"}:
                        self.diagnostic("warning", "tex_configuration_not_applied",
                                        f"\\{name} is preserved but not applied by this source parser.", self.node_span(rel, node))
                    if name in {"def", "gdef", "edef", "xdef", "newenvironment", "renewenvironment"}:
                        self.diagnostic("warning", "macro_expansion_not_performed",
                                        f"\\{name} is preserved; its expansion is not executed.", self.node_span(rel, node))
                    if name in {"input", "include"}:
                        literal = _last_arg(node, text)
                        span = self.node_span(rel, node)
                        target = self.resolve(literal, rel, kind="include", source=span)
                        self.include_targets[(rel, node.pos)] = target
                        self.includes.append({"from": rel, "to": target, "literal": literal, "source": span})
                        if target is not None:
                            self.discover(self.root / target, span, inherited=include_bindings.get(node.pos))
                        continue
                visit(_children(node))

        visit(nodes)
        self.discovery_stack.pop()

    def learn_environment(self, node, path):
        args = _args(node)
        if len(args) < 4:
            return
        text = self.files[path]["text"]
        name = _raw_arg(args[1], text).strip()
        heading = _raw_arg(args[3], text).strip()
        if not name or name in self.explicit_environments:
            return
        normalized = re.sub(r"[^a-z]", "", heading.lower())
        mapping = {"definition": "definition", "lemma": "lemma", "theorem": "theorem",
                   "proposition": "proposition", "corollary": "corollary", "conjecture": "conjecture",
                   "remark": "remark", "example": "example", "proof": "proof"}
        kind = mapping.get(normalized) or _ENVIRONMENTS.get(normalized) or _ENVIRONMENTS.get(name.rstrip("*"))
        if kind is None:
            for word, translated in (("定义", "definition"), ("引理", "lemma"), ("定理", "theorem"),
                                     ("命题", "proposition"), ("推论", "corollary"), ("猜想", "conjecture"),
                                     ("注", "remark"), ("例", "example")):
                if heading.startswith(word):
                    kind = translated
                    break
        if kind is None:
            kind = "statement_other"
            self.diagnostic("warning", "unclassified_theorem_environment",
                            f"Environment {name!r}, heading {heading!r}, is kept as statement_other; configure environment_map to classify it.",
                            self.node_span(path, node))
        previous = self.environment_map.get(name)
        if previous is not None and previous != kind:
            self.diagnostic("warning", "environment_redefinition",
                            f"Conflicting environment kind for {name}; using the latest declaration ({kind}).",
                            self.node_span(path, node))
        self.environment_map[name] = kind
        self.environment_headings[name] = heading

    def learn_macro(self, node, path):
        args = _args(node)
        if len(args) < 5:
            return
        text = self.files[path]["text"]
        name = _raw_arg(args[1], text).strip().lstrip("\\")
        if not re.fullmatch(r"[A-Za-z@]+", name):
            return
        # Generated bibliographies often provide zero-argument URL shims
        # that delegate to another command after changing URL catcodes.
        if name in _LINK_MACROS and node.macroname == "providecommand":
            return
        try:
            number = int(_raw_arg(args[2], text)) if args[2] is not None else 0
        except ValueError:
            return
        if not 0 <= number <= 9:
            return
        self.macro_specs[name] = ("[" + "{" * (number - 1)) if args[3] is not None and number else "{" * number

    def make_block(self, kind, path, start, end, parent_key=None, environment=None, title_tex=""):
        key = "block-" + str(len(self.blocks) + 1)
        block = {"key": key, "kind": kind, "environment": environment, "title_tex": title_tex,
                 "source": self.span(path, start, end), "latex": self.files[path]["text"][start:end],
                 "parent_key": parent_key, "labels": [], "references": [], "lean_declarations": [],
                 "leanok_declared": False, "order": len(self.blocks)}
        self.blocks.append(block)
        self.by_key[key] = block
        return block

    def kind_of_environment(self, name):
        return self.environment_map.get(name) or self.environment_map.get(name.rstrip("*"))

    @staticmethod
    def parent(owner, sections):
        return owner if owner is not None else (sections[-1][1] if sections else None)

    def metadata(self, node, path, owner, sections):
        """Inspect an AST node; nested extracted blocks get their own metadata."""
        text = self.files[path]["text"]
        if isinstance(node, LatexCommentNode):
            return
        if isinstance(node, LatexEnvironmentNode):
            if node.environmentname in _LITERAL_ENVIRONMENTS:
                return
            if self.kind_of_environment(node.environmentname):
                self.emit_environment(node, path, owner, sections)
                return
        if isinstance(node, LatexMathNode) and node.displaytype == "display":
            self.emit_math(node, path, owner, sections)
            return
        if isinstance(node, LatexMacroNode):
            name = node.macroname
            if name in _DECLARATIONS | _LITERAL_MACROS:
                return
            if name in {"input", "include"}:
                target = self.include_targets.get((path, node.pos))
                if target in self.files:
                    self.emit_file(target, owner, sections, body=True)
                return
            block = self.by_key.get(owner)
            if name == "label" and block is not None:
                label = _last_arg(node, text).strip()
                if label and label not in block["labels"]:
                    block["labels"].append(label)
                return
            if name in set(_REFERENCE_KINDS) | _CITATIONS:
                targets = [x.strip() for x in _last_arg(node, text).split(",") if x.strip()]
                if block is not None and targets:
                    block["references"].append({"kind": "cite" if name in _CITATIONS else _REFERENCE_KINDS[name],
                                                "targets": targets, "source": self.node_span(path, node), "macro": name})
                return
            if name == "lean" and block is not None:
                for declaration in _last_arg(node, text).split(","):
                    declaration = declaration.strip()
                    if declaration and declaration not in block["lean_declarations"]:
                        block["lean_declarations"].append(declaration)
                return
            if name in {"leanok", "mathlibok"} and block is not None:
                block["leanok_declared"] = True
                return
            if name == "notready" and block is not None:
                block["notready_declared"] = True
                return
            if name in {"includegraphics", "bibliography", "addbibresource"}:
                kind = "graphic" if name == "includegraphics" else "bibliography"
                literals = [_last_arg(node, text)]
                if name == "bibliography":
                    literals = literals[0].split(",")
                for literal in literals:
                    span = self.node_span(path, node)
                    target = self.resolve(literal, path, kind=kind, source=span)
                    self.resources.append({"kind": kind, "literal": literal.strip(), "path": target,
                                           "source": span, "block_key": owner})
                return
            if name == "caption" and block is not None and block["kind"] in {"table", "figure", "algorithm"}:
                if not block["title_tex"]:
                    block["title_tex"] = _last_arg(node, text)
        for child in _children(node):
            self.metadata(child, path, owner, sections)

    def emit_environment(self, node, path, parent, sections):
        kind = self.kind_of_environment(node.environmentname)
        args = _args(node)
        title = ""
        if kind not in {"equation", "table", "figure"} and args and args[0] is not None:
            title = _raw_arg(args[0], self.files[path]["text"])
        block = self.make_block(kind, path, node.pos, node.pos + node.len, parent,
                                node.environmentname, title)
        block["heading"] = self.environment_headings.get(node.environmentname)
        for arg in args:
            if arg is not None:
                self.metadata(arg, path, block["key"], sections)
        self.process(node.nodelist or [], path, block["key"], list(sections), body=True)
        return block["key"]

    def emit_math(self, node, path, parent, sections):
        block = self.make_block("equation", path, node.pos, node.pos + node.len,
                                parent, "display_math")
        for child in node.nodelist or []:
            self.metadata(child, path, block["key"], sections)
        return block["key"]

    def emit_bibliography_entries(self, node, path, parent, sections):
        children = node.nodelist or []
        entries = [(i, child) for i, child in enumerate(children)
                   if isinstance(child, LatexMacroNode) and child.macroname == 'bibitem']
        text = self.files[path]['text']
        for index, (offset, item) in enumerate(entries):
            stop = entries[index + 1][1].pos if index + 1 < len(entries) else (
                children[-1].pos + children[-1].len)
            key = _last_arg(item, text).strip()
            block = self.make_block('bib_entry', path, item.pos, stop, parent, title_tex=key)
            block.update(source_role='bibliography', bibliography_key=key)
            last = entries[index + 1][0] if index + 1 < len(entries) else len(children)
            for child in children[offset:last]:
                self.metadata(child, path, block['key'], sections)

    def emit_section(self, node, path, owner, sections, text):
        level = _SECTIONS[node.macroname]
        while sections and sections[-1][0] >= level:
            sections.pop()
        block = self.make_block("section", path, node.pos, node.pos + node.len, self.parent(owner, sections),
                                None, _last_arg(node, text))
        block["section_level"] = level
        sections.append((level, block["key"]))
        for arg in _args(node):
            if arg is not None:
                self.metadata(arg, path, block["key"], sections)
        return block["key"]

    def extend_section_span(self, target, path, stop, text):
        block = self.by_key[target]
        source = block["source"]
        # A label following a heading belongs to that heading. Include its
        # exact source in the heading's span for reliable citation.
        if block["kind"] == "section" and source["path"] == path and source["char_end"] <= stop:
            block["source"] = self.span(path, source["char_start"], stop)
            block["latex"] = text[source["char_start"]:stop]

    def process(self, nodes, path, owner, sections, *, body=True):
        text = self.files[path]["text"]
        buffer = []
        begin = end = None
        meaningful = False
        last_anchor = self.parent(owner, sections)

        def append(node, start, stop):
            nonlocal begin, end, meaningful
            if start >= stop:
                return
            begin = start if begin is None else begin
            end = stop
            if isinstance(node, LatexCharsNode):
                meaningful = meaningful or bool(node.chars[start - node.pos:stop - node.pos].strip())
            else:
                buffer.append(node)
                if not isinstance(node, LatexCommentNode):
                    meaningful = meaningful or not (isinstance(node, LatexMacroNode) and node.macroname in _METADATA_MACROS)

        def flush():
            nonlocal buffer, begin, end, meaningful, last_anchor
            if begin is None:
                return
            target = last_anchor or self.parent(owner, sections)
            if meaningful:
                block = self.make_block("paragraph", path, begin, end, self.parent(owner, sections))
                target = block["key"]
                last_anchor = target
            elif target is not None and buffer:
                self.extend_section_span(target, path, end, text)
            for buffered in buffer:
                self.metadata(buffered, path, target, sections)
            buffer, begin, end, meaningful = [], None, None, False

        for node in nodes:
            if isinstance(node, LatexMacroNode) and node.macroname in _DECLARATIONS:
                flush()
                continue
            if isinstance(node, LatexEnvironmentNode) and node.environmentname == "document":
                flush()
                self.process(node.nodelist or [], path, owner, sections, body=True)
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in {"input", "include"}:
                flush()
                target = self.include_targets.get((path, node.pos))
                if target in self.files:
                    self.emit_file(target, owner, sections, body=body)
                last_anchor = self.parent(owner, sections)
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in {'title', 'author'}:
                flush()
                self.make_block('title' if node.macroname == 'title' else 'author_block',
                                path, node.pos, node.pos + node.len, self.parent(owner, sections),
                                title_tex=_last_arg(node, text))
                continue
            if not body:
                # Preserve preamble in files, but do not turn declarations or
                # package metadata into mathematical paragraphs.
                if isinstance(node, LatexMacroNode) and node.macroname in {"bibliography", "addbibresource"}:
                    self.metadata(node, path, owner, sections)
                continue
            if (owner is None and isinstance(node, LatexMacroNode)
                    and node.macroname in _METADATA_MACROS and not meaningful
                    and last_anchor is not None):
                flush()
                self.metadata(node, path, last_anchor, sections)
                self.extend_section_span(last_anchor, path, node.pos + node.len, text)
                continue
            if isinstance(node, LatexMacroNode) and node.macroname in _SECTIONS:
                flush()
                last_anchor = self.emit_section(node, path, owner, sections, text)
                continue
            if isinstance(node, LatexEnvironmentNode) and node.environmentname == "thebibliography":
                flush()
                if self.kind_of_environment(node.environmentname):
                    last_anchor = self.emit_environment(node, path, self.parent(owner, sections), sections)
                    block = self.by_key[last_anchor]
                else:
                    block = self.make_block("paragraph", path, node.pos, node.pos + node.len,
                                            self.parent(owner, sections), node.environmentname)
                    last_anchor = block["key"]
                    self.metadata(node, path, last_anchor, sections)
                block["source_role"] = "bibliography"
                self.emit_bibliography_entries(node, path, block['key'], sections)
                continue
            if isinstance(node, LatexEnvironmentNode) and self.kind_of_environment(node.environmentname):
                flush()
                last_anchor = self.emit_environment(node, path, self.parent(owner, sections), sections)
                continue
            if isinstance(node, LatexMathNode) and node.displaytype == "display":
                flush()
                last_anchor = self.emit_math(node, path, self.parent(owner, sections), sections)
                continue
            if isinstance(node, LatexEnvironmentNode) and node.environmentname == "comment":
                continue
            if owner is not None:
                self.metadata(node, path, owner, sections)
            elif isinstance(node, LatexCharsNode):
                position = node.pos
                for match in re.finditer(r"\r?\n[\t \r]*\n", node.chars):
                    stop = node.pos + match.end()
                    append(node, position, stop)
                    flush()
                    position = stop
                append(node, position, node.pos + node.len)
            else:
                append(node, node.pos, node.pos + node.len)
        flush()

    def emit_file(self, path, owner, sections, *, body=True):
        if path in self.emitted:
            return
        self.emitted.add(path)
        nodes = self.parse_nodes(path)
        has_document = any(isinstance(node, LatexEnvironmentNode) and node.environmentname == "document"
                           for node in nodes)
        self.process(nodes, path, owner, sections, body=False if has_document else body)

    def run(self):
        self.discover(self.entry)
        self.context = self._context()
        entry = self.relative(self.entry)
        if entry in self.files:
            self.emit_file(entry, None, [], body=True)
        if self.macro_specs:
            self.diagnostic("warning", "custom_macros_not_expanded",
                            "Literal environment aliases and macro argument shapes are recognized; arbitrary macro bodies are not expanded.")
        return {"entry": entry, "files": [self.files[name] for name in sorted(self.files)],
                "blocks": self.blocks, "includes": self.includes, "resources": self.resources,
                "diagnostics": self.diagnostics, "parser": "pylatexenc",
                "parser_version": PYLATEXENC_VERSION, "extractor_version": PARSER_VERSION,
                "offset_convention": "UTF-8 decoded Unicode codepoints; half-open [start,end); line numbers 1-based",
                "environment_map": dict(sorted(self.environment_map.items()))}


def parse_project(entry: str | Path, project_root: str | Path | None = None,
                  config: dict | None = None, *, node_cache=None) -> dict:
    """Parse a UTF-8 LaTeX project without executing it.

    ``environment_map`` in config can map custom environment names to supported
    kinds.  Includes resolve relative to ``project_root`` first, then relative
    to the containing file; ``include_resolution='file_first'`` reverses this.
    Repeated included files are represented once and diagnosed.  Unsupported
    Macro expansion and conditional execution beyond static structural cases
    are reported rather than guessed.
    """
    entry = Path(entry).expanduser().resolve()
    root = Path(project_root).expanduser().resolve() if project_root is not None else entry.parent
    if not entry.is_file():
        raise ValueError(f"LaTeX entry file does not exist: {entry}")
    return _ProjectParser(entry, root, config or {}, node_cache=node_cache).run()
