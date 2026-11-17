"""One preparation attempt's state and serialized handoff; no compilation or I/O."""

from . import PREPARATION_VERSION
from .artifacts import SCHEMA, CROSS_REFERENCE_POLICY, json_bytes
from .capabilities import preparation_capabilities

_WARNING_CODES = frozenset(
    {
        "asset_case_mismatch",
        "native_guard_observation",
        "conditional_directive_resolved",
        "document_boundary_guard",
        "drawing_conditional",
        "duplicate_labels",
        "cross_reference_ambiguous",
        "guarded_document_bounds",
        "preamble_directive_in_conditional",
    }
)


class Material:
    def __init__(self, tree):
        self.files = {"sources/" + path: raw for path, raw in tree.files.items()}
        self.document = {
            "schema": "qecgraph.prepared_syntax/1",
            "nodes": [],
            "roots": [],
            "outline": [],
            "citations": [],
            "assets": [],
            "body_range": [None, None],
            "cross_reference_policy": CROSS_REFERENCE_POLICY,
        }
        self.entry_data = b""
        self.references = {"bindings": [], "entries": [], "complete": False}
        self.coverage = {
            "complete": False,
            "reasons": ["compile_failed"],
            "diagnostics": [],
        }
        self.build_report = {"success": False, "steps": []}
        self.diagnostics = []
        self.normalization = {
            "complete": False,
            "native_compile": "not_run",
            "pdf_text": "not_run",
        }

    def retain_build(self, build):
        self.files.update({"build/" + p: raw for p, raw in build.artifacts.items()})
        self.build_report = {
            "success": build.success,
            "engine": build.engine,
            "steps": build.steps,
            "inputs": build.inputs,
            "outputs": build.outputs,
            "dependencies": build.dependencies,
            "compatibility": getattr(build, "compatibility", []),
        }
        self.diagnostics.extend(build.diagnostics)

    def fail(self, exc):
        self.diagnostics.append(
            {"code": "preparation_failed", "message": str(exc)[:800]}
        )
        self.coverage = {
            "complete": False,
            "reasons": [
                "conversion_failed"
                if self.build_report["success"]
                else "compile_failed"
            ],
            "diagnostics": [],
        }

    def finish(self, tree, entry, loading):
        self.diagnostics.extend(self.coverage.get("diagnostics", []))
        stages = {
            "compile": "complete" if self.build_report["success"] else "failed",
            "conversion": "complete" if self.coverage["complete"] else "partial",
            "references": "complete" if self.references["complete"] else "partial",
            "normalized_latex": "complete"
            if self.normalization["complete"]
            else "partial",
            "source_fidelity": "checked_at_publication",
        }
        ready = (
            self.build_report["success"]
            and self.coverage["complete"]
            and self.references["complete"]
            and self.normalization["complete"]
            and not self.diagnostics
        )
        self.files.update(
            {
                "entry.tex": self.entry_data,
                "content.json": json_bytes(self.document),
                "references.json": json_bytes(self.references),
                "build.json": json_bytes(self.build_report),
                "coverage.json": json_bytes(self.coverage),
                "diagnostics.json": json_bytes(self.diagnostics),
                "normalization.json": json_bytes(self.normalization),
            }
        )
        manifest = {
            "schema": SCHEMA,
            "rule_version": PREPARATION_VERSION,
            "status": "ready" if ready else "partial",
            "entry": entry,
            "source_tree_sha256": tree.digest,
            "sources": tree.manifest,
            "stages": stages,
            "loading": loading,
            "model_calls": 0,
            "preparation_capabilities": preparation_capabilities(
                self.build_report, self.document, self.coverage, self.references
            ),
            "capabilities": {
                "originals": True,
                "syntax": bool(self.document["nodes"]),
                "scientific_extraction": False,
                "arbitrary_macro_expansion": False,
                "normalized_latex": "normalized.tex" in self.files,
            },
            "limitations": [
                "Native compilation is one build view; unmapped conditionals remain partial.",
                "The normalized handoff preserves original TeX syntax; it is not rendered semantic text.",
                "No theorem truth, experiment binding, numeric curve extraction or nine-question answers are produced.",
            ],
            "warnings": sorted(
                {
                    observation["code"]
                    for observation in self.coverage.get("observations", [])
                    if observation["code"] in _WARNING_CODES
                }
            ),
        }
        return self.files, manifest
