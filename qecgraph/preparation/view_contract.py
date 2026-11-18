"""Check native guard evidence, source instrumentation and view projection without TeX."""

import copy
from pathlib import PurePosixPath
import re
from types import SimpleNamespace

from .build_view import SCHEMA, _candidates, _instrument, _observations
from .artifacts import (
    compiled_bibliography,
    digest,
    json_bytes,
    pdf_text_pages,
    pdf_text_hashes,
)
from .guard_syntax import scan_views, project_view
from .branches import syntax_view
from .projection import working_tree, decorate_origins
from . import harvmac
from ..source.assembly import assemble_files, EntryCoordinates, document_bounds
from ..source.package import SourceTree


def check_view(evidence, document, text):
    expected_hash = document.get("build_view_sha256")
    if expected_hash is None:
        if document.get("observed_guards"):
            raise ValueError("Observed guards are missing their native build evidence")
        return
    files = evidence.files
    raw = files.get("build-view.json", b"")
    if digest(raw) != expected_hash:
        raise ValueError("Native build-view identity mismatch")
    view = evidence["build-view.json"]
    if view["schema"] != SCHEMA:
        raise ValueError("Unsupported native build-view schema")
    projection = evidence.get("source-projection.json", {"verified": False})
    tree = working_tree(files, projection=projection)
    if view["source_tree_sha256"] != tree.digest:
        raise ValueError("Native build view belongs to another original source tree")
    if view["guards"]:
        _check_probe(evidence, view, tree)
    _check_projection(evidence, document, text, tree, view, projection)


def _check_probe(evidence, view, tree):
    files = evidence.files
    manifest = evidence["manifest.json"]
    build = evidence["build.json"]
    original = SimpleNamespace(
        entry=manifest["entry"],
        inputs=build["inputs"],
        artifacts={
            p.removeprefix("build/"): raw
            for p, raw in files.items()
            if p.startswith("build/")
        },
    )
    expected = _candidates(original, tree)
    base_fields = set(expected[0]) if expected else set()
    actual = [{key: g.get(key) for key in base_fields} for g in view["guards"]]
    if expected != actual:
        raise ValueError(
            "Native guard grammar does not match consumed original sources"
        )
    prefix = view["marker_prefix"]
    if re.fullmatch(r"QECGRAPH-VIEW-[0-9a-f]{16}-", prefix) is None:
        raise ValueError("Invalid native guard marker prefix")
    instrumented, changed = _instrument(tree, expected, prefix)
    instrumented.update(compiled_bibliography(original))
    if (
        SourceTree("observed_build_view", instrumented).digest
        != view["instrumented_tree_sha256"]
    ):
        raise ValueError("Instrumented source tree identity mismatch")
    for path, raw in changed.items():
        if files.get("build-view/inputs/" + path) != raw:
            raise ValueError(
                "Native guard instrumentation changed outside the allowed markers"
            )
    _check_observations(files, view, expected, manifest["entry"])


def _check_observations(files, view, expected, entry):
    if view["verified"]:
        if view["native_compile"] != "complete" or view["pdf_text"] != "equal":
            raise ValueError("Native guard view has an unverified build outcome")
        _check_pdf_text(files, view)
    job = PurePosixPath(entry).stem
    log = files.get("build-view/build/files/" + job + ".log", b"").decode(
        "utf-8", errors="backslashreplace"
    )
    checked = {**view, "guards": copy.deepcopy(expected)}
    _observations(checked, log)
    if checked["guards"] != view["guards"]:
        raise ValueError("Native guard choices do not match the recorded TeX log")


def _check_pdf_text(files, view):
    pages = []
    for index in (0, 1):
        raw = files["build-view/build/files/pdf-text-" + str(index) + ".txt"]
        pages.append(pdf_text_pages(raw))
    hashes = pdf_text_hashes(pages)
    if pages[0] != pages[1] or hashes != view["pdf_text_sha256"]:
        raise ValueError("Native guard probe changed the per-page PDF text")


def _check_projection(evidence, document, text, tree, view, projection):
    build = evidence["build.json"]
    assembly = assemble_files(
        tree.files,
        document["entry"],
        scan_views=harvmac.assembly_views(
            tree, scan_views(tree, view), document.get("dialect")
        ),
        allowed_inputs=build.get("inputs"),
    )
    harvmac.adapt_assembly(assembly, document.get("dialect"))
    if assembly.text != text or json_bytes(assembly.source_map()) != json_bytes(
        evidence["source-map.json"]
    ):
        raise ValueError("Build-view assembly does not match original-source mapping")
    masks, guards = project_view(assembly, view)
    decorate_origins(guards, evidence.files, projection=projection)
    coordinates = EntryCoordinates(assembly)
    parse_text, inactive = syntax_view(
        harvmac.parse_view(coordinates.copy_text())
        if document.get("dialect")
        else coordinates.copy_text(),
        [(coordinates.to_parse(a), coordinates.to_parse(b)) for a, b in masks],
    )
    inactive = [[coordinates.to_entry(a), coordinates.to_entry(b)] for a, b in inactive]
    if document["observed_guards"] != guards or document["inactive_ranges"] != inactive:
        raise ValueError(
            "Observed guard projection does not match native source evidence"
        )
    _, start, end = document_bounds(parse_text)
    bounds = [coordinates.to_entry(v) if v is not None else None for v in (start, end)]
    if document.get("dialect"):
        bounds = list(harvmac.body_bounds(text)[:2])
    if document["body_range"] != bounds:
        raise ValueError("Document bounds do not match the observed active view")
