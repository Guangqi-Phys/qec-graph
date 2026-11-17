"""Recognize explicit option-forwarding tcolorbox declarations in consumed sources."""

from collections import Counter
from pathlib import PurePosixPath
import re
from typing import cast

from pylatexenc.latexwalker import LatexWalker, LatexMacroNode, LatexWalkerParseError
from pylatexenc.macrospec import MacroSpec

from .artifacts import SourceIndex
from .options import fields, mask_comments
from ..source.assembly import condition_regions, document_bounds
from ..source.syntax import declaration_context, _OpaqueDeclarationParser


def label_declarations(tree, paths):
    records, bodies, candidates = [], [], []
    for path in sorted(set(paths)):
        if path not in tree.files or PurePosixPath(path).suffix not in {
            ".tex",
            ".cls",
            ".sty",
        }:
            continue
        try:
            text = tree.files[path].decode()
        except UnicodeDecodeError:
            continue
        masked = mask_comments(text)
        bodies.append(masked)
        # The parser only recognizes the literal control words. A file without
        # the candidate bytes cannot contribute a declaration, and full
        # pylatexenc parsing of every consumed style file dominates read time.
        if "newtcolorbox" in masked:
            candidates.append((path, tree.files[path], text))
    for path, raw, text in candidates:
        records.extend(_source_declarations(path, raw, text))
    counts = Counter(row["environment"] for row in records)
    source = "\n".join(bodies)
    if _shadowed("newtcolorbox", source):
        return []
    return [
        r
        for r in records
        if counts[r["environment"]] == 1 and not _shadowed(r["environment"], source)
    ]


def _source_declarations(path, raw, text):
    context = declaration_context()
    context.add_context_category(
        "tcolorbox-declarations",
        macros=[
            MacroSpec(name, args_parser=_OpaqueDeclarationParser("[{[[{"))
            for name in ("newtcolorbox", "renewtcolorbox")
        ],
        prepend=True,
    )
    try:
        nodes = LatexWalker(
            text, latex_context=context, tolerant_parsing=True
        ).get_latex_nodes()[0]
    except (LatexWalkerParseError, ValueError, RecursionError):
        return []
    inactive, uncertain = condition_regions(text)
    body = document_bounds(text)[1]
    result = []
    for node in nodes:
        if not isinstance(node, LatexMacroNode) or node.macroname not in {
            "newtcolorbox",
            "renewtcolorbox",
        }:
            continue
        position = cast(int, node.pos)
        if any(a <= position < b for a, b in [*inactive, *uncertain]) or (
            body is not None and position >= body
        ):
            continue
        record = _declaration(node, path, raw, text)
        if record:
            result.append(record)
    return result


def _declaration(node, path, raw, text):
    args = getattr(node.nodeargd, "argnlist", None) or []
    if len(args) != 5:
        return None
    values = [text[a.pos : a.pos + a.len] if a else None for a in args]
    name = values[1][1:-1] if values[1] else ""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9@*_-]*", name):
        return None
    forwards = any(
        mask_comments(field).strip() == "#1"
        for _, _, field in fields((values[-1] or "")[1:-1])
    )
    return {
        "environment": name,
        "command": node.macroname,
        "supports_label_option": node.macroname == "newtcolorbox"
        and values[2] in {"[1]", "[2]", "[3]", "[4]"}
        and values[3] is not None
        and forwards,
        "origin": SourceIndex(raw).span(path, node.pos, node.pos + node.len),
        "raw_tex": text[node.pos : node.pos + node.len],
    }


def _shadowed(name, text):
    escaped = re.escape(name)
    return bool(
        re.search(
            r"\\(?:def|gdef|edef|xdef|let)\s*\\(?:end)?"
            + escaped
            + r"(?![A-Za-z@])"
            + r"|\\(?:newenvironment|renewenvironment|NewDocumentEnvironment|RenewDocumentEnvironment)\*?\s*\{"
            + escaped
            + r"\}",
            text,
        )
    )
