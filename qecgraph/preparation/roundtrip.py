"""Recompile the derived LaTeX in the same isolated build configuration."""

from __future__ import annotations


from .artifacts import compiled_bibliography
from .execution import compare_pdf_text as _compare_pdf_text
from ..source.package import SourceTree


def verify_roundtrip(build, tree, normalized, report, support, compiler):
    files = dict(tree.files)
    # Reuse bibliography actually produced by the first build, without editing originals.
    files.update(compiled_bibliography(build))
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
        compatibility=getattr(derived, "compatibility", []),
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
