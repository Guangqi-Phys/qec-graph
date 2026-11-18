"""Publish an already validated material directory with journaled recovery."""

import json
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp
from typing import Mapping
import uuid

from . import PREPARATION_VERSION
from .artifacts import SCHEMA, digest, safe_path


def _managed_output(directory: Path) -> bool:
    """Return true when a non-empty directory holds a prepare manifest."""
    manifest = directory / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schema") == SCHEMA
        and payload.get("rule_version") == PREPARATION_VERSION
    )


def _check_output_root(out: Path, source: Path | None, overwrite: bool) -> None:
    if out.is_symlink():
        raise ValueError(f"refusing symbolic-link output directory: {out}")
    if out.exists() and not out.is_dir():
        raise ValueError(f"output path is not a directory: {out}")
    if source is not None:
        target = out.resolve()
        origin = source.resolve()
        if origin == target or origin in target.parents:
            raise ValueError(f"output directory is inside the source: {out}")
        if target == origin or target in origin.parents:
            raise ValueError(f"source is inside the output directory: {out}")
    if out.is_dir() and any(out.iterdir()):
        if not overwrite and not _managed_output(out):
            raise ValueError(
                f"refusing to replace unmanaged output directory: {out}; "
                "pass --overwrite to replace it"
            )


def _journal_path(out: Path) -> Path:
    return out.parent / f".{out.name}.transaction.json"


def _write_journal(out: Path, payload: dict) -> None:
    journal = _journal_path(out)
    temporary = journal.with_name(journal.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(temporary, journal)


def _remove_journal(out: Path) -> None:
    try:
        _journal_path(out).unlink()
    except FileNotFoundError:
        pass


def _sibling(out: Path, name: object, prefix: str) -> Path | None:
    """Return a journal-named sibling created by this writer, or None."""
    if not isinstance(name, str) or "/" in name or not name.startswith(prefix):
        return None
    candidate = out.parent / name
    return candidate if candidate.parent == out.parent else None


def _manifest_digest(directory: Path) -> str | None:
    manifest = directory / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        return None
    try:
        return digest(manifest.read_bytes())
    except OSError:
        return None


def _artifacts_match(directory: Path, expected: dict) -> bool:
    for name, checksum in expected.items():
        try:
            path = directory / safe_path(name)
        except ValueError:
            return False
        if not path.is_file() or any(
            p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(directory)
        ):
            return False
        try:
            if digest(path.read_bytes()) != checksum:
                return False
        except OSError:
            return False
    return True


def _existing_outcome(out, payload, backup):
    current = _manifest_digest(out)
    if current == payload.get("new_manifest_sha256"):
        if not _artifacts_match(out, payload["artifacts"]):
            return "conflict"
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return "committed"
    if current is not None and current == payload.get("previous_manifest_sha256"):
        return "aborted"
    return "conflict"


def recover_output(out: Path) -> str | None:
    """Restore or clean up an interrupted publish described by the journal.

    Returns ``"restored"`` when the previous complete directory was put back,
    ``"committed"`` when the expected new directory is in place, ``"aborted"``
    when the old directory was never moved, ``"cleaned"`` when only staged
    leftovers were removed, ``"conflict"`` when the target is neither the
    expected new version nor the recorded old one, or None when there is no
    journal.

    A conflict keeps the journal and the backup so the only copy of the old
    result is never deleted because a directory merely exists.
    """
    journal = _journal_path(out)
    if journal.is_symlink():
        return "conflict"
    if not journal.is_file():
        return None
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "conflict"
    paths = _journal_directories(out, payload)
    if paths is None:
        return "conflict"
    staging, backup = paths
    outcome = _recover_directories(out, payload, staging, backup)
    if outcome == "conflict":
        return outcome
    shutil.rmtree(staging, ignore_errors=True)
    _remove_journal(out)
    return outcome


def _journal_directories(out, payload):
    if (
        not isinstance(payload, dict)
        or payload.get("out") != out.name
        or not isinstance(payload.get("artifacts"), dict)
    ):
        return None
    staging = _sibling(out, payload.get("staging", ""), f".{out.name}.staging-")
    backup = _sibling(out, payload.get("backup"), f".{out.name}.backup-")
    if (
        staging is None
        or staging.is_symlink()
        or out.is_symlink()
        or (backup is not None and backup.is_symlink())
        or payload["artifacts"].get("manifest.json")
        != payload.get("new_manifest_sha256")
        or not isinstance(payload.get("new_manifest_sha256"), str)
    ):
        return None
    return staging, backup


def _recover_directories(out, payload, staging, backup):
    if out.exists():
        return _existing_outcome(out, payload, backup) if out.is_dir() else "conflict"
    if backup is not None and backup.is_dir():
        os.replace(backup, out)
        return "restored"
    if staging.is_dir():
        if not _artifacts_match(staging, payload["artifacts"]):
            return "conflict"
        os.replace(staging, out)
    return "cleaned"


def _write_artifacts(directory: Path, artifacts: Mapping[str, bytes]) -> None:
    for name, data in artifacts.items():
        path = directory / name
        if Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
            raise ValueError("Unsafe managed artifact path")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def publish_artifacts(
    artifacts: Mapping[str, bytes], out: Path, *, source=None, overwrite=False
):
    """Publish one current material directory."""
    if recover_output(out) == "conflict":
        raise ValueError(
            "Interrupted material publication conflicts with existing output"
        )
    _check_output_root(out, source, overwrite)
    out.parent.mkdir(parents=True, exist_ok=True)
    previous_manifest = _manifest_digest(out) if out.is_dir() else None
    staging = Path(mkdtemp(dir=out.parent, prefix=f".{out.name}.staging-"))
    journal = {
        "out": out.name,
        "staging": staging.name,
        "backup": None,
        "phase": "staged",
        "new_manifest_sha256": digest(artifacts["manifest.json"]),
        "previous_manifest_sha256": previous_manifest,
        "artifacts": {name: digest(data) for name, data in artifacts.items()},
    }
    backup: Path | None = None
    try:
        _write_artifacts(staging, artifacts)
        _write_journal(out, journal)
        if out.exists():
            backup = out.parent / f".{out.name}.backup-{uuid.uuid4().hex[:12]}"
            journal["backup"] = backup.name
            journal["phase"] = "backup"
            _write_journal(out, journal)
            os.replace(out, backup)
            try:
                os.replace(staging, out)
            except BaseException:
                os.replace(backup, out)
                _remove_journal(out)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            os.replace(staging, out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if out.is_dir():
            _remove_journal(out)
