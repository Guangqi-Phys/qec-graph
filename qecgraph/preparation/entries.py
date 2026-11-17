"""Build entry sniffing only; compilation always receives the original bytes."""

from pathlib import PurePosixPath

from .harvmac import literal_input
from ..source.package import SourceTree
from ..source.prepare import select_entry, entry_candidates


def select_build_entry(tree, requested=None):
    if requested:
        return select_entry(tree, requested)
    probe = SourceTree(
        "entry_sniff",
        {
            p: raw.decode("utf-8", "backslashreplace").encode()
            if PurePosixPath(p).suffix.lower() in {"", ".tex"}
            else raw
            for p, raw in tree.files.items()
        },
    )
    if entry_candidates(probe):
        return select_entry(probe)
    candidates = [
        p
        for p, raw in probe.files.items()
        if PurePosixPath(p).suffix.lower() in {"", ".tex"}
        and literal_input(raw.decode())
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError("No unique native TeX entry; pass an explicit entry")
