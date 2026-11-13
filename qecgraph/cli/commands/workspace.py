"""CLI handlers for workspace commands."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

from ...core.graph import strict_json_loads
from ...core.progress import task
from ..errors import UsageError
from ..process import cli_command
from ..render import emit_report, print_doctor, workspace_summary


_DAILY_WORKSPACE_COMMANDS = {'sync', 'status', 'validate'}
_WORKSPACE_WRITE_COMMANDS = {'init', 'sync', 'rebuild'}


def uses_workspace(args):
    return (args.command in _WORKSPACE_WRITE_COMMANDS | {'status'}
            or args.command == 'validate' and not args.store)


def doctor(args):
    from ...maintenance import doctor
    from ...workspace import locate
    result = doctor(locate(args.workspace, default=os.environ.get('QECGRAPH_WORKSPACE')))
    code = result['suggested_exit_code']
    if args.json:
        return emit_report(result, exit_code=code)
    if code or not args.quiet:
        print_doctor(result)
    return code


def snapshots(args):
    from ...maintenance import list_snapshots
    from ...workspace import locate
    workspace = None if args.store or args.corpus else locate(args.workspace, default=os.environ.get('QECGRAPH_WORKSPACE'))
    result = list_snapshots(store=args.store, corpus=args.corpus, workspace=workspace)
    return emit_report(result, quiet=args.quiet, exit_code=0)


def inputs(args):
    from ...workspace import Workspace, locate
    ws = Workspace(locate(args.workspace, default=os.environ.get('QECGRAPH_WORKSPACE')))
    result = (ws.list_inputs() if args.input_action == 'list'
              else ws.move_quarantine(args.name, restore=args.input_action == 'restore'))
    return emit_report(result, quiet=args.quiet, exit_code=0)


def _render_release(workspace, release):
    fallback = {'status': 'human_stale', 'release_id': release}
    try:
        process = subprocess.run(cli_command('human', 'build', '--workspace', str(workspace), '--release', release),
                                 capture_output=True, text=True, timeout=120, check=False)
        report = strict_json_loads(process.stdout)
    except subprocess.TimeoutExpired:
        return {**fallback, 'error': 'human build timed out after 120 seconds'}
    except (OSError, ValueError) as exc:
        return {**fallback, 'error': f'{type(exc).__name__}: {exc}'}
    if not isinstance(report, dict):
        return {**fallback, 'error': 'human build returned an invalid report'}
    error = report.get('error')
    if isinstance(error, str) and error.strip():
        fallback['error'] = error.strip()
    status = report.get('status')
    if status == 'current' and process.returncode == 0 and report.get('release_id') == release:
        return report
    if status == 'human_stale' and process.returncode == 2 and report.get('release_id') == release:
        return report
    if status == 'superseded' and process.returncode == 2 and report.get('target_release_id') == release:
        return report
    if 'error' not in fallback and process.stderr.strip():
        lines = process.stderr.strip().splitlines()
        fallback['error'] = 'human build failed: ' + lines[-1].strip()
    return fallback


def workspace_action(args, progress):
    from ...workspace import CONFIG, Workspace, locate
    if getattr(args, 'snapshot', None):
        raise UsageError('--snapshot requires --store')
    options = {key: getattr(args, key) for key in ('no_ingest', 'dry_run', 'include_inputs', 'keep_inputs')
               if hasattr(args, key)}
    if args.command == 'init':
        # init never discovers a parent workspace: an omitted path is the cwd.
        ws = Workspace(Path(args.workspace).expanduser().resolve() if args.workspace else Path.cwd())
    else:
        default = os.environ.get('QECGRAPH_WORKSPACE') if args.command in _DAILY_WORKSPACE_COMMANDS else None
        ws = Workspace(locate(args.workspace, default=default))
    if args.command != 'init' and not ws.path(CONFIG).is_file():
        raise ValueError('No initialized workspace found. Set QECGRAPH_WORKSPACE or use --workspace.')

    if args.command == 'init':
        result = ws.prepare()
    else:
        result = getattr(ws, args.command)(**options)
    if args.command in _WORKSPACE_WRITE_COMMANDS and result.get('release_id') and not args.no_human:
        with task('Rendering Obsidian views', retain=True) as stage:
            stage.phase('Waiting for the isolated renderer', detail='timeout 120s')
            result['human'] = _render_release(ws.root, result['release_id'])
            if result['human'].get('status') in ('human_stale', 'superseded'):
                stage.outcome('partial', detail=result['human'].get('error', result['human']['status']))
    renderer_failed = (args.command in _WORKSPACE_WRITE_COMMANDS
                       and result.get('human', {}).get('status') in ('human_stale', 'superseded'))
    code = 2 if result['status'] in {'partial_batch', 'invalid'} or renderer_failed else 0
    if progress:
        return progress.finish(*workspace_summary(args.command, result, code), summary=True)
    return emit_report(result, exit_code=code)


def human_build(args):
    from ...render.human import build_human
    result = build_human(args.workspace, args.release)
    return emit_report(result, quiet=args.quiet, exit_code=0 if result['status'] == 'current' else 2)


def asset_add(args):
    from ...workspace_assets import add_asset
    result = add_asset(args.workspace, args.input, media_type=args.media_type)
    return emit_report(result, quiet=args.quiet, exit_code=0)
