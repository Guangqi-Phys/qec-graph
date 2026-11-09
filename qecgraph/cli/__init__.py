"""Command-line entry point for QEC Graph."""
from __future__ import annotations

import sys
from collections.abc import Sequence

from .. import __version__
from .commands import HANDLERS
from .commands.workspace import uses_workspace, workspace_action
from .errors import InternalError, Interrupted, UsageError, classify
from .parser import parse_command
from .render import WorkspaceProgress, report_alias, report_error


def main(argv: Sequence[str] | None = None, *, entrypoint: tuple[str, str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_command(argv, entrypoint=entrypoint)
        if args is None:
            return 0
    except UsageError as exc:
        options = argv[:argv.index('--')] if '--' in argv else argv
        return report_error(exc, exc.command, json_mode='--json' in options)
    if args.command == 'version':
        if not args.quiet:
            print(f'qec-graph {__version__}')
        return 0
    report_alias(args.alias)
    workspace_command = uses_workspace(args)
    progress = None
    if workspace_command and not args.json:
        progress = WorkspaceProgress(args.command, quiet=args.quiet, color=args.color, animate=not args.verbose)
    if args.verbose:
        print(f'qec-graph: running {args.command}', file=sys.stderr, flush=True)
    try:
        if workspace_command:
            return workspace_action(args, progress)
        return HANDLERS[args.command](args)
    except Exception as exc:
        error = classify(exc)
        if isinstance(error, InternalError) and args.debug:
            raise
        return report_error(error, args.command, json_mode=args.json, progress=progress)
    except KeyboardInterrupt:
        return report_error(Interrupted('interrupted'), args.command, json_mode=args.json, progress=progress)
    finally:
        if progress:
            progress.close()
