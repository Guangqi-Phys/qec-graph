"""Provenance-preserving LaTeX extraction and typed QEC evidence graphs."""
from pathlib import Path

__version__ = "0.5.0"
PARSER_VERSION = "0.2.0"
__all__ = ["__version__", "split_project"]


def split_project(
    entry: str | Path,
    project_id: str,
    out: str | Path,
    project_root: str | Path | None = None,
    config_path: str | Path | None = None,
    *,
    force: bool = False,
) -> dict:
    """Public source-only splitter API; see :mod:`qecgraph.splitter` for details."""
    from .source.splitter import split_project as implementation

    return implementation(entry, project_id, out, project_root, config_path, force=force)
