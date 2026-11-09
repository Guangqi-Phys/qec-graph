from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from threading import Event, Thread
from time import monotonic

from .query import context, dependencies, search, show
from .splitter import split_project
from .store import current_snapshot, ingest, pin_snapshot, validate_snapshot
from .registry import Registry
from .graph import read_json


_DAILY_WORKSPACE_COMMANDS = {'sync', 'status', 'validate'}
_WORKSPACE_WRITE_COMMANDS = {'init', 'sync', 'rebuild'}


def _cli_command(*arguments):
    if getattr(sys, 'frozen', False):
        return [sys.executable, *arguments]
    return [sys.executable, '-m', 'qecgraph', *arguments]


class _WorkspaceProgress:
    def __init__(self, action):
        self.action = action
        self.stderr = sys.stderr
        self.live = sys.stdout.isatty() and self.stderr.isatty() and os.environ.get('TERM') != 'dumb'
        self.color = self.live and not os.environ.get('NO_COLOR')
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
        message = ' '.join(''.join(char if char.isprintable() else ' ' for char in message).split())
        if len(message) > 180:
            message = message[:177] + '...'
        if self.live:
            marker = self._paint(self.error, '31') if code else self._paint(self.ok, '32')
        else:
            done, total, _ = self.state
            filled = 16 * done // total if code else 16
            marker = f"[{'#' * filled}{'.' * (16 - filled)}]"
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


def _workspace_summary(action, result, code):
    if result['status'] == 'already_initialized':
        return 'workspace already initialized', code
    if action == 'validate':
        if not code:
            return '', 0
        issue = next((item for item in result.get('issues', []) if item.get('severity') != 'warning'), {})
        return issue.get('message') or issue.get('code') or 'workspace validation failed', code
    if action == 'status':
        materials = result['materials']
        count = len(materials)
        ready = sum(row.get('processing_completed', False) for row in materials)
        problem = next(filter(None, map(_input_problem, materials)), None)
        if problem:
            return f'{ready}/{count} packages indexed; {problem}', 2
        return f'{ready}/{count} packages indexed', code
    if code:
        inputs = result.get('sync', {}).get('inputs', []) + result.get('inputs', [])
        problem = next(filter(None, map(_input_problem, inputs)), None)
        human = result.get('human', {})
        return (problem or human.get('error') or 'could not refresh workspace views'), code
    counts = result['counts']
    return f"{counts['processed']}/{counts['registered']} packages indexed", code


def _add_query_scope(parser, *, workspace=False):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--store')
    group.add_argument('--corpus')
    if workspace:
        group.add_argument('--workspace')
        group.add_argument('--machine', help='Only the mounted machine directory (no workspace access)')
        parser.add_argument('--release')
    parser.add_argument('--snapshot', help='Fixed store snapshot ID')
    parser.add_argument('--registry-revision', help='Fixed corpus state revision')
    parser.add_argument('--source-version-id', help='Restrict corpus source scope')


def _add_ai_arguments(parser):
    _add_query_scope(parser, workspace=True)
    parser.add_argument('--session-max-nodes', type=int, default=100)
    parser.add_argument('--session-max-depth', type=int, default=4)
    parser.add_argument('--session-max-chars', type=int, default=64000)
    parser.add_argument('--session-max-results', type=int, default=50)


def _ai_session(args):
    if args.workspace or args.machine:
        from .workspace import Workspace
        from .workspace_query import WorkspaceSession
        if args.snapshot or args.source_version_id or args.registry_revision:
            raise ValueError('Workspace tools use --release; store/corpus selectors are not applicable')
        machine = args.machine or Workspace(args.workspace).path('machine')
        return WorkspaceSession(machine, args.release, max_nodes=args.session_max_nodes,
                                max_depth=args.session_max_depth, max_chars=args.session_max_chars,
                                max_results=args.session_max_results)
    if args.release:
        raise ValueError('--release requires --workspace or --machine')
    from .ai_tools import ReadOnlySession
    return ReadOnlySession(store=args.store, corpus=args.corpus, snapshot_id=args.snapshot,
                           registry_revision=args.registry_revision, source_version_id=args.source_version_id,
                           max_nodes=args.session_max_nodes, max_depth=args.session_max_depth,
                           max_chars=args.session_max_chars, max_results=args.session_max_results)


def _add_source_arguments(parser):
    parser.add_argument("entry")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--config")
    parser.add_argument('--strict', action='store_true', help='Keep partial extraction in staging without changing CURRENT')
    parser.add_argument('--incremental', action='store_true', help='Reuse content-checked per-file ASTs; rebuild semantic projections')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:2] == ['mcp', 'serve']:
        argv[:2] = ['serve-mcp']
    if argv[:2] == ['human', 'build']:
        argv[:2] = ['human-build']
    if argv[:2] in (['software', 'import-seed'], ['software', 'coverage'], ['software', 'refresh']):
        argv[:2] = ['software-' + argv[1]]
    if argv[:2] == ['review', 'list'] and '--corpus' not in argv:
        argv[:2] = ['review-list']
    parser = argparse.ArgumentParser(prog="qecgraph", description="LaTeX source blocks and typed QEC graphs with explicit evidence checks")
    sub = parser.add_subparsers(dest="command", required=True)
    for action in ('init', 'sync', 'rebuild', 'status'):
        workspace = sub.add_parser(action, help=f'{action.capitalize()} a managed QEC workspace')
        workspace.add_argument('--workspace')
        workspace.add_argument('--json', action='store_true', help='Print the detailed workspace report')
        if action != 'status':
            workspace.add_argument('--keep-inputs', action='store_true')
            workspace.add_argument('--no-human', action='store_true', help='Skip the separate Obsidian renderer')
        if action == 'init':
            workspace.add_argument('--no-ingest', action='store_true')
        if action == 'sync':
            workspace.add_argument('--dry-run', action='store_true')
        if action == 'rebuild':
            workspace.add_argument('--include-inputs', action='store_true')
    cmd = sub.add_parser('human-build', help='Render Obsidian pages from the current fixed machine release')
    cmd.add_argument('--workspace')
    cmd.add_argument('--release')
    cmd = sub.add_parser('asset-add', help='Copy one explicit non-human asset into the content-addressed machine store')
    cmd.add_argument('input')
    cmd.add_argument('--workspace')
    cmd.add_argument('--media-type', default='application/octet-stream')
    cmd = sub.add_parser('extract-request', help='Export bounded, provenance-bound source excerpts for an optional provider')
    cmd.add_argument('source_version')
    cmd.add_argument('--workspace')
    cmd.add_argument('--release')
    cmd.add_argument('--max-chars', type=int, default=24000)
    cmd.add_argument('--offset', type=int, default=0)
    cmd = sub.add_parser('extract-submit', help='Validate a local provider response and queue a draft')
    cmd.add_argument('request_id')
    cmd.add_argument('response')
    cmd.add_argument('--workspace')
    cmd = sub.add_parser('extract-review', help='Record an explicit human decision on an exact provider draft')
    cmd.add_argument('proposal_id')
    cmd.add_argument('--workspace')
    cmd.add_argument('--reviewer', required=True)
    cmd.add_argument('--decision', choices=['approve', 'reject'], required=True)
    cmd.add_argument('--rationale', required=True)
    cmd = sub.add_parser('workspace-migrate', help='Copy a legacy corpus into a new workspace; retain all exact revisions')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--workspace', required=True)
    cmd.add_argument('--registry-revision')
    for name in ('software-import-seed', 'software-coverage', 'software-refresh'):
        cmd = sub.add_parser(name, help='Manage the bounded software directory')
        cmd.add_argument('--workspace')
        if name == 'software-refresh':
            cmd.add_argument('--project-id')
            cmd.add_argument('--limit', type=int, default=20)
            cmd.add_argument('--timeout', type=int, default=8)
    cmd = sub.add_parser('research-import', help='Validate and publish exact research records without evidence promotion')
    cmd.add_argument('input')
    cmd.add_argument('--workspace')
    cmd.add_argument('--format', choices=['records', 'software-seed', 'synthetic-fixture'], default='records')
    cmd = sub.add_parser('review-list', help='List source-linked proposals without approving them')
    cmd.add_argument('--workspace')
    cmd = sub.add_parser('lean-build', help='Explicitly build/export/audit a pinned Lean project; never invoked by read tools')
    cmd.add_argument('--project', required=True)
    cmd.add_argument('--out', required=True)
    cmd.add_argument('--lake')
    cmd.add_argument('--build-only', action='store_true')
    cmd = sub.add_parser('lean-import', help='Import an actual Lean export with current input or explicit historical bindings')
    cmd.add_argument('report')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--project-id', required=True)
    cmd.add_argument('--project')
    cmd.add_argument('--mapping')
    cmd.add_argument('--historical', action='store_true')
    cmd = sub.add_parser('lean-status', help='Read Lean build freshness without executing Lean')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--registry-revision')
    cmd = sub.add_parser('mcp-config', help='Print a reviewable fixed-scope client config without editing user settings')
    _add_ai_arguments(cmd)
    cmd = sub.add_parser('serve-mcp', help='Serve only fixed-scope read tools over local MCP stdio')
    _add_ai_arguments(cmd)
    cmd = sub.add_parser('query-tool', help='Call the fixed-scope read-only AI contract from JSON')
    cmd.add_argument('tool')
    cmd.add_argument('--arguments', required=True, help='JSON file of tool arguments')
    _add_ai_arguments(cmd)
    cmd = sub.add_parser('watch', help='Debounced content polling; rebuild through the shared ingestion pipeline')
    _add_source_arguments(cmd)
    cmd.add_argument('--annotations')
    cmd.add_argument('--catalog')
    cmd.add_argument('--interval', type=float, default=0.5)
    cmd.add_argument('--debounce', type=float, default=0.25)
    cmd.add_argument('--max-polls', type=int)
    cmd.add_argument('--once', action='store_true')
    cmd = sub.add_parser('recover-store', help='Validate CURRENT and inventory abandoned tool-owned builds')
    cmd.add_argument('--store', required=True)
    cmd.add_argument('--remove-abandoned', action='store_true')
    cmd = sub.add_parser('validate-staged', help='Validate an explicitly selected staged snapshot')
    cmd.add_argument('--store', required=True)
    cmd.add_argument('--snapshot', required=True)
    cmd = sub.add_parser('audit-dependencies', help='Report SCCs only in active reviewed logical dependencies')
    _add_query_scope(cmd)
    cmd = sub.add_parser('apply', help='Atomically publish a reviewed proposal with input conflict checks')
    cmd.add_argument('proposal_id')
    cmd.add_argument('--review-id', required=True)
    cmd.add_argument('--corpus', required=True)
    cmd = sub.add_parser('review', help='Create an inspectable proposal, without applying changes')
    cmd.add_argument('input', help='JSON with changes and rationale')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--actor-id', required=True)
    cmd.add_argument('--actor-kind', choices=['ai', 'program', 'human'], default='ai')
    cmd = sub.add_parser('review-decide', help='Bind an explicit decision to an exact proposal')
    cmd.add_argument('proposal_id')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--actor-id', required=True)
    cmd.add_argument('--actor-kind', choices=['ai', 'program', 'human'], default='ai')
    cmd.add_argument('--decision', choices=['approve', 'reject'], required=True)
    cmd.add_argument('--rationale', required=True)
    cmd.add_argument('--checked-scope', choices=['statement', 'hypotheses', 'dependencies'], action='append', default=[])
    cmd = sub.add_parser('check-css', help='Validate binary check matrices; optionally enumerate a small distance')
    cmd.add_argument('--hx', required=True)
    cmd.add_argument('--hz', required=True)
    cmd.add_argument('--lx')
    cmd.add_argument('--lz')
    cmd.add_argument('--enumerate-distance', action='store_true')
    cmd.add_argument('--max-n', type=int, default=20)
    cmd = sub.add_parser('check-experiment', help='Check explicit experiment/metric JSON; no evidence promotion')
    cmd.add_argument('input')
    cmd = sub.add_parser('codes', help='Exact code constraints, metric and currently bound distance evidence')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--registry-revision')
    cmd.add_argument('--n-min', type=int)
    cmd.add_argument('--n-max', type=int)
    cmd.add_argument('--distance-at-least', type=int)
    cmd.add_argument('--metric-definition-id')
    cmd.add_argument('--sector', choices=['X', 'Z', 'joint'], default='joint')
    cmd.add_argument('--construction')
    cmd.add_argument('--limit', type=int, default=100)
    cmd = sub.add_parser('validate-corpus', help='Check typed records, references, sources and managed assets')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--registry-revision')
    cmd = sub.add_parser('migrate', help='Adapt legacy inputs into a new location with a rejection report')
    cmd.add_argument('input')
    cmd.add_argument('--out', required=True)
    cmd.add_argument('--source-root')
    cmd = sub.add_parser('migration-import', help='Import adapted records and managed assets atomically')
    cmd.add_argument('input')
    cmd.add_argument('--corpus', required=True)
    for name in ('record-add', 'claim-link'):
        cmd = sub.add_parser(name, help="Add an explicit record or provenance mapping from JSON")
        cmd.add_argument("input")
        cmd.add_argument("--corpus", required=True)
    cmd = sub.add_parser("register", help="Archive a store as an explicit work/source version in a corpus")
    cmd.add_argument("--corpus", required=True)
    cmd.add_argument("--store", required=True)
    cmd.add_argument("--work-id", required=True)
    cmd.add_argument("--source-version-id", required=True)
    cmd.add_argument("--title")
    cmd.add_argument("--upstream-version")
    cmd = sub.add_parser("ingest", help="Parse a LaTeX project and write an immutable snapshot")
    _add_source_arguments(cmd)
    cmd.add_argument("--annotations")
    cmd.add_argument("--catalog", help="Directory of existing JSON records, such as the earlier starter records/")
    cmd = sub.add_parser("split", help="Write source-only semantic fragments and return their exact file paths")
    _add_source_arguments(cmd)
    cmd = sub.add_parser("search", help="Search titles, labels and text")
    cmd.add_argument("query")
    _add_query_scope(cmd)
    cmd.add_argument("--kind")
    cmd.add_argument("--limit", type=int, default=20)
    cmd = sub.add_parser("show", help="Read one node with its incoming/outgoing edges")
    cmd.add_argument("id_or_label")
    _add_query_scope(cmd)
    for name in ("deps", "impact", "context"):
        cmd = sub.add_parser(name)
        cmd.add_argument("id_or_label")
        _add_query_scope(cmd)
        cmd.add_argument("--depth", type=int, default=2)
        cmd.add_argument("--include-candidates", action="store_true")
        cmd.add_argument("--max-nodes", type=int, default=60)
    cmd = sub.add_parser("validate", help="Validate hashes, source spans, endpoints and SQLite")
    group = cmd.add_mutually_exclusive_group()
    group.add_argument("--store")
    group.add_argument("--workspace")
    cmd.add_argument('--snapshot')
    cmd.add_argument('--json', action='store_true', help='Print the detailed workspace report')
    args = parser.parse_args(argv)
    daily = args.command in _DAILY_WORKSPACE_COMMANDS and argv[1:] in ([], ['--json'])
    interactive_write = (args.command in _WORKSPACE_WRITE_COMMANDS and sys.stdout.isatty()
                         and not getattr(args, 'dry_run', False))
    progress = _WorkspaceProgress(args.command) if (daily or interactive_write) and not args.json else None
    try:
        if args.command in _WORKSPACE_WRITE_COMMANDS | {'status'} or (args.command == 'validate' and not args.store):
            if progress:
                progress.start()
            from .workspace import CONFIG, Workspace, locate
            if getattr(args, 'snapshot', None):
                raise ValueError('--snapshot requires --store')
            options = {key: getattr(args, key) for key in ('no_ingest', 'dry_run', 'include_inputs', 'keep_inputs')
                       if hasattr(args, key)}
            default = os.environ.get('QECGRAPH_WORKSPACE') if args.command in _DAILY_WORKSPACE_COMMANDS else None
            ws = Workspace(locate(args.workspace, default=default))
            if daily and not ws.path(CONFIG).is_file():
                raise ValueError('No initialized workspace found. Set QECGRAPH_WORKSPACE or use --workspace.')
            if progress and args.command != 'status':
                options['progress'] = progress.update
            result = getattr(ws, args.command)(**options)
            if args.command in _WORKSPACE_WRITE_COMMANDS and result.get('release_id') and not args.no_human:
                if progress:
                    progress.phase('Rendering Obsidian views')
                import subprocess
                try:
                    render = subprocess.run(
                        _cli_command('human-build', '--workspace', str(ws.root), '--release', result['release_id']),
                        capture_output=True, text=True, timeout=120, check=False)
                    result['human'] = json.loads(render.stdout)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    result['human'] = {'status': 'human_stale', 'release_id': result['release_id']}
            code = 2 if (result['status'] in {'partial_batch', 'invalid'}
                         or result.get('human', {}).get('status') == 'human_stale') else 0
            if progress:
                return progress.finish(*_workspace_summary(args.command, result, code))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return code
        if args.command == 'human-build':
            from .human import build_human
            result = build_human(args.workspace, args.release)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['status'] == 'current' else 2
        if args.command == 'asset-add':
            from .workspace_assets import add_asset
            result = add_asset(args.workspace, args.input, media_type=args.media_type)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command in {'extract-request', 'extract-submit', 'extract-review'}:
            from . import semantic
            if args.command == 'extract-request':
                result = semantic.request_extraction(args.workspace, args.source_version, release=args.release,
                                                     max_chars=args.max_chars, offset=args.offset)
            elif args.command == 'extract-submit':
                result = semantic.submit_extraction(args.workspace, args.request_id, read_json(args.response))
            else:
                result = semantic.review_extraction(args.workspace, args.proposal_id, reviewer=args.reviewer,
                                                    decision=args.decision, rationale=args.rationale)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'workspace-migrate':
            from .workspace_migration import migrate_corpus
            result = migrate_corpus(args.corpus, args.workspace, args.registry_revision)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command in {'research-import', 'review-list', 'software-import-seed', 'software-coverage', 'software-refresh'}:
            from .workspace import Workspace
            from .research_store import load_records, publish_records
            ws = Workspace(args.workspace)
            ws.config()
            if args.command == 'software-import-seed':
                from .software import adapt_seed, bundled_seed
                result = publish_records(ws.registry, adapt_seed(bundled_seed()))
            elif args.command == 'software-refresh':
                from .software import refresh
                result = refresh(ws.registry, project_id=args.project_id, limit=args.limit, timeout=args.timeout)
            elif args.command == 'software-coverage':
                from .software import coverage
                state, release = ws.registry.read()
                result = {'release_id': release, **coverage(r for r in load_records(ws.registry, state) if not r['is_synthetic'])}
            elif args.command == 'research-import':
                payload = read_json(args.input)
                if args.format == 'software-seed':
                    from .software import adapt_seed
                    payload = adapt_seed(payload)
                elif args.format == 'synthetic-fixture':
                    from .research import adapt_synthetic
                    payload = adapt_synthetic(payload)
                if not isinstance(payload, list):
                    raise ValueError('Research import expects a list of records')
                result = publish_records(ws.registry, payload)
            else:
                state, release = ws.registry.read()
                rows = [row for row in load_records(ws.registry, state)
                        if not row['is_synthetic'] and row['data'].get('review_status') == 'proposed']
                from .semantic import queued
                result = {'release_id': release, 'proposals': rows, 'provider_drafts': queued(ws.root, state)}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2 if result.get('status') == 'partial' else 0
        if args.command in {'search', 'show', 'deps', 'impact', 'context', 'validate', 'audit-dependencies'}:
            if getattr(args, 'corpus', None):
                if args.snapshot:
                    raise ValueError('--snapshot belongs to store queries; use --registry-revision for a corpus')
            else:
                if getattr(args, 'registry_revision', None) or getattr(args, 'source_version_id', None):
                    raise ValueError('Corpus scope arguments require --corpus')
                args.store = pin_snapshot(args.store, args.snapshot)
        if args.command == 'lean-build':
            from .lean import build_project
            result = build_project(args.project, args.out, lake=args.lake, export_declarations=not args.build_only)
        elif args.command == 'lean-import':
            from .lean_integration import import_build
            mappings = read_json(args.mapping) if args.mapping else None
            if mappings is not None and isinstance(mappings, dict):
                mappings = [mappings]
            result = import_build(args.corpus, args.report, project_id=args.project_id, project=args.project,
                                  mappings=mappings, historical=args.historical)
        elif args.command == 'lean-status':
            from .lean_integration import lean_record_states
            from .status import review_states
            registry = Registry(args.corpus)
            state, fixed = registry.read(args.registry_revision)
            records = registry.records_from_state(state)
            reviews = review_states(registry, state, records)
            result = {'registry_revision': fixed, 'records': lean_record_states(registry, state, records, reviews),
                      'scope': 'read-only freshness; no Lean process or semantic approval'}
        elif args.command == 'mcp-config':
            from pathlib import Path
            session = _ai_session(args)
            executable, *arguments = _cli_command('serve-mcp')
            if args.workspace or args.machine:
                arguments += ['--machine', str(session.machine), '--release', session.release]
            elif args.corpus:
                arguments += ['--corpus', str(Path(args.corpus).resolve()), '--registry-revision', session.scope['registry_revision']]
                if args.source_version_id:
                    arguments += ['--source-version-id', args.source_version_id]
            else:
                arguments += ['--store', str(Path(args.store).resolve()), '--snapshot', session.scope['snapshot_id']]
            for name in ('nodes', 'depth', 'chars', 'results'):
                arguments += ['--session-max-' + name, str(getattr(args, 'session_max_' + name))]
            result = {'mcpServers': {'qecgraph': {'command': executable, 'args': arguments}}}
        elif args.command == 'serve-mcp':
            from .mcp_server import serve_stdio
            return serve_stdio(_ai_session(args))
        elif args.command == 'query-tool':
            result = _ai_session(args).invoke(args.tool, read_json(args.arguments))
        elif args.command == 'watch':
            from .watch import Watcher, run
            watcher = Watcher(args.entry, args.project_id, args.out, args.project_root, args.config, args.annotations, args.catalog,
                              strict=args.strict, debounce=0 if args.once else args.debounce)
            result = run(watcher, interval=args.interval, max_polls=1 if args.once else args.max_polls,
                         emit=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return result['suggested_exit_code']
        elif args.command == 'recover-store':
            from .store import recover_store
            result = recover_store(args.store, remove_abandoned=args.remove_abandoned)
        elif args.command == 'validate-staged':
            from pathlib import Path
            from .store import safe_relative
            if len(args.snapshot) != 64 or any(c not in '0123456789abcdef' for c in args.snapshot):
                raise ValueError('Invalid staged snapshot ID')
            result = validate_snapshot(safe_relative(Path(args.store).resolve(), 'staging/' + args.snapshot))
        elif args.command == 'audit-dependencies':
            from .status import reviewed_cycles
            if args.corpus:
                from .corpus import project
                graph_input, scope = project(args.corpus, args.registry_revision, args.source_version_id)
                graph = graph_input.graph
            else:
                from .store import load_graph
                graph, _ = load_graph(args.store)
                scope = {'snapshot_id': graph['snapshot_id']}
            result = {'scope': scope, 'issues': reviewed_cycles(graph), 'policy': 'Active reviewed logic only; citation cycles are retained'}
        elif args.command == 'apply':
            from .review import apply
            result = apply(args.corpus, args.proposal_id, args.review_id)
        elif args.command == 'review':
            from .review import create_proposal
            result = create_proposal(args.corpus, actor={'id': args.actor_id, 'kind': args.actor_kind}, **read_json(args.input))
        elif args.command == 'review-decide':
            from .review import decide
            result = decide(args.corpus, args.proposal_id, actor={'id': args.actor_id, 'kind': args.actor_kind},
                            decision=args.decision, rationale=args.rationale, checked_scopes=args.checked_scope)
        elif args.command == 'check-css':
            from .validators.qec import check_css
            result = check_css(read_json(args.hx), read_json(args.hz), read_json(args.lx) if args.lx else None,
                               read_json(args.lz) if args.lz else None, enumerate_distance=args.enumerate_distance, max_n=args.max_n)
            result['suggested_exit_code'] = 0 if result['passed'] else 2
        elif args.command == 'check-experiment':
            from .validators.qec import check_experiment
            payload = read_json(args.input)
            result = check_experiment(payload['record'], payload['metric'])
        elif args.command == 'codes':
            from .domain_query import codes
            result = codes(args.corpus, registry_revision=args.registry_revision, n_min=args.n_min, n_max=args.n_max,
                           distance_at_least=args.distance_at_least, metric_definition_id=args.metric_definition_id,
                           sector=args.sector, construction=args.construction, limit=args.limit)
        elif args.command == 'validate-corpus':
            result = Registry(args.corpus).validate(args.registry_revision)
        elif args.command == 'migrate':
            from .migrations import migrate
            result = migrate(args.input, args.out, source_root=args.source_root)
        elif args.command == 'migration-import':
            result = Registry(args.corpus).import_migration(args.input)
        elif args.command == 'record-add':
            result = Registry(args.corpus).add_record(read_json(args.input))
        elif args.command == 'claim-link':
            result = Registry(args.corpus).link_claim(**read_json(args.input))
        elif args.command == "register":
            result = Registry(args.corpus).register_source(args.work_id, args.source_version_id, args.store,
                                                         title=args.title, upstream_version=args.upstream_version)
        elif args.command == "ingest":
            result = ingest(args.entry, args.project_id, args.out, args.project_root, args.config, args.annotations, args.catalog,
                            strict=args.strict, incremental=args.incremental)
        elif args.command == "split":
            result = split_project(args.entry, args.project_id, args.out, args.project_root, args.config,
                                   strict=args.strict, incremental=args.incremental)
        elif getattr(args, 'corpus', None):
            from .corpus import execute
            result = execute(args.corpus, args.command, getattr(args, 'id_or_label', None),
                             registry_revision=args.registry_revision, source_version_id=args.source_version_id,
                             text=getattr(args, 'query', None), kind=getattr(args, 'kind', None),
                             limit=getattr(args, 'limit', 20), depth=getattr(args, 'depth', 2),
                             include_candidates=getattr(args, 'include_candidates', False),
                             max_nodes=getattr(args, 'max_nodes', 60))
        elif args.command == "search":
            result = search(args.store, args.query, args.kind, args.limit)
        elif args.command == "show":
            result = show(args.store, args.id_or_label)
        elif args.command == "validate":
            result = validate_snapshot(current_snapshot(args.store))
        elif args.command == "context":
            result = context(args.store, args.id_or_label, args.depth, args.include_candidates, args.max_nodes)
        else:
            result = dependencies(args.store, args.id_or_label, args.depth, args.include_candidates,
                                  args.command == "impact", args.max_nodes)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if 'ok' in result:
            return 1 if not result['ok'] else 2 if result['data'].get('extraction_status') == 'partial' else 0
        return result.get('suggested_exit_code', 2 if result.get("extraction_status") == "partial" else 0)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        if progress:
            return progress.finish(str(exc), 1)
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if progress:
            return progress.finish('interrupted', 130)
        raise
    finally:
        if progress:
            progress.close()


if __name__ == "__main__":
    raise SystemExit(main())
