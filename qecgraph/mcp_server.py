"""Compatibility shim; canonical implementation is :mod:`qecgraph.mcp.server`."""
from .mcp.server import *  # noqa: F401,F403
from .mcp.server import main  # noqa: F401


if __name__ == "__main__":
    main()
