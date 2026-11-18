"""Pure material identities, coordinates and serialized evidence primitives."""

from array import array
import hashlib
import json
from pathlib import PurePosixPath

from ..core.coordinates import SourceLines

SCHEMA = "qecgraph.prepare/3"
CROSS_REFERENCE_POLICY = "preserve_ambiguity/1"


class SourceIndex:
    """Cache hashes and coordinates once per file, not once per token."""

    def __init__(self, raw, encoding="utf-8"):
        self.text = raw.decode(encoding)
        self.encoding = encoding
        self.sha256 = digest(raw)
        self.lines = SourceLines(self.text)
        self.offsets = None
        if not self.text.isascii() or encoding != "utf-8":
            self.offsets = array("Q", [0])
            for char in self.text:
                self.offsets.append(self.offsets[-1] + len(char.encode(encoding)))

    def byte_at(self, offset):
        return self.offsets[offset] if self.offsets is not None else offset

    def span(self, path, start, end, *, layer="original"):
        return {
            "path": path,
            "sha256": self.sha256,
            "layer": layer,
            "encoding": self.encoding,
            "chars": [start, end],
            "bytes": [self.byte_at(start), self.byte_at(end)],
            "lines": [
                self.lines.line_at(start),
                self.lines.line_at(max(start, end - 1)),
            ],
        }


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


class ArtifactJSON:
    """Decode metadata once per validation or read of an artifact bundle."""

    def __init__(self, files: dict[str, bytes], *, manifest=None):
        self.files = files
        self._decoded = {} if manifest is None else {"manifest.json": manifest}

    def __getitem__(self, name):
        if name not in self._decoded:
            self._decoded[name] = json.loads(self.files[name])
        return self._decoded[name]

    def get(self, name, default=None):
        return self[name] if name in self.files else default


def safe_path(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or "\\" in name
        or "\x00" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError(f"Unsafe material path: {name!r}")
    return name


def compiled_bibliography(build):
    """Reuse only bibliography files emitted by the original build."""
    return {
        path.removeprefix("files/"): raw
        for path, raw in build.artifacts.items()
        if path.startswith("files/") and PurePosixPath(path).suffix in {".bbl", ".bib"}
    }


def pdf_text_pages(raw):
    return ["".join(page.split()) for page in raw.decode().split("\f")]


def pdf_text_hashes(pages):
    return [digest("\f".join(page).encode()) for page in pages]
