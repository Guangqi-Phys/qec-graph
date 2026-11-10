"""Compatibility shim; canonical implementation is :mod:`qecgraph.source.splitter`."""
from .source.splitter import *  # noqa: F401,F403
from .source.splitter import main  # noqa: F401


if __name__ == "__main__":
    main()
