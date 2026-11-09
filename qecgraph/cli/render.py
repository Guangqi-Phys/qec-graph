"""Terminal presentation for CLI commands."""
from __future__ import annotations

import json
import os
import sys
from threading import Event, Thread
from time import monotonic

from .. import __version__
from .errors import QecError, UsageError


class WorkspaceProgress:
    def __init__(self, action, *, quiet=False, color='auto', animate=True):
        self.action = action
        self.quiet = quiet
        self.stderr = sys.stderr
        terminal = sys.stdout.isatty() and self.stderr.isatty() and os.environ.get('TERM') != 'dumb'
        self.live = terminal and not quiet and animate
        forced = os.environ.get('FORCE_COLOR')
        self.color = (color == 'always' or color == 'auto' and not os.environ.get('NO_COLOR')
                      and (forced != '0' if forced is not None else terminal))
        self.state = (0, 1, 'Opening workspace')
        self.started = None
        self.stopped = Event()
        self.worker = None
        self.spinner, self.full, self.empty, self.ok, self.error = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏', '█', '░', '✓', '✗'
        try:
            (self.spinner + self.full + self.empty + self.ok + self.error).encode(self.stderr.encoding or 'ascii')
        except UnicodeEncodeError:
            self.spinner, self.full, self.empty, self.ok, self.error = '|/-\\', '#', '.', '+', '!'

    def start(self):
        if self.live:
            self.started = monotonic()
            self._draw(0)
            self.worker = Thread(target=self._animate, daemon=True)
            self.worker.start()

    def _animate(self):
        frame = 1
        while not self.stopped.wait(0.1):
            self._draw(frame)
            frame += 1

    def _paint(self, value, code):
        return f'\x1b[{code}m{value}\x1b[0m' if self.color else value

    def _draw(self, frame):
        done, total, message = self.state
        try:
            columns = os.get_terminal_size(self.stderr.fileno()).columns or 80
        except OSError:
            columns = 80
        spinner = self.spinner[frame % len(self.spinner)]
        label = f' {self.action}: {message}'
        elapsed = f'  {monotonic() - self.started:.1f}s'
        filled = 12 * done // total
        bar = self.full * filled + self.empty * (12 - filled)
        width = max(0, columns - 2)  # Leave one column free to avoid terminal wrapping.
        if total > 1 and len(label + elapsed) + len(bar) + 2 <= width:
            label += '  ' + bar
        if len(label + elapsed) <= width:
            label += elapsed
        print('\r\x1b[K' + self._paint(spinner, '36') + label[:width],
              end='', file=self.stderr, flush=True)

    def update(self, done, total, message):
        self.state = (done, total, message)

    def phase(self, message):
        self.update(*self.state[:2], message)

    def close(self):
        if self.started is not None:
            self.stopped.set()
            if self.worker is not None and self.worker.is_alive():
                self.worker.join()
            self.started = None
            print('\r\x1b[K', end='', file=self.stderr, flush=True)

    def finish(self, message, code):
        self.close()
        if self.quiet and not code:
            return 0
        message = ' '.join(''.join(char if char.isprintable() else ' ' for char in message).split())
        if len(message) > 180:
            message = message[:177] + '...'
        if self.live:
            marker = self._paint(self.error, '31') if code else self._paint(self.ok, '32')
        else:
            done, total, _ = self.state
            filled = 16 * done // total if code else 16
            marker = self._paint(f"[{'#' * filled}{'.' * (16 - filled)}]", '31' if code else '32')
        outcome = 'ERROR: ' + message if code else 'OK' + (f' ({message})' if message else '')
        print(f'{marker} {self.action}: {outcome}', file=self.stderr if code else sys.stdout)
        return code


def _input_problem(row):
    if row.get('cleanup_error') or row.get('retained_claim'):
        problem = row.get('cleanup_error') or 'input could not be restored'
    elif row.get('source_version_conflict'):
        problem = 'conflicting source version'
    elif not row.get('processing_completed'):
        problem = next((item['message'] for item in row.get('diagnostics', [])
                        if item['severity'] == 'error'), None)
        problem = problem or row.get('reason') or row['status'].replace('_', ' ')
    else:
        return None
    name = row.get('input') or row.get('archive_sha256', '')[:12]
    return f'{name}: {problem}' if name else problem


def workspace_summary(action, result, code):
    if result['status'] == 'already_initialized':
        return 'workspace already initialized', code
    if result['status'] == 'planned':
        return f"{len(result['inputs'])} inbox files, {result['pending_claims']} pending claims", code
    if action == 'validate':
        if not code:
            return '', 0
        issue = next((item for item in result.get('issues', []) if item.get('severity') != 'warning'), {})
        return issue.get('message') or issue.get('code') or 'workspace validation failed', code
    if action == 'status':
        materials = result['materials']
        count = len(materials)
        ready = sum(row.get('processing_completed', False) for row in materials)
        problem = next(filter(None, (_input_problem(row) for row in materials if not row.get('quarantined'))), None)
        summary = f'{ready}/{count} packages indexed'
        if held := result.get('quarantined_inputs'):
            summary += f'; {len(held)} quarantined'
        if problem:
            summary += f'; {problem}'
        return summary, code
    if code:
        inputs = result.get('sync', {}).get('inputs', []) + result.get('inputs', [])
        problem = next(filter(None, map(_input_problem, inputs)), None)
        human = result.get('human', {})
        if not problem and human.get('status') == 'superseded':
            return 'a newer release was published; run qec-graph human build to refresh the vault', code
        return (problem or human.get('error') or 'could not refresh workspace views'), code
    counts = result['counts']
    return f"{counts['processed']}/{counts['registered']} packages indexed", code

def print_json(result, *, compact=False, stream=None, flush=False):
    """Write one JSON value; compact mode keeps stream records on one line."""
    print(json.dumps(result, ensure_ascii=False, indent=None if compact else 2),
          file=stream, flush=flush)


def print_doctor(result):
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
        return progress.finish(str(error), error.exit_code)
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
