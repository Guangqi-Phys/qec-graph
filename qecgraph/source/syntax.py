"""Shared lossless TeX declaration grammar; replacement bodies stay opaque."""

import re

from pylatexenc.latexwalker import (
    LatexWalker,
    LatexMacroNode,
    LatexWalkerEndOfStream,
    LatexWalkerParseError,
    LatexCharsNode,
    LatexGroupNode,
    get_default_latex_context_db,
)
from pylatexenc.macrospec import MacroStandardArgsParser, ParsedMacroArgs, MacroSpec

CITATION_COMMANDS = frozenset(
    {
        "cite",
        "citep",
        "citet",
        "citealt",
        "citealp",
        "autocite",
        "parencite",
        "textcite",
        "footcite",
        "nocite",
        "onlinecite",
        "citenum",
    }
)


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
            raise LatexWalkerParseError(
                s=w.s, pos=pos, msg="Unclosed declaration argument"
            )
        character = (
            token.arg if token.tok in {"char", "brace_open", "brace_close"} else None
        )
        if character == "{":
            stack.append("{")
        elif opening == "[" and character == "[" and stack[-1] == "[":
            stack.append("[")
        elif character == "}" and stack[-1] == "{":
            stack.pop()
        elif character == "]" and stack[-1] == "[":
            stack.pop()
        current = token.pos + token.len
    content = w.make_node(
        LatexCharsNode,
        parsing_state=parsing_state,
        pos=pos + 1,
        len=token.pos - pos - 1,
        chars=w.s[pos + 1 : token.pos],
    )
    return w.make_node(
        LatexGroupNode,
        parsing_state=parsing_state,
        pos=pos,
        len=current - pos,
        nodelist=[content],
        delimiters=(opening, closing),
    ), current


class _OpaqueDeclarationParser(MacroStandardArgsParser):
    """Parse declaration arguments without treating their bodies as a document."""

    def parse_args(self, w, pos, parsing_state=None):
        original = pos
        args = []
        for expected in self.argspec:
            token = _next_token(w, pos, parsing_state)
            if expected == "*":
                if token is not None and token.tok == "char" and token.arg == "*":
                    args.append(
                        w.make_node(
                            LatexCharsNode,
                            parsing_state=parsing_state,
                            pos=token.pos,
                            len=token.len,
                            chars="*",
                        )
                    )
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
                    raise LatexWalkerParseError(
                        s=w.s, pos=pos, msg="Missing declaration argument"
                    )
                if token.tok == "brace_open":
                    group, pos = _opaque_group(w, token.pos, "{", "}", parsing_state)
                    args.append(group)
                else:
                    node, start, length = w.get_latex_expression(
                        token.pos, parsing_state=parsing_state, strict_braces=True
                    )
                    args.append(node)
                    pos = start + length
        return (
            ParsedMacroArgs(argspec=self.argspec, argnlist=args),
            original,
            pos - original,
        )


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
        raise LatexWalkerParseError(
            s=w.s, pos=start, msg="Missing primitive macro definition body"
        )


def declaration_context(extra_citations=(), *, source_text=None):
    context = get_default_latex_context_db()
    specs = [
        MacroSpec(n, args_parser=_OpaqueDeclarationParser("*{[[{"))
        for n in (
            "newcommand",
            "renewcommand",
            "providecommand",
            "DeclareRobustCommand",
        )
    ]
    specs += [
        MacroSpec(n, args_parser=_PrimitiveDefinitionParser())
        for n in ("def", "gdef", "edef", "xdef")
    ]
    specs += [
        MacroSpec(n, args_parser=_OpaqueDeclarationParser("*{[[{{"))
        for n in ("newenvironment", "renewenvironment")
    ]
    specs += [
        MacroSpec("newtheorem", args_parser=_OpaqueDeclarationParser("*{[{[")),
        MacroSpec("DeclareMathOperator", args_parser=_OpaqueDeclarationParser("*{{")),
    ]
    specs += [
        MacroSpec(n, args_parser="*[[{")
        for n in sorted(CITATION_COMMANDS | set(extra_citations))
    ]
    specs += [
        MacroSpec(n, args_parser="*{")
        for n in ("label", "ref", "eqref", "pageref", "autoref", "cref", "Cref")
    ]
    context.add_context_category("material-declarations", macros=specs, prepend=True)
    if source_text is not None:
        if re.search(
            r"\\(?:usepackage|RequirePackage)(?:\[[^]]*\])?\s*\{[^}]*\bbraket\b",
            source_text,
        ):
            context.add_context_category(
                "braket-package",
                macros=[MacroSpec("braket", args_parser="{")],
                prepend=True,
            )
        learned = _literal_signatures(source_text, context)
        context.add_context_category(
            "literal-source-signatures", macros=learned, prepend=True
        )
    return context


class _SourceArgumentParser(MacroStandardArgsParser):
    def __init__(self, choices, fallback):
        super().__init__(argspec="")
        self.choices, self.fallback = choices, fallback

    def parse_args(self, w, pos, parsing_state=None):
        parser = self.fallback
        for offset, candidate in self.choices:
            if offset <= pos:
                parser = candidate
        return parser.parse_args(w, pos, parsing_state=parsing_state)


def _literal_signatures(text, context):
    aliases, profiles, fallbacks = {}, {}, {}
    known = {spec.macroname for spec in context.iter_macro_specs()}
    learned = {}
    for depth in range(4):
        nodes = _declaration_nodes(text, context)
        learned, found = _learn_specs(nodes, text, aliases, known)
        current = {
            n: [(offset, spec.args_parser.argspec) for offset, spec in choices]
            for n, choices in learned.items()
        }
        specs = _source_specs(learned, found, context, fallbacks)
        if found == aliases and current == profiles:
            break
        aliases, profiles = found, current
        context.add_context_category(
            "source-grammar-" + str(depth), macros=specs, prepend=True
        )
    return specs


def _source_specs(learned, aliases, context, fallbacks):
    specs = []
    for name, choices in {**learned, **aliases}.items():
        if name not in fallbacks:
            prior = context.get_macro_spec(name)
            fallbacks[name] = (
                prior.args_parser if prior else MacroStandardArgsParser("")
            )
        parsers = (
            [(offset, _OpaqueDeclarationParser("*{[[{")) for offset, _ in choices]
            if name in aliases
            else [(offset, s.args_parser) for offset, s in choices]
        )
        specs.append(
            MacroSpec(name, args_parser=_SourceArgumentParser(parsers, fallbacks[name]))
        )
    return specs


def _learn_specs(nodes, text, aliases, known):
    learned, found = {}, {}
    for node in nodes:
        command = node.macroname
        for offset, target in aliases.get(command, []):
            if offset <= node.pos:
                command = target
        spec = _signature(node, text, command)
        if spec is not None and (
            command != "providecommand" or spec.macroname not in known
        ):
            learned.setdefault(spec.macroname, []).append((node.pos + node.len, spec))
        alias = _declaration_alias(node, text, command)
        if alias:
            found.setdefault(alias[0], []).append((node.pos + node.len, alias[1]))
    return learned, found


def _declaration_nodes(text, context):
    from .assembly import condition_regions

    try:
        parsed = LatexWalker(
            text, latex_context=context, tolerant_parsing=True
        ).get_latex_nodes()[0]
    except (LatexWalkerParseError, ValueError, IndexError):
        return []
    inactive, uncertain = condition_regions(text)
    result = []
    for node in parsed:
        values = (
            getattr(node, "nodelist", [])
            if getattr(node, "environmentname", None) == "document"
            else [node]
        )
        result.extend(
            n
            for n in values
            if isinstance(n, LatexMacroNode)
            and not any(a <= n.pos < b for a, b in [*inactive, *uncertain])
        )
    return result


def _declaration_arguments(node, text):
    args = getattr(getattr(node, "nodeargd", None), "argnlist", None) or []
    return [text[a.pos : a.pos + a.len] if a else None for a in args]


def _declaration_alias(node, text, command):
    raw = _declaration_arguments(node, text)
    if command not in {"newcommand", "renewcommand", "providecommand"} or len(raw) != 5:
        return None
    name = re.fullmatch(r"\{?\\([A-Za-z@]+)\}?", raw[1] or "")
    target = re.fullmatch(
        r"\{\s*\\(newcommand|renewcommand|providecommand)\s*\}", raw[4] or ""
    )
    return (name[1], target[1]) if name and target and raw[2] is None else None


def _signature(node, text, command):
    raw = _declaration_arguments(node, text)
    if (
        command
        in {"newcommand", "renewcommand", "providecommand", "DeclareRobustCommand"}
        and len(raw) == 5
    ):
        name = re.fullmatch(r"\{?\\([A-Za-z@]+)\}?", raw[1] or "")
        count = (
            int(raw[2][1:-1]) if raw[2] and re.fullmatch(r"\[[0-9]\]", raw[2]) else 0
        )
        if name:
            spec = "[" + "{" * (count - 1) if raw[3] and count else "{" * count
            return MacroSpec(name[1], args_parser=spec)
    if command in {"def", "gdef", "edef", "xdef"}:
        match = re.match(
            r"\\(?:def|gdef|edef|xdef)\s*\\([A-Za-z@]+)((?:#[1-9])*)\s*\{",
            text[node.pos : node.pos + node.len],
        )
        if match and match[2] == "".join(
            "#" + str(i + 1) for i in range(len(match[2]) // 2)
        ):
            return MacroSpec(match[1], args_parser="{" * (len(match[2]) // 2))
    return None
