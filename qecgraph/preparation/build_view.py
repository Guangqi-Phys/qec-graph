"""Observe literal source guards in a second isolated native build, never infer them."""

from pathlib import PurePosixPath
import re
import secrets

from .artifacts import json_bytes, compiled_bibliography
from .guard_syntax import candidates
from .execution import compare_pdf_text as _compare_pdf_text
from ..source.package import SourceTree

SCHEMA = "qecgraph.build_view/1"


def observe_branches(build, tree, support, compiler):
    guards = _candidates(build, tree)
    report = {
        "schema": SCHEMA,
        "source_tree_sha256": tree.digest,
        "guards": guards,
        "verified": False,
        "native_compile": "not_run",
        "pdf_text": "not_run",
    }
    if not guards:
        return report, {}
    prefix = "QECGRAPH-VIEW-" + secrets.token_hex(8) + "-"
    files, changed = _instrument(tree, guards, prefix)
    files.update(_bibliography(build))
    derived_tree = SourceTree("observed_build_view", files)
    root = build.root / "build-view"
    root.mkdir()
    derived = compiler(
        derived_tree, build.entry, root, engine=build.engine, support=support
    )
    report.update(
        marker_prefix=prefix,
        instrumented_tree_sha256=derived_tree.digest,
        native_compile="complete" if derived.success else "failed",
        engine=derived.engine,
        steps=derived.steps,
        dependencies=derived.dependencies,
        diagnostics=derived.diagnostics,
    )
    if derived.success:
        _compare_pdf_text(build, derived, report)
    report["verified"] = derived.success and report["pdf_text"] == "equal"
    log_path = "files/" + PurePosixPath(build.entry).stem + ".log"
    log = derived.artifacts.get(log_path, b"").decode(
        "utf-8", errors="backslashreplace"
    )
    _observations(report, log)
    artifacts = {"build-view/build/" + p: raw for p, raw in derived.artifacts.items()}
    artifacts.update({"build-view/inputs/" + p: raw for p, raw in changed.items()})
    artifacts["build-view.json"] = json_bytes(report)
    return report, artifacts


def _candidates(build, tree):
    result = []
    for path in build.inputs:
        if path not in tree.files or PurePosixPath(path).suffix != ".tex":
            continue
        try:
            found = candidates(path, tree.files[path])
        except UnicodeDecodeError:
            continue
        for guard in found:
            guard["id"] = "g" + str(len(result))
            result.append(guard)
            if len(result) > 128:
                raise ValueError("Native guard observation limit exceeded")
    return result


_bibliography = compiled_bibliography


def _instrument(tree, guards, prefix):
    changes = {}
    for guard in guards:
        path = guard["origin"]["path"]
        edits = changes.setdefault(path, [])
        edits.append((guard["true_marker"], _marker(prefix, guard["id"], "T")))
        alternative = guard["false_marker"]
        edits.append(
            (
                guard["closing"] if alternative is None else alternative,
                (r"\else" if alternative is None else "")
                + _marker(prefix, guard["id"], "F"),
            )
        )
    files, changed = dict(tree.files), {}
    for path, edits in changes.items():
        text = tree.files[path].decode()
        if prefix in text:
            raise ValueError("Native branch marker collides with source")
        for position, value in sorted(edits, reverse=True):
            text = text[:position] + value + text[position:]
        files[path] = changed[path] = text.encode()
    return files, changed


def _marker(prefix, identifier, branch):
    return r"\immediate\write16{" + prefix + identifier + ":" + branch + r"}\relax"


def _observations(report, log):
    for guard in report["guards"]:
        values = re.findall(
            r"(?m)^"
            + re.escape(report["marker_prefix"] + guard["id"])
            + r":([TF])\r?$",
            log,
        )
        unique = set(values)
        guard["observations"] = values
        guard["selected"] = (
            next(iter(unique)) == "T"
            if len(unique) == 1 and report["verified"]
            else None
        )
        guard["status"] = (
            "observed"
            if guard["selected"] is not None
            else "context_dependent"
            if len(unique) > 1
            else "not_executed"
            if not values
            else "unverified"
        )
