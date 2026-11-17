"""Recompile the derived LaTeX in the same isolated build configuration."""

from __future__ import annotations

from pathlib import Path

from . import sandbox
from .build import tool
from .contract import digest
from ..source.package import SourceTree


def verify_roundtrip(build, tree, normalized, report, support, compiler):
    files = dict(tree.files)
    # Reuse bibliography actually produced by the first build, without editing originals.
    for path, raw in build.artifacts.items():
        if path.startswith("files/") and Path(path).suffix in {".bbl", ".bib"}:
            files[path.removeprefix("files/")] = raw
    files[build.entry] = normalized
    root = build.root / "normalized"
    root.mkdir()
    derived_tree = SourceTree("derived_latex", files)
    derived = compiler(
        derived_tree, build.entry, root, engine=build.engine, support=support
    )
    report.update(
        native_compile="complete" if derived.success else "failed",
        engine=derived.engine,
        steps=derived.steps,
        dependencies=derived.dependencies,
        diagnostics=derived.diagnostics,
    )
    report["derived_tree_sha256"] = derived_tree.digest
    if derived.success:
        _compare_pdf_text(build, derived, report)
    report["complete"] = (
        derived.success
        and report["syntax_parse"] == "complete"
        and report["pdf_text"] not in {"different", "failed"}
    )
    return {"normalized-build/" + p: raw for p, raw in derived.artifacts.items()}


def _compare_pdf_text(original, derived, report):
    job = Path(original.entry).stem
    pdfs = [b.root / "project" / (job + ".pdf") for b in (original, derived)]
    try:
        binary = tool("pdftotext")
    except ValueError:
        report["pdf_text"] = "tool_unavailable"
        return
    if not all(p.is_file() for p in pdfs):
        report["pdf_text"] = "pdf_unavailable"
        return
    pages = []
    for index, pdf in enumerate(pdfs):
        output = original.root / ("pdf-text-" + str(index) + ".txt")
        result = sandbox.run(
            original.root,
            original.root,
            [binary, "-enc", "UTF-8", str(pdf), str(output)],
        )
        derived.artifacts[f"logs/pdf-text-{index}.log"] = result.pop("log")
        if result["exit"] != 0 or result["timeout"]:
            report["pdf_text"] = "failed"
            return
        raw = output.read_bytes()
        derived.artifacts[f"files/pdf-text-{index}.txt"] = raw
        pages.append(["".join(p.split()) for p in raw.decode().split("\f")])
    report["pdf_text"] = "equal" if pages[0] == pages[1] else "different"
    report["pdf_text_sha256"] = [digest("\f".join(p).encode()) for p in pages]
    report["pdf_text_scope"] = (
        "Per-page non-whitespace text equality; not pixel or mathematical equivalence"
    )
