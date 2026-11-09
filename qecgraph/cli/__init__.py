"""Command-line entry point for QEC Graph."""
from __future__ import annotations

import json
import os
import sqlite3
import sys

from .. import __version__
from ..query import context, dependencies, search, show
from ..splitter import split_project
from ..store import current_snapshot, ingest, snapshot_reference, validate_snapshot
from ..registry import Registry
from ..graph import read_json
from .parser import UsageError, parse_command
from .render import WorkspaceProgress, print_doctor, print_json, workspace_summary


_DAILY_WORKSPACE_COMMANDS = {'sync', 'status', 'validate'}
_WORKSPACE_WRITE_COMMANDS = {'init', 'sync', 'rebuild'}
_GRAPH_QUERY_COMMANDS = {'search', 'show', 'deps', 'impact', 'context'}


def _cli_command(*arguments):
    if getattr(sys, 'frozen', False):
        return [sys.executable, *arguments]
    return [sys.executable, '-m', 'qecgraph', *arguments]


def _workspace_session(args, **budgets):
    from ..workspace import Workspace
    from ..workspace_query import WorkspaceSession
    if args.snapshot or args.source_version_id or args.registry_revision:
        raise ValueError('Workspace tools use --release; store/corpus selectors are not applicable')
    machine = args.machine or Workspace(args.workspace).path('machine')
    return WorkspaceSession(machine, args.release, **budgets)


def _ai_session(args):
    if args.workspace or args.machine:
        return _workspace_session(args, max_nodes=args.session_max_nodes, max_depth=args.session_max_depth,
                                  max_chars=args.session_max_chars, max_results=args.session_max_results)
    if args.release:
        raise ValueError('--release requires --workspace or --machine')
    from ..ai_tools import ReadOnlySession
    return ReadOnlySession(store=args.store, corpus=args.corpus, snapshot_id=args.snapshot,
                           registry_revision=args.registry_revision, source_version_id=args.source_version_id,
                           max_nodes=args.session_max_nodes, max_depth=args.session_max_depth,
                           max_chars=args.session_max_chars, max_results=args.session_max_results)


def _workspace_query(args):
    if args.command == 'search':
        session = _workspace_session(args, max_results=args.limit)
        return session.invoke('qecgraph_search', {'query': args.query, 'kind': args.kind, 'limit': args.limit})
    if args.command == 'show':
        return _workspace_session(args).invoke('qec_get_entity', {'identifier': args.id_or_label})
    session = _workspace_session(args, max_nodes=args.max_nodes, max_depth=args.depth)
    tool = 'qec_get_context' if args.command == 'context' else 'qecgraph_' + args.command
    return session.invoke(tool, {'identifier': args.id_or_label, 'depth': args.depth,
                                 'max_nodes': args.max_nodes,
                                 'include_candidates': args.include_candidates})


def _command_object(path, required, optional=()):
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError("Input must be a JSON object")
    if missing := set(required) - value.keys():
        raise ValueError("Input is missing fields: " + ", ".join(sorted(missing)))
    if extra := value.keys() - (set(required) | set(optional)):
        raise ValueError("Unknown input fields: " + ", ".join(sorted(extra)))
    return value


def main(argv=None):
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
    workspace_command = (args.command in _WORKSPACE_WRITE_COMMANDS | {'status'}
                         or args.command == 'validate' and not args.store)
    progress = WorkspaceProgress(args.command) if workspace_command and not args.json else None
    try:
        if args.command == 'doctor':
            from ..maintenance import doctor
            from ..workspace import locate
            result = doctor(locate(args.workspace, default=os.environ.get('QECGRAPH_WORKSPACE')))
            if args.json:
                print_json(result)
            else:
                print_doctor(result)
            return result['suggested_exit_code']
        if args.command == 'snapshot':
            from ..maintenance import list_snapshots
            from ..workspace import locate
            workspace = None if args.store or args.corpus else locate(args.workspace, default=os.environ.get('QECGRAPH_WORKSPACE'))
            result = list_snapshots(store=args.store, corpus=args.corpus, workspace=workspace)
            print_json(result)
            return 0
        if args.command == 'inputs':
            from ..workspace import Workspace, locate
            ws = Workspace(locate(args.workspace, default=os.environ.get('QECGRAPH_WORKSPACE')))
            result = (ws.list_inputs() if args.input_action == 'list'
                      else ws.move_quarantine(args.name, restore=args.input_action == 'restore'))
            print_json(result)
            return 0
        if workspace_command:
            if progress and not getattr(args, 'dry_run', False):
                progress.start()
            from ..workspace import CONFIG, Workspace, locate
            if getattr(args, 'snapshot', None):
                raise ValueError('--snapshot requires --store')
            options = {key: getattr(args, key) for key in ('no_ingest', 'dry_run', 'include_inputs', 'keep_inputs')
                       if hasattr(args, key)}
            default = os.environ.get('QECGRAPH_WORKSPACE') if args.command in _DAILY_WORKSPACE_COMMANDS else None
            ws = Workspace(locate(args.workspace, default=default))
            if args.command != 'init' and not ws.path(CONFIG).is_file():
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
                return progress.finish(*workspace_summary(args.command, result, code))
            print_json(result)
            return code
        if args.command == 'human-build':
            from ..human import build_human
            result = build_human(args.workspace, args.release)
            print_json(result)
            return 0 if result['status'] == 'current' else 2
        if args.command == 'asset-add':
            from ..workspace_assets import add_asset
            result = add_asset(args.workspace, args.input, media_type=args.media_type)
            print_json(result)
            return 0
        if args.command in {'extract-request', 'extract-submit', 'extract-review'}:
            from .. import semantic
            if args.command == 'extract-request':
                result = semantic.request_extraction(args.workspace, args.source_version, release=args.release,
                                                     max_chars=args.max_chars, offset=args.offset)
            elif args.command == 'extract-submit':
                result = semantic.submit_extraction(args.workspace, args.request_id, read_json(args.response))
            else:
                result = semantic.review_extraction(args.workspace, args.proposal_id, reviewer=args.reviewer,
                                                    decision=args.decision, rationale=args.rationale)
            print_json(result)
            return 0
        if args.command == 'workspace-migrate':
            from ..workspace_migration import migrate_corpus
            result = migrate_corpus(args.corpus, args.workspace, args.registry_revision)
            print_json(result)
            return 0
        if args.command in {'research-import', 'review-list', 'software-import-seed', 'software-coverage', 'software-refresh'}:
            from ..workspace import Workspace
            from ..research_store import load_records, publish_records
            ws = Workspace(args.workspace)
            ws.config()
            if args.command == 'software-import-seed':
                from ..software import adapt_seed, bundled_seed
                result = publish_records(ws.registry, adapt_seed(bundled_seed()))
            elif args.command == 'software-refresh':
                from ..software import refresh
                result = refresh(ws.registry, project_id=args.project_id, limit=args.limit, timeout=args.timeout)
            elif args.command == 'software-coverage':
                from ..software import coverage
                state, release = ws.registry.read()
                result = {'release_id': release, **coverage(r for r in load_records(ws.registry, state) if not r['is_synthetic'])}
            elif args.command == 'research-import':
                payload = read_json(args.input)
                if args.format == 'software-seed':
                    from ..software import adapt_seed
                    payload = adapt_seed(payload)
                elif args.format == 'synthetic-fixture':
                    from ..research import adapt_synthetic
                    payload = adapt_synthetic(payload)
                if not isinstance(payload, list):
                    raise ValueError('Research import expects a list of records')
                result = publish_records(ws.registry, payload)
            else:
                state, release = ws.registry.read()
                rows = [row for row in load_records(ws.registry, state)
                        if not row['is_synthetic'] and row['data'].get('review_status') == 'proposed']
                from ..semantic import queued
                result = {'release_id': release, 'proposals': rows, 'provider_drafts': queued(ws.root, state)}
            print_json(result)
            return 2 if result.get('status') == 'partial' else 0
        workspace_query = args.command in _GRAPH_QUERY_COMMANDS and (args.workspace or args.machine)
        if not workspace_query and args.command in _GRAPH_QUERY_COMMANDS | {'validate', 'audit-dependencies'}:
            if getattr(args, 'release', None):
                raise ValueError('--release requires --workspace or --machine')
            if getattr(args, 'corpus', None):
                if args.snapshot:
                    raise ValueError('--snapshot belongs to store queries; use --registry-revision for a corpus')
            else:
                if getattr(args, 'registry_revision', None) or getattr(args, 'source_version_id', None):
                    raise ValueError('Corpus scope arguments require --corpus')
                args.store = snapshot_reference(args.store, args.snapshot)
        if workspace_query:
            result = _workspace_query(args)
        elif args.command == 'lean-build':
            from ..lean import build_project
            result = build_project(args.project, args.out, lake=args.lake, export_declarations=not args.build_only)
        elif args.command == 'lean-import':
            from ..lean_integration import import_build
            mappings = read_json(args.mapping) if args.mapping else None
            if mappings is not None and isinstance(mappings, dict):
                mappings = [mappings]
            result = import_build(args.corpus, args.report, project_id=args.project_id, project=args.project,
                                  mappings=mappings, historical=args.historical)
        elif args.command == 'lean-status':
            from ..lean_integration import lean_record_states
            from ..status import review_states
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
            from ..mcp_server import serve_stdio
            return serve_stdio(_ai_session(args))
        elif args.command == 'query-tool':
            result = _ai_session(args).invoke(args.tool, read_json(args.arguments))
        elif args.command == 'watch':
            from ..watch import Watcher, run
            watcher = Watcher(args.entry, args.project_id, args.out, args.project_root, args.config, args.annotations, args.catalog,
                              strict=args.strict, debounce=0 if args.once else args.debounce)
            result = run(watcher, interval=args.interval, max_polls=1 if args.once else args.max_polls,
                         emit=lambda event: print_json(event, compact=True, flush=True))
            print_json(result, compact=True, flush=True)
            return result['suggested_exit_code']
        elif args.command == 'recover-store':
            from ..store import recover_store
            result = recover_store(args.store, remove_abandoned=args.remove_abandoned)
        elif args.command == 'validate-staged':
            from pathlib import Path
            from ..store import safe_relative
            if len(args.snapshot) != 64 or any(c not in '0123456789abcdef' for c in args.snapshot):
                raise ValueError('Invalid staged snapshot ID')
            result = validate_snapshot(safe_relative(Path(args.store).resolve(), 'staging/' + args.snapshot))
        elif args.command == 'audit-dependencies':
            from ..status import reviewed_cycles
            if args.corpus:
                from ..corpus import project
                graph_input, scope = project(args.corpus, args.registry_revision, args.source_version_id)
                graph = graph_input.graph
            else:
                from ..store import load_graph
                graph, _ = load_graph(args.store)
                scope = {'snapshot_id': graph['snapshot_id']}
            result = {'scope': scope, 'issues': reviewed_cycles(graph), 'policy': 'Active reviewed logic only; citation cycles are retained'}
        elif args.command == 'apply':
            from ..review import apply
            result = apply(args.corpus, args.proposal_id, args.review_id)
        elif args.command == 'review':
            from ..review import create_proposal
            payload = _command_object(args.input, ('changes', 'rationale'), ('expected_registry_revision',))
            result = create_proposal(args.corpus, actor={'id': args.actor_id, 'kind': args.actor_kind}, **payload)
        elif args.command == 'review-decide':
            from ..review import decide
            result = decide(args.corpus, args.proposal_id, actor={'id': args.actor_id, 'kind': args.actor_kind},
                            decision=args.decision, rationale=args.rationale, checked_scopes=args.checked_scope)
        elif args.command == 'check-css':
            from ..validators.qec import check_css
            result = check_css(read_json(args.hx), read_json(args.hz), read_json(args.lx) if args.lx else None,
                               read_json(args.lz) if args.lz else None, enumerate_distance=args.enumerate_distance, max_n=args.max_n)
            result['suggested_exit_code'] = 0 if result['passed'] else 2
        elif args.command == 'check-experiment':
            from ..validators.qec import check_experiment
            payload = _command_object(args.input, ('record', 'metric'))
            result = check_experiment(payload['record'], payload['metric'])
        elif args.command == 'codes':
            from ..domain_query import codes
            result = codes(args.corpus, registry_revision=args.registry_revision, n_min=args.n_min, n_max=args.n_max,
                           distance_at_least=args.distance_at_least, metric_definition_id=args.metric_definition_id,
                           sector=args.sector, construction=args.construction, limit=args.limit)
        elif args.command == 'validate-corpus':
            result = Registry(args.corpus).validate(args.registry_revision)
        elif args.command == 'migrate':
            from ..migrations import migrate
            result = migrate(args.input, args.out, source_root=args.source_root)
        elif args.command == 'migration-import':
            result = Registry(args.corpus).import_migration(args.input)
        elif args.command == 'record-add':
            result = Registry(args.corpus).add_record(read_json(args.input))
        elif args.command == 'claim-link':
            payload = _command_object(args.input, ('link_id', 'source_version_id', 'source_selector', 'claim_id'),
                                      ('claim_revision', 'assumptions', 'notation_scope'))
            result = Registry(args.corpus).link_claim(**payload)
        elif args.command == "register":
            result = Registry(args.corpus).register_source(args.work_id, args.source_version_id, args.store,
                                                         title=args.title, upstream_version=args.upstream_version)
        elif args.command == "ingest":
            result = ingest(args.entry, args.project_id, args.out, args.project_root, args.config, args.annotations, args.catalog,
                            strict=args.strict, incremental=args.incremental)
        elif args.command == "split":
            result = split_project(args.entry, args.project_id, args.out, args.project_root, args.config,
                                   strict=args.strict, incremental=args.incremental, force=args.force)
        elif getattr(args, 'corpus', None):
            from ..corpus import execute
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
        print_json(result)
        if 'ok' in result:
            return 1 if not result['ok'] else 2 if result['data'].get('extraction_status') == 'partial' else 0
        return result.get('suggested_exit_code', 2 if result.get("extraction_status") == "partial" else 0)
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
