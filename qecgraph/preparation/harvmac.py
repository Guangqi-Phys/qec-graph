"""Source-preserving grammar for an explicitly identified native Harvmac build.

Based on the documented grammar of Harvmac by Paul Ginsparg (CC BY 3.0).
No Harvmac TeX implementation is copied; the consumed dependency hash is pinned.
"""

from dataclasses import replace
from pathlib import PurePosixPath
import re

from pylatexenc.macrospec import MacroSpec, MacroStandardArgsParser

from .artifacts import digest
from .options import mask_comments
from ..source.assembly import mask_comments_and_definitions
from ..source.syntax import declaration_context

HARVMAC_SHA256 = "65ff913ce13af190558fc07d161e90cf74f50ccd693ca95bb00dee2920535f1f"
_SIGNATURES = {
    "Title": "{{",
    "Date": "{",
    "newsec": "{",
    "subsec": "{",
    "appendix": "{{",
    "eqn": "{{",
    "eqnn": "{",
    "eqna": "{",
    "ref": "{{",
    "nref": "{{",
    "lref": "{{",
    "refs": "{",
    "foot": "{",
    "figlabel": "{",
    "seclab": "{",
    "subseclab": "{",
}
_DEFINERS = {
    "eqn",
    "eqnn",
    "eqna",
    "ref",
    "nref",
    "lref",
    "figlabel",
    "seclab",
    "subseclab",
}


def literal_input(text):
    return bool(
        re.search(
            r"\\input\s*(?:\{harvmac(?:\.tex)?\}|harvmac(?:\.tex)?\b)",
            mask_comments_and_definitions(text),
        )
    )


def identify(build, tree):
    if build.engine not in {"etex", "pdftex"} or not literal_input(
        tree.files[build.entry].decode()
    ):
        return None
    deps = [
        d for d in build.dependencies if PurePosixPath(d["path"]).name == "harvmac.tex"
    ]
    deps += [
        {"path": p, "sha256": digest(tree.files[p])}
        for p in build.inputs
        if PurePosixPath(p).name == "harvmac.tex" and p in tree.files
    ]
    supported = [d for d in deps if d["sha256"] == HARVMAC_SHA256]
    if not supported or len(supported) != len(deps):
        return None
    if any(
        _unsafe_definitions(tree.files[p].decode())
        for p in build.inputs
        if p in tree.files
        and PurePosixPath(p).name != "harvmac.tex"
        and PurePosixPath(p).suffix.lower() in {"", ".tex"}
    ):
        return None
    return {"name": "harvmac", "grammar_version": 1, "dependency": supported[0]}


def _shadowed(text):
    names = "|".join(set(_SIGNATURES) - {"figlabel", "seclab", "subseclab", "foot"})
    return bool(
        re.search(
            r"\\(?:def|gdef|edef|xdef|let)\s*\\(?:" + names + r")(?![A-Za-z@])",
            mask_comments(text),
        )
    )


def _unsafe_definitions(text):
    primitives = {
        "if",
        "ifx",
        "ifnum",
        "ifdim",
        "ifodd",
        "ifcase",
        "ifcat",
        "ifdefined",
        "ifcsname",
        "iftrue",
        "iffalse",
        "ifeof",
        "ifhmode",
        "ifvmode",
        "ifmmode",
        "ifinner",
        "ifvoid",
        "ifhbox",
        "ifvbox",
    }
    return _shadowed(text) or bool(generated_names(text) & primitives)


def generated_names(text):
    syntax = mask_comments_and_definitions(text)
    return {
        m[1]
        for m in re.finditer(
            r"\\(?:" + "|".join(_DEFINERS) + r")\s*\\([A-Za-z@]+)", syntax
        )
    }


def scan_text(text):
    names = {n for n in generated_names(text) if n.startswith("if")}
    return re.sub(
        r"\\([A-Za-z@]+)",
        lambda m: "\\" + "z" * len(m[1]) if m[1] in names else m[0],
        text,
    )


def assembly_views(tree, views, dialect):
    if not dialect:
        return views
    result = dict(views)
    for path, raw in tree.files.items():
        if PurePosixPath(path).suffix.lower() not in {"", ".tex"}:
            continue
        try:
            result[path] = scan_text(views.get(path, raw.decode()))
        except UnicodeDecodeError:
            continue
    return result


def body_bounds(text):
    syntax = mask_comments_and_definitions(scan_text(text))
    title = re.search(r"\\Title(?![A-Za-z@])", syntax)
    terminal = list(re.finditer(r"(?m)^\\(?:end|bye)[ \t]*(?=\r?$)", syntax))
    if title is None or len(terminal) != 1 or title.start() >= terminal[0].start():
        raise ValueError("Harvmac requires a literal title and unique plain terminator")
    return title.start(), terminal[0].start(), terminal[0].end()


def adapt_assembly(assembly, dialect):
    if dialect:
        start, _, _ = body_bounds(assembly.text)
        assembly.events = [
            replace(e, region="preamble") if e.out_char_start < start else e
            for e in assembly.events
        ]
    return assembly


def parse_view(text):
    _, end, _ = body_bounds(text)
    text = scan_text(text)
    return text[:end] + "".join("\n" if c == "\n" else " " for c in text[end:])


def context(text):
    result = declaration_context(source_text=text)
    specs = [
        MacroSpec(n, args_parser=MacroStandardArgsParser(a))
        for n, a in _SIGNATURES.items()
    ]
    specs += [
        MacroSpec(n, args_parser=MacroStandardArgsParser(""))
        for n in generated_names(text)
    ]
    result.add_context_category("native-harvmac", macros=specs, prepend=True)
    return result


def annotate_node(item, text):
    start, end = item["range"]
    token = re.match(r"\\([A-Za-z@]+)", text[start:end])
    if item["kind"] == "macro" and token:
        item["name"] = token[1]
    if item["name"] == "eqn" and len(item["arguments"]) == 2:
        item.update(
            kind="math",
            display="display",
            syntax="harvmac_eqn",
            math_tex=item["arguments"][-1][1:-1],
        )


def check_dialect(evidence, document):
    if not document.get("dialect"):
        return
    from types import SimpleNamespace
    from .projection import working_tree, decorate_origins
    from .harvmac_refs import adapt, compiled_entries, cross_references

    files = evidence.files
    projection = evidence.get("source-projection.json", {"verified": False})
    report = evidence["build.json"]
    build = SimpleNamespace(**report, entry=document["entry"])
    tree = working_tree(files, projection=projection)
    if identify(build, tree) != document["dialect"]:
        raise ValueError(
            "Harvmac grammar is not supported by the native build evidence"
        )
    current = evidence["references.json"]
    raw = files.get("build/files/refs.tmp", files.get("sources/refs.tmp", b""))
    diagnostics = [
        d for d in current["diagnostics"] if d["code"] != "harvmac_bibliography_unbound"
    ]
    expected = adapt(
        build, tree, {"diagnostics": diagnostics}, compiled=compiled_entries(raw)
    )
    decorate_origins(expected, files, projection=projection)
    if any(current.get(k) != v for k, v in expected.items()):
        raise ValueError(
            "Harvmac bibliography does not match consumed source and compiled text"
        )
    labels, references = cross_references(document["nodes"])
    if labels != document["labels"] or references != document["cross_references"]:
        raise ValueError("Harvmac reference candidates do not match source definitions")
