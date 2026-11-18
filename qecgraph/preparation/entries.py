"""Build entry sniffing only; compilation always receives the original bytes."""

import json
from pathlib import PurePosixPath
import re

from .harvmac import literal_input
from ..source.entry import select_main_document
from ..source.package import SourceTree


_DOCUMENT_CLASS = re.compile(r"\\(?:documentclass|documentstyle)\b")
_BEGIN_DOCUMENT = re.compile(r"\\begin\s*\{document\}")
_TEX_SUFFIXES = {"", ".tex"}


def _looks_like_tex(raw: bytes) -> bool:
    if b"\x00" in raw:
        return False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return bool(_DOCUMENT_CLASS.search(text) and _BEGIN_DOCUMENT.search(text))


def _readme_candidates(tree):
    try:
        payload = json.loads(tree.files.get("00README.json", b"{}"))
    except (ValueError, TypeError):
        return []
    sources = payload.get("sources") if isinstance(payload, dict) else None
    return (
        [
            name
            for item in sources
            if isinstance(item, dict) and item.get("usage") == "toplevel"
            if isinstance(name := item.get("filename"), str) and name in tree.files
            if _looks_like_tex(tree.files[name])
        ]
        if isinstance(sources, list)
        else []
    )


def _latex_candidates(tree):
    return _readme_candidates(tree) or [
        path
        for path, raw in sorted(tree.files.items())
        if PurePosixPath(path).suffix.lower() in _TEX_SUFFIXES and _looks_like_tex(raw)
    ]


def select_build_entry(tree, requested=None):
    if requested:
        if requested not in tree.files:
            raise ValueError(f"entry not found in source tree: {requested}")
        return requested
    probe = SourceTree(
        "entry_sniff",
        {
            p: raw.decode("utf-8", "backslashreplace").encode()
            if PurePosixPath(p).suffix.lower() in _TEX_SUFFIXES
            else raw
            for p, raw in tree.files.items()
        },
    )
    latex = _latex_candidates(probe)
    if latex:
        selected, _method = select_main_document(probe.files, latex)
        if selected is not None:
            return selected
        raise ValueError(
            "multiple TeX entry candidates; pass an explicit entry: "
            + ", ".join(latex[:8])
        )
    candidates = [
        p
        for p, raw in probe.files.items()
        if PurePosixPath(p).suffix.lower() in _TEX_SUFFIXES
        and literal_input(raw.decode())
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError("No unique native TeX entry; pass an explicit entry")
