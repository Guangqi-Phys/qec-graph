"""CLI reports; live activity rendering is owned by progress.py."""
from __future__ import annotations

import json
import os
import sys

from .. import __version__
from ..core.progress import hide
from .progress import WorkspaceProgress
from .errors import QecError, UsageError


def _input_problem(row):
    if row.get('cleanup_error') or row.get('retained_claim'):
        problem = row.get('cleanup_error') or 'input could not be restored'
    elif row.get('source_version_conflict'):
        problem = 'conflicting source version'
    elif not row.get('processing_completed'):
        problem = next((item['message'] for item in row.get('diagnostics', [])
                        if item['severity'] == 'error'), None)
        problem = problem or row.get('reason') or row['status'].replace('_', ' ')
        if reason := row.get('structure_recovery', {}).get('reason'):
            problem = reason.replace('_', ' ') + '; ' + problem
    elif row.get('ai_extraction', {}).get('errors'):
        problem = 'AI extraction pending; sync retries from the archive'
    else:
        return None
    name = row.get('input') or row.get('archive_sha256', '')[:12]
    return f'{name}: {problem}' if name else problem


def workspace_summary(action, result, code):
    if result['status'] == 'already_initialized':
        return 'workspace already initialized', code
    if result['status'] == 'initialized':
        return 'edit [ai] in qecgraph.toml, put packages in inputs/, and run qec-graph sync', code
    if result['status'] == 'planned':
        return f"{len(result['inputs'])} inbox files, {result['pending_claims']} pending claims", code
    if action == 'validate':
        if not code:
            return '', 0
        issue = next((item for item in result.get('issues', []) if item.get('severity') != 'warning'), {})
        return issue.get('message') or issue.get('code') or 'workspace validation failed', code
    if action == 'status':
        materials = result['materials']
        counts = result['counts']
        problem = next(filter(None, (_input_problem(row) for row in materials if not row.get('quarantined'))), None)
        summary = f"{counts['processed']}/{counts['registered']} packages indexed"
        if held := counts['quarantined']:
            summary += f'; {held} quarantined'
        if problem:
            summary += f'; {problem}'
        return summary, code
    if code:
        inputs = result.get('sync', {}).get('inputs', []) + result.get('inputs', [])
        problem = next(filter(None, map(_input_problem, inputs)), None)
        human = result.get('human', {})
        if not problem and human.get('status') == 'superseded':
            return 'a newer release was published; run qec-graph human build to refresh the vault', code
        return (problem or human.get('error')
                or 'workspace updated; generated views are stale; run qec-graph human build --json for details'), code
    counts = result['counts']
    return f"{counts['processed']}/{counts['registered']} packages indexed", code

def print_json(result, *, compact=False, stream=None, flush=False):
    """Write one JSON value; compact mode keeps stream records on one line."""
    hide()
    print(json.dumps(result, ensure_ascii=False, indent=None if compact else 2),
          file=stream, flush=flush)


def print_doctor(result):
    hide()
    print(f"QEC Graph {__version__} · {result['workspace']}")
    for name, check in result['checks'].items():
        details = ', '.join(f'{key}={value}' for key, value in check.items()
                            if key not in {'status', 'message', 'release_id'})
        print(f"{name}: {check.get('message') or details or check['status']}")
    if result['release_id']:
        print(f"Release: {result['release_id']}")


def emit_report(result, *, quiet=False, exit_code=None, compact=False):
    """Write the report and use its declared or legacy extraction exit code."""
    if exit_code is None:
        if 'ok' in result:
            exit_code = 1 if not result['ok'] else 2 if result['data'].get('extraction_status') == 'partial' else 0
        else:
            exit_code = result.get('suggested_exit_code', 2 if result.get('extraction_status') == 'partial' else 0)
    if exit_code or not quiet:
        print_json(result, compact=compact, flush=compact)
    return exit_code


def report_error(error: QecError, command: str | None, *, json_mode: bool,
                 progress: WorkspaceProgress | None = None) -> int:
    if json_mode:
        stream = sys.stderr if command == 'serve-mcp' else sys.stdout
        print_json(error.envelope(command), compact=True, stream=stream)
    elif progress:
        return progress.finish(str(error), error.exit_code, summary=True)
    elif isinstance(error, UsageError):
        print(f'error: {error}. {error.hint}', file=sys.stderr)
    else:
        # Preserve the existing error shape for scripts that use JSON-native
        # commands without requesting the versioned CLI envelope.
        print_json({'error': str(error)}, compact=True, stream=sys.stderr)
    return error.exit_code


def report_alias(alias: tuple[str, str] | None) -> None:
    preference = os.environ.get('QECGRAPH_DEPRECATIONS')
    if alias and (preference == '1' or preference != '0' and sys.stderr.isatty()):
        old, current = alias
        print(f'warning: qec-graph {old} is deprecated; use qec-graph {current}.', file=sys.stderr)
