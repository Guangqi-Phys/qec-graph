"""Command-line entry point for QEC Graph."""
from __future__ import annotations

import sys
from collections.abc import Sequence

from .. import __version__
from ..core.progress import reporting, task
from .commands import HANDLERS
from .commands.workspace import uses_workspace, workspace_action
from .errors import InternalError, Interrupted, UsageError, classify
from .parser import parse_command
from .progress import ACTIVITIES, CommandProgress
from .render import print_json, report_alias, report_error


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
        if args.json:
            print_json({'name': 'qec-graph', 'version': __version__}, compact=True)
        elif not args.quiet:
            print(f'qec-graph {__version__}')
        return 0
    report_alias(args.alias)
    workspace_command = uses_workspace(args)
    mode = args.progress
    if args.command == 'serve-mcp' and mode == 'auto' and sys.stderr.isatty():
        mode = 'plain'  # Service logs and incoming stdio must never fight a live region.
    progress = CommandProgress(args.display_command, quiet=args.quiet, color=args.color,
                               mode=mode, verbose=args.verbose)
    progress.start()
    summary = progress if workspace_command and not args.json else None
    activity = ACTIVITIES[args.command]
    if args.command == 'inputs':
        activity = {'list': 'Inspecting inbox packages', 'quarantine': 'Quarantining input package',
                    'restore': 'Restoring input package'}[args.input_action]
    elif args.command == 'sync' and args.dry_run:
        activity = 'Previewing pending input packages'
    try:
        with reporting(progress.on_event if progress.enabled else None), task(activity):
            if workspace_command:
                code = workspace_action(args, summary)
            else:
                code = HANDLERS[args.command](args)
        if not summary:
            progress.finish('Stopped watching' if args.command == 'watch' else '', code=code)
        return code
    except Exception as exc:
        error = classify(exc)
        if isinstance(error, InternalError) and args.debug:
            raise
        progress.close()
        return report_error(error, args.command, json_mode=args.json, progress=summary)
    except KeyboardInterrupt:
        progress.close()
        return report_error(Interrupted('interrupted'), args.command, json_mode=args.json, progress=summary)
    finally:
        progress.close()
