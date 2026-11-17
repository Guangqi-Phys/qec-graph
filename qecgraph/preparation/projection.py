"""Reversible TeX byte spelling; never guess a Unicode encoding for invalid bytes."""

import json
from pathlib import PurePosixPath
import re

from .contract import digest, json_bytes, safe_path
from .roundtrip import _compare_pdf_text
from ..source.package import SourceTree

SCHEMA = "qecgraph.source_projection/1"
_TEXT = {".tex", ".sty", ".cls", ".bib", ".bbl"}
_INVALID = re.compile("[\udc80-\udcff]")


def project_bytes(raw):
    text = raw.decode("utf-8", "surrogateescape")
    matches = list(_INVALID.finditer(text))
    if len(matches) > 4096:
        raise ValueError("TeX byte projection limit exceeded")
    pieces, segments = [], []
    cursor = byte_pos = char_pos = 0
    for match in matches:
        copy = text[cursor : match.start()]
        byte_pos, char_pos = _segment(pieces, segments, copy, byte_pos, char_pos)
        value = "^^" + format(ord(match[0]) - 0xDC00, "02x")
        segments.append(
            {
                "input_bytes": [byte_pos, byte_pos + 1],
                "output_chars": [char_pos, char_pos + 4],
                "operation": "tex_byte_escape",
            }
        )
        pieces.append(value)
        cursor, byte_pos, char_pos = match.end(), byte_pos + 1, char_pos + 4
    _segment(pieces, segments, text[cursor:], byte_pos, char_pos)
    return "".join(pieces).encode(), segments


def _segment(pieces, segments, text, byte_pos, char_pos):
    if text:
        stop = byte_pos + len(text.encode())
        segments.append(
            {
                "input_bytes": [byte_pos, stop],
                "output_chars": [char_pos, char_pos + len(text)],
                "operation": "copy",
            }
        )
        pieces.append(text)
        return stop, char_pos + len(text)
    return byte_pos, char_pos


def candidate_tree(tree, paths):
    files, records = dict(tree.files), []
    for path in sorted(set(paths) & set(files)):
        if PurePosixPath(path).suffix not in _TEXT:
            continue
        raw = files[path]
        projected, segments = project_bytes(raw)
        if projected != raw:
            files[path] = projected
            records.append(
                {
                    "path": path,
                    "original_sha256": digest(raw),
                    "projected_sha256": digest(projected),
                    "segments": segments,
                }
            )
    return SourceTree("tex_byte_projection", files), records


def prepare_projection(build, tree, support, compiler, artifacts):
    projected, records = candidate_tree(tree, build.inputs)
    if not records:
        return tree
    report = {
        "schema": SCHEMA,
        "original_tree_sha256": tree.digest,
        "projected_tree_sha256": projected.digest,
        "files": records,
        "verified": False,
        "native_compile": "not_run",
        "pdf_text": "not_run",
    }
    artifacts["source-projection.json"] = json_bytes(report)
    _eligibility(build.engine, tree, build.inputs)
    root = build.root / "projection-build"
    root.mkdir()
    derived = compiler(
        projected, build.entry, root, engine=build.engine, support=support
    )
    report.update(
        native_compile="complete" if derived.success else "failed",
        engine=derived.engine,
        inputs=derived.inputs,
        steps=derived.steps,
        dependencies=derived.dependencies,
    )
    if derived.success:
        _compare_pdf_text(build, derived, report)
    same_inputs = set(derived.inputs) & set(tree.files) == set(build.inputs) & set(
        tree.files
    )
    report["same_original_inputs"] = same_inputs
    report["verified"] = (
        derived.success and report["pdf_text"] == "equal" and same_inputs
    )
    artifacts.update(
        {"projection-build/" + p: raw for p, raw in derived.artifacts.items()}
    )
    artifacts.update(
        {"projected-sources/" + r["path"]: projected.files[r["path"]] for r in records}
    )
    artifacts["source-projection.json"] = json_bytes(report)
    if not report["verified"]:
        raise ValueError(
            "TeX byte projection has no matching native build and PDF text evidence"
        )
    return projected


def working_tree(files):
    original = {
        p.removeprefix("sources/"): raw
        for p, raw in files.items()
        if p.startswith("sources/")
    }
    report = json.loads(files.get("source-projection.json", b'{"verified":false}'))
    if report["verified"]:
        original.update(
            {
                r["path"]: files["projected-sources/" + safe_path(r["path"])]
                for r in report["files"]
            }
        )
    return SourceTree("working_sources", original)


def check_projection(files):
    if "source-projection.json" not in files:
        return
    report = json.loads(files["source-projection.json"])
    if report["schema"] != SCHEMA:
        raise ValueError("Unsupported source projection schema")
    original = SourceTree(
        "original", {p[8:]: raw for p, raw in files.items() if p.startswith("sources/")}
    )
    if report["original_tree_sha256"] != original.digest:
        raise ValueError("Source projection original identity mismatch")
    if not report["verified"]:
        return
    build = json.loads(files["build.json"])
    _eligibility(build["engine"], original, build["inputs"])
    projected, records = candidate_tree(original, build["inputs"])
    document = json.loads(files["content.json"])
    if document.get("source_projection_sha256") != digest(
        files["source-projection.json"]
    ):
        raise ValueError("Prepared syntax has no bound source projection")
    if (
        records != report["files"]
        or projected.digest != report["projected_tree_sha256"]
    ):
        raise ValueError("Source projection does not match the allowed byte spelling")
    if any(
        files.get("projected-sources/" + r["path"]) != projected.files[r["path"]]
        for r in records
    ):
        raise ValueError("Projected source bytes changed")
    _check_evidence(files, report, build, original)


def _check_evidence(files, report, build, original):
    same = set(report["inputs"]) & set(original.files) == set(build["inputs"]) & set(
        original.files
    )
    if (
        not same
        or not report.get("same_original_inputs")
        or report["native_compile"] != "complete"
    ):
        raise ValueError("Source projection build input evidence mismatch")
    pages = [
        [
            "".join(p.split())
            for p in files[f"projection-build/files/pdf-text-{i}.txt"]
            .decode()
            .split("\f")
        ]
        for i in (0, 1)
    ]
    hashes = [digest("\f".join(p).encode()) for p in pages]
    if (
        report["pdf_text"] != "equal"
        or pages[0] != pages[1]
        or hashes != report["pdf_text_sha256"]
    ):
        raise ValueError("Source projection PDF text evidence mismatch")


def decorate_origins(value, artifacts):
    report = json.loads(artifacts.get("source-projection.json", b'{"verified":false}'))
    if report["verified"]:
        records = {r["path"]: r for r in report["files"]}
        _decorate(value, records, artifacts)


def _decorate(value, records, artifacts):
    if isinstance(value, list):
        for item in value:
            _decorate(item, records, artifacts)
    elif isinstance(value, dict):
        path = value.get("path")
        if value.get("layer") == "original" and path in records:
            value["layer"] = "projected"
            value["original_source"] = original_locator(value, records[path], artifacts)
        else:
            for item in value.values():
                _decorate(item, records, artifacts)


def original_locator(span, record, artifacts, text=None):
    if text is None:
        text = artifacts["projected-sources/" + safe_path(span["path"])].decode()
    start, end = span["chars"]
    ranges = []
    for segment in record["segments"]:
        a, b = segment["output_chars"]
        if a < end and start < b:
            lo, hi = segment["input_bytes"]
            if segment["operation"] == "copy":
                lo += len(text[a : max(start, a)].encode())
                hi = segment["input_bytes"][0] + len(text[a : min(end, b)].encode())
            ranges.append([lo, hi])
    if not ranges:
        raise ValueError("Projected locator has no original byte range")
    return {
        "path": span["path"],
        "sha256": record["original_sha256"],
        "bytes": [ranges[0][0], ranges[-1][1]],
        "coordinate_unit": "byte",
        "scope": "Enclosing original bytes; projected characters are not verbatim quotations",
    }


def check_locator(span, files, text):
    report = json.loads(files["source-projection.json"])
    if not report["verified"]:
        raise ValueError("Projected locator has no verified projection")
    record = next((r for r in report["files"] if r["path"] == span["path"]), None)
    if record is None or span.get("original_source") != original_locator(
        span, record, files, text
    ):
        raise ValueError("Projected locator original bytes mismatch")


def _eligibility(engine, tree, inputs):
    if engine not in {"pdflatex", "pdftex", "latex", "etex"}:
        raise ValueError(
            "Byte projection requires a supported byte-oriented TeX engine"
        )
    if any(b"\\catcode" in tree.files[p] for p in inputs if p in tree.files):
        raise ValueError("Byte projection does not support explicit catcode changes")
