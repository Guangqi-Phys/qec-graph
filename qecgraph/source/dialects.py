"""Literal Harvmac-to-LaTeX syntax conversion; math and prose are copied verbatim."""

from __future__ import annotations
import re
from .assembly import (
    LITERAL_ENVIRONMENTS,
    _DECLARATIONS,
    _read_group,
    _skip_definition,
    _skip_space,
)


def _syntax(text):
    """Mask comments and declaration bodies without changing offsets."""
    chars = list(text)
    cursor = 0
    token = re.compile(r"%|\\([A-Za-z@]+)|\\[^A-Za-z@]")
    while match := token.search(text, cursor):
        if match[0] == "%":
            stop = text.find("\n", match.start())
            stop = len(text) if stop < 0 else stop
        elif match[1] is None:
            stop = match.end()
        elif match[1] in _DECLARATIONS:
            stop = _skip_definition(text, match.end(), match[1])
        else:
            cursor = match.end()
            continue
        chars[match.start() : stop] = [
            "\n" if c == "\n" else " " for c in text[match.start() : stop]
        ]
        cursor = stop
    return "".join(chars)


_ALIAS_DECLARATION = re.compile(
    r"\s*\{\s*\\([A-Za-z@]+)\s*\}\s*\{\s*\\([A-Za-z@]+)\s*\}\s*"
)
_DECLARATION_TARGETS = {
    "newcommand",
    "renewcommand",
    "providecommand",
    "DeclareRobustCommand",
}


def _literal_end(text, match):
    if match[0] == "%":
        end = text.find("\n", match.end())
        return len(text) if end < 0 else end
    if match[1] == "begin":
        environment, after = _read_group(text, _skip_space(text, match.end()))
        if environment in LITERAL_ENVIRONMENTS:
            closing = "\\end{" + environment + "}"
            end = text.find(closing, after)
            if end < 0:
                raise ValueError(
                    "Unclosed literal environment in declaration conversion"
                )
            return end + len(closing)
    if match[1] == "verb" and match.end() < len(text):
        end = text.find(text[match.end()], match.end() + 1)
        if end < 0:
            raise ValueError("Unclosed inline literal in declaration conversion")
        return end + 1
    return None


def _learn_declaration_alias(text, match, stop, target, aliases, conditional):
    definition = _ALIAS_DECLARATION.fullmatch(text[match.end() : stop])
    if (
        definition
        and definition[2] in _DECLARATION_TARGETS
        and not (target == "providecommand" and definition[1] in aliases)
    ):
        if conditional:
            raise ValueError("Conditional declaration aliases require review")
        aliases[definition[1]] = definition[2]
    elif not (target == "providecommand" and definition and definition[1] in aliases):
        declared = re.match(r"\s*\{?\s*\\([A-Za-z@]+)", text[match.end() : stop])
        if declared:
            aliases.pop(declared[1], None)


def declaration_alias_edits(text):
    """Normalize literal zero-argument declaration aliases, never math macros."""
    aliases, changes, scopes = {}, [], []
    conditional = False
    token = re.compile(r"%|\\([A-Za-z@]+)|\\[^A-Za-z@]|[{}]")
    cursor = 0
    while match := token.search(text, cursor):
        name = match[1]
        literal_end = _literal_end(text, match)
        if literal_end is not None:
            cursor = literal_end
            continue
        if match[0] == "{" or name == "begingroup":
            scopes.append(dict(aliases))
        elif match[0] == "}" or name == "endgroup":
            aliases = scopes.pop() if scopes else {}
        elif name and (
            name.startswith("if") or name in {"else", "fi", "input", "include"}
        ):
            conditional = True
            if aliases:
                raise ValueError(
                    "Declaration alias conversion requires a literal local context"
                )
        target = aliases.get(name, name)
        if target in _DECLARATION_TARGETS:
            stop = _skip_definition(text, match.end(), target)
            if name in aliases:
                changes.append(
                    (
                        match.start(),
                        match.end(),
                        {
                            "old": match[0],
                            "new": "\\" + target,
                            "evidence": text[match.start() : stop],
                            "reason": "Normalize a literal zero-argument declaration alias; preserve its arguments.",
                            "conversion": "declaration_alias",
                        },
                    )
                )
            _learn_declaration_alias(text, match, stop, target, aliases, conditional)
            cursor = stop
        elif name in _DECLARATIONS:
            cursor = _skip_definition(text, match.end(), name)
        else:
            cursor = match.end()
    return changes


def harvmac_edits(text):
    """Return fixed grammar substitutions, never generated source content."""
    syntax = _syntax(text)
    if not re.search(r"\\input\s+(?:\{harvmac(?:\.tex)?\}|harvmac\b)", syntax):
        raise ValueError("Harvmac conversion requires a literal harvmac input")
    if re.search(r"\\begin\s*\{document\}", syntax):
        raise ValueError("Harvmac conversion cannot wrap an existing LaTeX document")
    title = re.search(r"\\Title\s*\{", syntax)
    if title is None:
        raise ValueError("Harvmac conversion requires a literal Title boundary")
    changes = []

    def add(a, b, new, reason):
        changes.append(
            (
                a,
                b,
                {
                    "old": text[a:b],
                    "new": new,
                    "evidence": text[a:b],
                    "reason": reason,
                    "conversion": "harvmac",
                },
            )
        )

    add(
        0,
        0,
        "\\documentclass{article}\n",
        "Provide the standard parser document wrapper.",
    )
    add(
        title.start(),
        title.start(),
        "\\begin{document}\n",
        "Start the body at the existing title.",
    )
    terminal = list(re.finditer(r"(?m)^\\(?:end|bye)\s*$", syntax))
    if terminal:
        end = terminal[-1]
        add(
            end.start(),
            end.end(),
            "\\end{document}\n",
            "Normalize the plain-TeX terminator.",
        )
    else:
        add(
            len(text),
            len(text),
            "\n\\end{document}\n",
            "Close the standard document wrapper.",
        )
    for match in re.finditer(r"\\(newsec|subsec)(?![A-Za-z@])", syntax):
        add(
            match.start(),
            match.end(),
            "\\section" if match[1] == "newsec" else "\\subsection",
            "Normalize a section command; keep its original title argument.",
        )
    _harvmac_equations(text, syntax, add)
    return changes


def _harvmac_equations(text, syntax, add):
    headers = []
    labels = set()
    for match in re.finditer(r"\\eqn\s*\\([A-Za-z@]+)\s*\{", syntax):
        _, end = _read_group(text, match.end() - 1)
        if end <= match.end() or text[end - 1] != "}":
            raise ValueError("Unclosed Harvmac equation argument")
        label = match[1]
        labels.add(label)
        headers.append((match.start(), match.end()))
        add(
            match.start(),
            match.end(),
            "\\begin{equation}\\label{" + label + "}",
            "Normalize the equation wrapper; copy the formula argument verbatim.",
        )
        add(end - 1, end, "\\end{equation}", "Close the normalized equation wrapper.")
    for label in labels:
        for match in re.finditer(r"\\" + re.escape(label) + r"(?![A-Za-z@])", syntax):
            if not any(a <= match.start() < b for a, b in headers):
                add(
                    match.start(),
                    match.end(),
                    "\\ref{" + label + "}",
                    "Normalize the reference to the existing Harvmac equation label.",
                )
