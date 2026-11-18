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
    return declaration_options(tree, paths, rule_version=None)[0]


def declaration_options(tree, paths, *, rule_version):
    records, bodies, package_loads = _scan_declarations(tree, paths)
    if rule_version == "compile-prepare-v19":
        # Both policies were published with v19. Verify each historical result
        # against its own literal grammar before accepting either representation.
        return tuple(
            _legacy_declarations(records, bodies, extended)
            for extended in (True, False)
        )
    if rule_version in {f"compile-prepare-v{v}" for v in range(1, 19)}:
        return (_legacy_declarations(records, bodies, False),)
    if _is_shadowed("newtcolorbox", bodies, package_loads):
        return ([],)
    return (_unique_declarations(records, lambda r: _environment_shadowed(r, bodies)),)


def _scan_declarations(tree, paths):
    records, bodies, package_loads = [], {}, {}
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
        bodies[path] = masked
        # The parser only recognizes the literal control words. A file without
        # the candidate bytes cannot contribute a declaration, and full
        # pylatexenc parsing of every consumed style file dominates read time.
        if "newtcolorbox" in masked:
            found, package_load = _source_declarations(path, tree.files[path], text)
            records.extend(found)
            if package_load is not None:
                package_loads[path] = package_load
    return records, bodies, package_loads


def _unique_declarations(records, shadowed):
    counts = Counter(row["environment"] for row in records)
    return [r for r in records if counts[r["environment"]] == 1 and not shadowed(r)]


def _legacy_declarations(records, bodies, extended):
    source = "\n".join(bodies.values())
    if _shadow_patterns("newtcolorbox", extended).search(source):
        return []
    return _unique_declarations(
        records, lambda r: _shadow_patterns(r["environment"], extended).search(source)
    )


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
        return [], None
    inactive, uncertain = condition_regions(text)
    body = document_bounds(text)[1]
    result, package_load = [], None
    for node in nodes:
        if not isinstance(node, LatexMacroNode):
            continue
        position = cast(int, node.pos)
        if any(a <= position < b for a, b in [*inactive, *uncertain]) or (
            body is not None and position >= body
        ):
            continue
        if node.macroname in {"newtcolorbox", "renewtcolorbox"}:
            record = _declaration(node, path, raw, text)
            if record:
                result.append(record)
        elif package_load is None and _loads_tcolorbox(node, text):
            package_load = position + cast(int, node.len)
    return result, package_load


def _loads_tcolorbox(node, text):
    if node.macroname not in {"usepackage", "RequirePackage"}:
        return False
    args = getattr(node.nodeargd, "argnlist", None) or []
    for arg in args:
        if arg and text[arg.pos] == "{":
            packages = text[arg.pos + 1 : arg.pos + arg.len - 1].split(",")
            return any(package.strip() == "tcolorbox" for package in packages)
    return False


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


def _shadow_patterns(name, extended=True):
    escaped = re.escape(name)
    literal = (
        r"\\(?:def|gdef|edef|xdef|let)\s*\\(?:end)?"
        + escaped
        + r"(?![A-Za-z@])"
        + r"|\\(?:newenvironment|renewenvironment|NewDocumentEnvironment|RenewDocumentEnvironment)\*?\s*\{"
        + escaped
        + r"\}"
    )
    if extended:
        target = r"\*?\s*\{?\s*\\" + escaped + r"(?![A-Za-z@])"
        literal += (
            r"|\\(?:newcommand|renewcommand|DeclareRobustCommand|(?:New|Renew|Declare)DocumentCommand)"
            + target
            + r"|\\(?P<provide>providecommand|ProvideDocumentCommand)"
            + target
        )
    return re.compile(literal)


def _environment_shadowed(record, bodies):
    origin = record["origin"]
    defined = (
        {origin["path"]: origin["chars"][1]}
        if record["command"] == "newtcolorbox"
        else {}
    )
    return _is_shadowed(record["environment"], bodies, defined)


def _is_shadowed(name, bodies, defined):
    pattern = _shadow_patterns(name)
    for path, text in bodies.items():
        start = defined.get(path)
        for match in pattern.finditer(text):
            if not match["provide"] or start is None or match.start() < start:
                return True
    return False
