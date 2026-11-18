"""Read directory and archive inputs for native preparation."""

import base64
import gzip
import hashlib
import io
from pathlib import Path
import tarfile

from ..source.package import Limits, PackageError, SourceTree, read_bounded, unpack


def load_directory(root: Path) -> SourceTree:
    root = root.resolve()
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"refusing symlink in source tree: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith("../"):
            raise ValueError(f"source path escapes tree: {relative}")
        files[relative] = path.read_bytes()
    if not files:
        raise ValueError(f"source directory is empty: {root}")
    return SourceTree("directory", files)


def load_for_preparation(source: Path) -> tuple[SourceTree, list[dict]]:
    """Retain strict archive checks; repair only a verified missing tar footer."""
    if source.is_dir():
        return load_directory(source), []
    with source.open("rb") as stream:
        raw = read_bounded(stream, Limits().input_bytes)
    try:
        # latin1 is a format-recognition probe. unpack preserves original bytes.
        return unpack(raw, encoding="latin1"), []
    except PackageError as exc:
        if str(exc) != "Tar missing a valid zero-block trailer":
            raise
    data = raw
    if raw.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            data = read_bounded(stream, Limits().expanded_bytes)
    if len(data) % 512:
        raise ValueError("Legacy tar repair requires complete 512-byte records")
    # The strict reader already checked every visible member. Legacy writers may
    # leave nonzero record padding after the first end marker. Keep those bytes
    # in the audit record and reject a second archive rather than silently merge.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        list(archive)
        end = archive.offset
    tail = data[end:]
    for offset in range(0, len(tail) - 511, 512):
        try:
            header = tarfile.TarInfo.frombuf(
                tail[offset : offset + 512], "utf-8", "surrogateescape"
            )
        except tarfile.HeaderError:
            continue
        if header.name and data[:end].find(tail[offset : offset + 512]) < 0:
            raise ValueError(
                "Additional archive headers after the end marker require review"
            )
    repaired = data[:end] + bytes(1024)
    tree = unpack(repaired)
    return tree, [
        {
            "operation": "normalize_tar_zero_footer",
            "original_package_sha256": hashlib.sha256(raw).hexdigest(),
            "derived_tar_sha256": hashlib.sha256(repaired).hexdigest(),
            "appended_bytes": 1024,
            "retained_original_trailer_base64": base64.b64encode(tail).decode("ascii"),
        }
    ]
