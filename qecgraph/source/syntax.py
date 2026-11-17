"""Shared lossless TeX declaration grammar; replacement bodies stay opaque."""

from pylatexenc.latexwalker import (
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


def declaration_context():
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
    specs += [MacroSpec(n, args_parser="*[[{") for n in sorted(CITATION_COMMANDS)]
    specs += [
        MacroSpec(n, args_parser="*{")
        for n in ("label", "ref", "eqref", "pageref", "autoref", "cref", "Cref")
    ]
    context.add_context_category("material-declarations", macros=specs, prepend=True)
    return context
