"""Finish bounded native passes using recorder and final-log evidence."""

from pathlib import Path
import re

from .artifacts import digest
from .execution import execute

_DRIVER_OUTPUTS = (".log", ".fls", ".pdf", ".dvi", ".xdv", ".synctex.gz")
_RERUN = re.compile(
    rb"Rerun\s+(?:to get|LaTeX)|Please\s+(?:\(re\)run|rerun)\s+"
    rb"(?:LaTeX|Biber|BibTeX)|There were undefined references\.",
    re.IGNORECASE,
)
_FEEDBACK_LIMIT = 8 << 20


def _read(path, limit):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _feedback_paths(project, recorder, job):
    outputs = set()
    for line in recorder.splitlines():
        kind, _, name = line.partition(" ")
        if kind != "OUTPUT":
            continue
        try:
            path = (project / name).resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        if not path.is_relative_to(project):
            return None
        if not path.name.endswith(_DRIVER_OUTPUTS):
            outputs.add(path)
    return outputs if project / (job + ".aux") in outputs else None


def _feedback(project: Path, job):
    recorder = _read(project / (job + ".fls"), _FEEDBACK_LIMIT)
    log = _read(project / (job + ".log"), _FEEDBACK_LIMIT)
    if recorder is None or log is None:
        return None, False
    rerun = bool(_RERUN.search(log))
    paths = _feedback_paths(project, recorder.decode(errors="replace"), job)
    if paths is None:
        return None, rerun
    remaining = _FEEDBACK_LIMIT
    state = {}
    for path in paths:
        raw = _read(path, remaining)
        if raw is None:
            return None, rerun
        remaining -= len(raw)
        state[path.relative_to(project).as_posix()] = digest(raw)
    return state, rerun


def finish_passes(build, job, args, *, stdin, runner):
    """Early exit requires two successful passes and unchanged auxiliary output."""
    project = build.root / "project"
    observe = build.engine != "etex"
    previous, rerun = _feedback(project, job) if observe else (None, False)
    status = "unavailable"
    for index in (1, 2):
        if not execute(build, f"tex-{index}", args, stdin=stdin, runner=runner):
            build.convergence = _result("failed", index, rerun)
            return False
        state, rerun = _feedback(project, job) if observe else (None, False)
        if state is not None and state == previous and not rerun:
            status = "converged"
            break
        previous = state
        status = "pass_limit" if state is not None else "unavailable"
    build.convergence = _result(status, index, rerun)
    return True


def _result(status, index, rerun):
    return {"status": status, "tex_passes": index + 1, "rerun_requested": rerun}
