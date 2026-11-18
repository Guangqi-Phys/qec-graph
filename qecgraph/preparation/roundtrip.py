"""Recompile the derived LaTeX in the same isolated build configuration."""

from __future__ import annotations


from .artifacts import compiled_bibliography
from .bibliography_runtime import bibliography_runtime, bibliography_runtime_failed
from .execution import compare_pdf_text as _compare_pdf_text, compile_derived
from ..source.package import SourceTree


def verify_roundtrip(build, tree, normalized, report, support, compiler):
    files = dict(tree.files)
    # Reuse bibliography actually produced by the first build, without editing originals.
    files.update(compiled_bibliography(build))
    files[build.entry] = normalized
    derived_tree = SourceTree("derived_latex", files)
    derived = compile_derived(build, derived_tree, "normalized", support, compiler)

    report.update(
        native_compile="complete" if derived.success else "failed",
        engine=derived.engine,
        steps=derived.steps,
        dependencies=derived.dependencies,
        diagnostics=derived.diagnostics,
        compatibility=getattr(derived, "compatibility", []),
    )
    if convergence := getattr(derived, "convergence", None):
        report["convergence"] = convergence
    report["derived_tree_sha256"] = derived_tree.digest
    if derived.success:
        report["bibliography_runtime"] = bibliography_runtime(
            derived.artifacts, derived.entry
        )
        _compare_pdf_text(build, derived, report)
    report["complete"] = (
        derived.success
        and report["syntax_parse"] == "complete"
        and report["pdf_text"] not in {"different", "failed"}
        and not bibliography_runtime_failed(report["bibliography_runtime"])
    )
    return {"normalized-build/" + p: raw for p, raw in derived.artifacts.items()}
