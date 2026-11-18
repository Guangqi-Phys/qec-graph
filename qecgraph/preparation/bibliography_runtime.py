"""Observed bibliography failures in the retained final TeX transcript."""

from pathlib import PurePosixPath
import re

from .artifacts import digest


_WARNING_PREFIXES = (
    b"LaTeX Warning: ",
    b"Package biblatex Warning: ",
    b"Package natbib Warning: ",
)
_BBL_FORMAT = re.compile(
    r"^Package biblatex Warning: File '([^']+)' is wrong format version"
)
_UNDEFINED = re.compile(
    r"Warning: Citation '([^']+)'(?: on page \S+)? (?:is )?undefined\b"
)
_FAILURES = {"incompatible_bbl", "undefined_citations"}


def _warnings(log):
    lines = log.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(_WARNING_PREFIXES):
            continue
        parts = [line]
        for continuation in lines[index + 1 : index + 9]:
            # TeX wraps the transcript at 79 bytes even within a word or key.
            if (
                len(parts[-1]) != 79
                or not continuation
                or continuation.startswith(_WARNING_PREFIXES)
            ):
                break
            parts.append(continuation)
        yield b"".join(parts).decode("utf-8", errors="replace")


def bibliography_runtime(artifacts, entry, *, prefix=""):
    path = prefix + "files/" + PurePosixPath(entry).stem + ".log"
    log = artifacts.get(path)
    if log is None:
        return {"status": "unavailable"}
    incompatible, undefined = set(), set()
    for message in _warnings(log):
        if match := _BBL_FORMAT.match(message):
            incompatible.add(match[1])
        if match := _UNDEFINED.search(message):
            undefined.add(match[1])
    return {
        "status": (
            "incompatible_bbl"
            if incompatible
            else "undefined_citations"
            if undefined
            else "no_reported_failures"
        ),
        "log_sha256": digest(log),
        "incompatible_bbl_files": sorted(incompatible),
        "undefined_keys": sorted(undefined),
    }


def bibliography_runtime_failed(runtime):
    return runtime["status"] in _FAILURES


def record_bibliography_runtime(references, build):
    runtime = bibliography_runtime(getattr(build, "artifacts", {}), build.entry)
    references["runtime"] = runtime
    references["structure_complete"] = references["complete"]
    if bibliography_runtime_failed(runtime):
        references["diagnostics"].append({"code": "bibliography_runtime_failed"})
        references["complete"] = False
