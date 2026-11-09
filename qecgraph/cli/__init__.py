"""Command-line entry point for QEC Graph."""
from __future__ import annotations

import sqlite3
import sys
from collections.abc import Sequence

from .. import __version__
from .commands import HANDLERS
from .commands.workspace import uses_workspace, workspace_action
from .parser import UsageError, parse_command
from .render import WorkspaceProgress, print_json


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_command(argv)
        if args is None:
            return 0
    except UsageError as exc:
        print(f'error: {exc}. Run qec-graph --help for usage.', file=sys.stderr)
        return 64
    if args.command == 'version':
        print(f'qec-graph {__version__}')
        return 0
    workspace_command = uses_workspace(args)
    progress = WorkspaceProgress(args.command) if workspace_command and not args.json else None
    try:
        if workspace_command:
            return workspace_action(args, progress)
        return HANDLERS[args.command](args)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        if progress:
            return progress.finish(str(exc), 1)
        print_json({"error": str(exc)}, compact=True, stream=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if progress:
            return progress.finish('interrupted', 130)
        raise
    finally:
        if progress:
            progress.close()
