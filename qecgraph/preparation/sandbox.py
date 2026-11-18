"""Bounded local tools inside a filesystem and network sandbox."""

from __future__ import annotations

import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import time


def _profile(work: Path) -> str:
    roots = [
        "/System",
        "/usr/bin",
        "/usr/lib",
        "/usr/share",
        "/usr/local/bin",
        "/usr/local/texlive",
        "/Library/TeX",
        "/Library/Fonts",
        "/Library/Developer/CommandLineTools/usr",
        "/bin",
        "/sbin",
        "/opt/homebrew/bin",
        "/opt/homebrew/lib",
        "/opt/homebrew/Cellar",
        "/opt/homebrew/opt",
        "/opt/homebrew/share",
        "/dev",
        "/private/etc/fonts",
        "/private/var/db/timezone",
        str(work),
    ]
    reads = " ".join(f"(subpath {json.dumps(p)})" for p in roots)
    return f"""(version 1)
(deny default)
(import "/System/Library/Sandbox/Profiles/dyld-support.sb")
(allow syscall*)
(allow process*)
(allow sysctl-read)
(allow file-read-metadata)
(allow mach-lookup (global-name-regex #"^com\\.apple\\.(dyld|logd|system\\.logger)"))
(allow file-read-data file-map-executable {reads})
(allow file-write* (subpath {json.dumps(str(work))}) (literal "/dev/null"))
"""


def _command(work: Path, cwd: Path, command: list[str]) -> list[str]:
    if sys.platform == "darwin":
        profile = work / "sandbox.sb"
        profile.write_text(_profile(work))
        return ["/usr/bin/sandbox-exec", "-f", str(profile), *command]
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise ValueError(
            "Isolated TeX execution requires sandbox-exec on macOS or bubblewrap on Linux"
        )
    args = [bwrap, "--unshare-all", "--die-with-parent", "--new-session"]
    for name in (
        "/usr",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/opt",
        "/etc/alternatives",  # Debian TeX tools can dispatch through these symlinks.
        "/etc/fonts",
        "/etc/texmf",
        "/var/lib/texmf",
    ):
        if Path(name).exists():
            args.extend(["--ro-bind", name, name])
    return [
        *args,
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--bind",
        str(work),
        str(work),
        "--chdir",
        str(cwd),
        *command,
    ]


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 << 20, 64 << 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))


def run(work: Path, cwd: Path, command: list[str], *, timeout=90, stdin=None) -> dict:
    """Never inherit credentials; descendants inherit the same sandbox and limits."""
    work, cwd = work.resolve(), cwd.resolve()
    for name in ("tmp", "cache", "config", "texmf"):
        (work / name).mkdir(exist_ok=True)
    paths = [
        "/Library/TeX/texbin",
        "/Library/Developer/CommandLineTools/usr/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    env = {
        "PATH": ":".join(paths),
        "LANG": "en_US.UTF-8",
        "TMPDIR": str(work / "tmp"),
        "PAR_GLOBAL_TEMP": str(work / "tmp"),
        "TEXMFVAR": str(work / "cache"),
        "TEXMFCONFIG": str(work / "config"),
        "TEXMFHOME": str(work / "texmf"),
        "TEXINPUTS": ".:" + str(work / "texmf/tex/generic/qecgraph") + "//:",
        "BIBINPUTS": ".:" + str(work / "texmf/tex/generic/qecgraph") + "//:",
        "BSTINPUTS": ".:" + str(work / "texmf/tex/generic/qecgraph") + "//:",
        "TEXMFOUTPUT": str(cwd),
        "XDG_CONFIG_HOME": str(work / "config"),
        "openin_any": "p",
        "openout_any": "p",
    }
    log = work / "command.log"
    started = time.monotonic()
    with log.open("wb") as output:
        process = subprocess.Popen(
            _command(work, cwd, command),
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=_limits,
        )
        timed_out = False
        try:
            process.communicate(
                input=stdin.encode() if stdin is not None else None, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        finally:
            # A tool must not leave background descendants after it exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    raw = log.read_bytes()
    raw = raw.replace(str(work).encode(), b"<build>")
    return {
        "command": [arg.replace(str(work), "<build>") for arg in command],
        "exit": process.returncode,
        "timeout": timed_out,
        "seconds": round(time.monotonic() - started, 3),
        "log": raw,
    }
