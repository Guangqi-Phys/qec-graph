"""Compile the unchanged source tree, then collect actual build artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import platform
import re

from . import sandbox
from .execution import Build as Build, tool as tool, execute as execute
from .artifacts import digest, safe_path
from ..source.package import SourceTree

ENGINES = {"pdflatex", "xelatex", "lualatex", "latex", "etex", "pdftex"}


def select_engine(tree, entry, requested=None):
    if requested is None:
        try:
            metadata = json.loads(tree.files.get("00README.json", b"{}"))
            requested = metadata.get("process", {}).get("compiler")
        except (ValueError, AttributeError):
            pass
    if requested is not None:
        if requested not in ENGINES:
            raise ValueError(
                "Unsupported compiler; expected " + ", ".join(sorted(ENGINES))
            )
        return requested
    body = tree.files[entry].decode("latin1")
    body = re.sub(r"(?m)(?<!\\)%.*$", "", body)
    if re.search(r"\\input\s*\{?harvmac", body):
        return "etex"
    if re.search(r"\\(?:documentstyle|epsfbox|psfig)\b|hypertex|BoxedEPS", body):
        return "latex"
    if re.search(r"\\usepackage(?:\[[^\]]*\])?\{(?:unicode-math|fontspec)\}", body):
        return "xelatex"
    return "pdflatex"


def _support(build, folders):
    for folder in folders:
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("Support directory must be a regular directory")
        for source in sorted(folder.rglob("*")):
            if source.is_symlink():
                raise ValueError("Linked TeX support file")
            if not source.is_file():
                continue
            relative = source.relative_to(folder).as_posix()
            target = build.root / "texmf/tex/generic/qecgraph" / safe_path(relative)
            raw = source.read_bytes()
            if (
                len(raw) > 16 << 20
                or sum(d["size"] for d in build.dependencies) + len(raw) > 64 << 20
            ):
                raise ValueError("TeX support byte limit exceeded")
            if target.exists() and target.read_bytes() != raw:
                raise ValueError("Conflicting TeX support files")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            build.artifacts["support/" + relative] = raw
            build.dependencies.append(
                {"path": relative, "sha256": digest(raw), "size": len(raw)}
            )


def _bibliography(build, tree, job, runner):
    project = build.root / "project"
    # The same job's supplied BBL is preserved, even when a partial BIB exists.
    if job + ".bbl" in tree.files:
        return True
    if (project / (job + ".bcf")).exists():
        binary = tool("biber")
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            target = build.root / "biber-native"
            if execute(
                build,
                "biber-architecture",
                [tool("lipo"), binary, "-thin", "arm64", "-output", str(target)],
                runner=runner,
            ):
                target.chmod(0o755)
                binary = str(target)
        return execute(build, "bibliography", [binary, job], runner=runner)
    aux = project / (job + ".aux")
    if aux.exists() and r"\bibdata{" in aux.read_text(errors="replace"):
        return execute(build, "bibliography", [tool("bibtex"), job], runner=runner)
    return True


def _record_files(build, tree, job):
    project = build.root / "project"
    fls = project / (job + ".fls")
    paths = {"INPUT": set(), "OUTPUT": set()}
    if fls.exists():
        lines = fls.read_text(errors="replace").splitlines()
        if len(lines) > 32768:
            raise ValueError("TeX recorder line limit exceeded")
        for line in lines:
            kind, _, name = line.partition(" ")
            if kind not in paths:
                continue
            path = Path(name)
            path = (path if path.is_absolute() else project / path).resolve()
            if path.is_relative_to(project):
                paths[kind].add(path.relative_to(project).as_posix())
            elif (
                kind == "INPUT"
                and _trusted_dependency(path, build.root)
                and path.is_file()
            ):
                build.dependencies.append(
                    {
                        "path": str(path).replace(str(build.root), "<build>"),
                        "sha256": digest(path.read_bytes()),
                        "size": path.stat().st_size,
                    }
                )
    build.inputs = sorted(paths["INPUT"])
    build.outputs = sorted(paths["OUTPUT"])
    retained = (
        paths["INPUT"]
        | paths["OUTPUT"]
        | {
            job + suffix
            for suffix in (".pdf", ".log", ".fls", ".synctex.gz", ".bbl", ".bcf")
        }
    )
    _collect_artifacts(build, tree, retained)


def _trusted_dependency(path, root):
    # FLS is untrusted output. Never let it make the parent read a user file.
    return any(
        path.is_relative_to(Path(p).resolve())
        for p in (
            root / "texmf",
            root / "cache",
            "/usr/local/texlive",
            "/usr/local/share/texmf",
            "/usr/share/texlive",
            "/usr/share/texmf",
            "/var/lib/texmf",
            "/System/Library/Fonts",
            "/Library/Fonts",
        )
    )


def compile_tree(
    tree: SourceTree,
    entry: str,
    root: Path,
    *,
    engine=None,
    support=(),
    runner=sandbox.run,
) -> Build:
    """No assembly, parser, AI, archive mutation or source edits before compiling."""
    safe_path(entry)
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", entry) or entry.startswith("-"):
        raise ValueError("Compiler entry needs a literal portable filename")
    build = Build(entry, select_engine(tree, entry, engine), root.resolve())
    tree.materialize(build.root / "project")
    _support(build, support)
    job = Path(entry).stem
    project = build.root / "project"
    for suffix in (
        ".aux",
        ".out",
        ".log",
        ".toc",
        ".bcf",
        ".run.xml",
        ".pdf",
        ".fls",
        ".synctex.gz",
    ):
        stale = project / (job + suffix)
        if stale.is_file():
            stale.unlink()
    args = [
        tool(build.engine),
        "-no-shell-escape",
        "-halt-on-error",
        "-file-line-error",
        "-interaction="
        + ("errorstopmode" if build.engine == "etex" else "nonstopmode"),
        "-recorder",
        "-synctex=1",
        entry,
    ]
    stdin = "b\n" if build.engine == "etex" else None
    execute(build, "engine-version", [tool(build.engine), "--version"], runner=runner)
    from .compatibility import initial_compile
    from .tex_passes import finish_passes

    ok = initial_compile(build, tree, args, stdin=stdin, runner=runner)
    if ok:
        ok = _bibliography(build, tree, job, runner)
    if ok:
        ok = finish_passes(build, job, args, stdin=stdin, runner=runner)
    if ok:
        ok = _pdf(build, job, runner)
    build.success = ok and (project / (job + ".pdf")).is_file()
    _check_source_copy(build, tree)
    _check_support_copy(build)
    _record_files(build, tree, job)
    if not build.success:
        build.diagnostics.append(
            {
                "code": "compile_failed",
                "stage": "compile",
                "severity": "error",
                "message": "Native compilation failed; inspect the retained build logs.",
            }
        )
    return build


def _check_source_copy(build, tree):
    for path, original in tree.files.items():
        if Path(path).suffix not in {".tex", ".sty", ".cls", ".bst"}:
            continue
        file = build.root / "project" / path
        if file.is_symlink() or not file.is_file() or file.read_bytes() != original:
            build.success = False
            build.diagnostics.append(
                {
                    "code": "source_changed_during_build",
                    "path": path,
                    "message": "Compilation changed an input source; the original is retained.",
                }
            )


def _check_support_copy(build):
    for path, original in list(build.artifacts.items()):
        if not path.startswith("support/"):
            continue
        target = (
            build.root
            / "texmf/tex/generic/qecgraph"
            / safe_path(path.removeprefix("support/"))
        )
        if (
            target.is_symlink()
            or not target.is_file()
            or target.read_bytes() != original
        ):
            build.success = False
            build.diagnostics.append(
                {
                    "code": "support_changed_during_build",
                    "path": path,
                    "message": "Compilation changed an explicitly supplied dependency.",
                }
            )


def _collect_artifacts(build, tree, retained):
    project = build.root / "project"
    total = sum(len(v) for v in build.artifacts.values())
    for name in sorted(retained):
        path = project / safe_path(name)
        if path.is_symlink() or not path.is_file():
            continue
        raw = path.read_bytes()
        total += len(raw)
        if total > 256 << 20:
            raise ValueError("Compiled artifact byte limit exceeded")
        if name not in tree.files or tree.files[name] != raw:
            build.artifacts["files/" + name] = raw


def _pdf(build, job, runner):
    ok = True
    if build.engine in {"latex", "etex"}:
        ok = execute(
            build,
            "dvips",
            [tool("dvips"), "-R2", "-o", job + ".ps", job + ".dvi"],
            runner=runner,
        )
        if ok:
            ok = execute(
                build,
                "ps2pdf",
                [tool("ps2pdf"), "-dSAFER", job + ".ps", job + ".pdf"],
                runner=runner,
            )
    return ok
