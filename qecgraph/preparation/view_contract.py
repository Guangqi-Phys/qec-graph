"""Check native guard evidence, source instrumentation and view projection without TeX."""

import copy
import json
from pathlib import PurePosixPath
import re
from types import SimpleNamespace

from .build_view import SCHEMA, _candidates, _instrument, _bibliography, _observations
from .contract import digest
from .guard_syntax import scan_views, project_view
from .branches import syntax_view
from ..source.assembly import assemble_files, EntryCoordinates, document_bounds
from ..source.package import SourceTree


def check_view(files, document, text):
    expected_hash = document.get("build_view_sha256")
    if expected_hash is None:
        if document.get("observed_guards"):
            raise ValueError("Observed guards are missing their native build evidence")
        return
    raw = files.get("build-view.json", b"")
    if digest(raw) != expected_hash:
        raise ValueError("Native build-view identity mismatch")
    view = json.loads(raw)
    if view["schema"] != SCHEMA:
        raise ValueError("Unsupported native build-view schema")
    tree = SourceTree(
        "tex",
        {
            p.removeprefix("sources/"): raw
            for p, raw in files.items()
            if p.startswith("sources/")
        },
    )
    if view["source_tree_sha256"] != tree.digest:
        raise ValueError("Native build view belongs to another original source tree")
    if view["guards"]:
        _check_probe(files, view, tree)
    _check_projection(files, document, text, tree, view)


def _check_probe(files, view, tree):
    manifest = json.loads(files["manifest.json"])
    build = json.loads(files["build.json"])
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
    instrumented.update(_bibliography(original))
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
        pages.append(["".join(p.split()) for p in raw.decode().split("\f")])
    hashes = [digest("\f".join(p).encode()) for p in pages]
    if pages[0] != pages[1] or hashes != view["pdf_text_sha256"]:
        raise ValueError("Native guard probe changed the per-page PDF text")


def _check_projection(files, document, text, tree, view):
    assembly = assemble_files(
        tree.files, document["entry"], scan_views=scan_views(tree, view)
    )
    if assembly.text != text or assembly.source_map() != json.loads(
        files["source-map.json"]
    ):
        raise ValueError("Build-view assembly does not match original-source mapping")
    masks, guards = project_view(assembly, view)
    coordinates = EntryCoordinates(assembly)
    parse_text, inactive = syntax_view(
        coordinates.copy_text(),
        [(coordinates.to_parse(a), coordinates.to_parse(b)) for a, b in masks],
    )
    inactive = [[coordinates.to_entry(a), coordinates.to_entry(b)] for a, b in inactive]
    if document["observed_guards"] != guards or document["inactive_ranges"] != inactive:
        raise ValueError(
            "Observed guard projection does not match native source evidence"
        )
    _, start, end = document_bounds(parse_text)
    bounds = [coordinates.to_entry(v) if v is not None else None for v in (start, end)]
    if document["body_range"] != bounds:
        raise ValueError("Document bounds do not match the observed active view")
