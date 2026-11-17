"""Bounded native build shims, triggered by an exact known class and failure."""

import re
from pathlib import PurePosixPath

from .artifacts import digest

QUANTUMARTICLE_42 = "dff601e10b3c4c408f50ca1353e110ff72f83e30f85895e9c2332bd5d4189319"
HOOK_PREAMBLE = r"\makeatletter\providecommand\@afterenddocumenthook{}\makeatother"


def initial_compile(build, tree, args, *, stdin, runner):
    from .execution import execute

    ok = execute(build, "tex-0", args, stdin=stdin, runner=runner)
    profile = _known_profile(build, tree) if not ok else None
    if profile is None:
        return ok
    build.compatibility.append(profile)
    args[-1] = profile["preamble"] + r"\input{" + build.entry + "}"
    args.insert(-1, "-jobname=" + PurePosixPath(build.entry).stem)
    return execute(build, "tex-compatibility-0", args, stdin=stdin, runner=runner)


def _known_profile(build, tree):
    if build.engine != "pdflatex":
        return None
    log = build.artifacts.get("logs/tex-0.log", b"")
    if (
        b"Undefined control sequence" not in log
        or b"\\@afterenddocumenthook" not in log
    ):
        return None
    source = tree.files[build.entry].decode("latin1")
    source = re.sub(r"(?m)(?<!\\)%[^\n]*", "", source)
    if not re.search(r"\\documentclass(?:\[[^]]*\])?\{quantumarticle\}", source):
        return None
    for path, raw in tree.files.items():
        if (
            path.rsplit("/", 1)[-1] == "quantumarticle.cls"
            and digest(raw) == QUANTUMARTICLE_42
        ):
            return {
                "id": "quantumarticle-4.2-empty-afterenddocument-hook/1",
                "trigger": "undefined_afterenddocument_hook",
                "class_path": path,
                "class_sha256": QUANTUMARTICLE_42,
                "preamble": HOOK_PREAMBLE,
                "source_edits": False,
                "scope": "Restore the old empty default hook; keep the author class and all source bytes.",
            }
    return None
