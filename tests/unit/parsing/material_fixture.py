"""Wrap deterministic syntax fixtures in the current material envelope."""

from types import SimpleNamespace

from qecgraph.preparation.artifacts import digest, json_bytes
from qecgraph.preparation.bibliography_runtime import record_bibliography_runtime
from qecgraph.preparation.material import Material


def partial_material(tree, entry, content, document, *, coverage=None, references=None):
    material = Material(tree)
    material.entry_data = content
    material.document.update(document)
    material.references.update(references or {})
    if material.references.get("mode") in {"classic", "biblatex"}:
        record_bibliography_runtime(
            material.references, SimpleNamespace(entry=entry, artifacts={})
        )
    if coverage is not None:
        material.coverage = coverage
    material.build_report["inputs"] = sorted(tree.files)
    files, manifest = material.finish(tree, entry, [])
    manifest["artifacts"] = {name: digest(raw) for name, raw in files.items()}
    files["manifest.json"] = json_bytes(manifest)
    return files
