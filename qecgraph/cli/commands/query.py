"""CLI handlers for query commands."""
from __future__ import annotations

from ...core.graph import read_json
from ...query import QuerySession
from ...store import current_snapshot, snapshot_reference, validate_snapshot
from ..errors import QueryError, UsageError
from ..process import cli_command
from ..render import emit_report, print_json, report_error


def _workspace_session(args, **budgets):
    from ...workspace import Workspace
    from ...workspace_query import WorkspaceSession
    if any(getattr(args, flag, None) for flag in ('snapshot', 'source_version_id', 'registry_revision')):
        raise UsageError('Workspace tools use --release; store/corpus selectors are not applicable')
    machine = args.machine or Workspace(args.workspace).path('machine')
    return WorkspaceSession(machine, args.release, **budgets)


def research_query(args):
    fields = {
        'codes': ('n_min', 'n_max', 'distance_at_least', 'metric_id', 'metric_revision',
                  'evidence_policy', 'sector'),
        'performance': ('code_id', 'decoder_id', 'noise_model_id', 'metric_id', 'complete_only',
                        'coordinate_name', 'coordinate', 'selection'),
        'software': ('query', 'role'),
    }
    subject = args.command.removeprefix('query-')
    if subject == 'codes' and args.construction is not None:
        raise ValueError('--construction requires a legacy --corpus')
    arguments = {name: getattr(args, name) for name in (*fields[subject], 'limit', 'offset', 'max_chars')
                 if getattr(args, name) is not None}
    return _emit_tool_result(args, _workspace_session(args).invoke('qec_find_' + subject, arguments))


def _ai_session(args):
    if args.workspace or args.machine:
        return _workspace_session(args, max_nodes=args.session_max_nodes, max_depth=args.session_max_depth,
                                  max_chars=args.session_max_chars, max_results=args.session_max_results)
    if args.release:
        raise UsageError('--release requires --workspace or --machine')
    from ...mcp.ai_tools import ReadOnlySession
    return ReadOnlySession(store=args.store, corpus=args.corpus, snapshot_id=args.snapshot,
                           registry_revision=args.registry_revision, source_version_id=args.source_version_id,
                           max_nodes=args.session_max_nodes, max_depth=args.session_max_depth,
                           max_chars=args.session_max_chars, max_results=args.session_max_results)


def _workspace_query(args):
    if args.command == 'search':
        session = _workspace_session(args, max_results=args.limit)
        return session.invoke('qecgraph_search', {'query': args.query, 'kind': args.kind,
                                                'limit': args.limit, 'view': args.view})
    selector = {'identifier': args.id_or_label}
    revision = getattr(args, 'revision', None)
    if revision is not None:
        selector['revision'] = revision
    if args.command == 'show':
        return _workspace_session(args).invoke('qec_get_entity', selector)
    session = _workspace_session(args, max_nodes=args.max_nodes, max_depth=args.depth)
    tool = 'qec_get_context' if args.command == 'context' else 'qecgraph_' + args.command
    return session.invoke(tool, {**selector, 'depth': args.depth, 'max_nodes': args.max_nodes,
                                 'include_candidates': args.include_candidates})


def _select_store_snapshot(args):
    if getattr(args, 'release', None):
        raise UsageError('--release requires --workspace or --machine')
    if getattr(args, 'corpus', None):
        if args.snapshot:
            raise UsageError('--snapshot belongs to store queries; use --registry-revision for a corpus')
    else:
        if getattr(args, 'registry_revision', None) or getattr(args, 'source_version_id', None):
            raise UsageError('Corpus scope arguments require --corpus')
        args.store = snapshot_reference(args.store, args.snapshot)


def graph_query(args):
    if args.workspace or args.machine:
        return _emit_tool_result(args, _workspace_query(args))
    if getattr(args, 'view', 'raw') == 'reading':
        raise UsageError('--view reading requires --workspace or --machine')
    if getattr(args, 'revision', None) is not None:
        raise UsageError('--revision requires --workspace or --machine')
    _select_store_snapshot(args)
    selector = getattr(args, 'id_or_label', None)
    options = {'text': getattr(args, 'query', None), 'kind': getattr(args, 'kind', None),
               'limit': getattr(args, 'limit', 20), 'depth': getattr(args, 'depth', 2),
               'include_candidates': getattr(args, 'include_candidates', False),
               'max_nodes': getattr(args, 'max_nodes', 60)}
    if getattr(args, 'corpus', None):
        from ...corpus import execute
        result = execute(args.corpus, args.command, selector,
                         registry_revision=args.registry_revision, source_version_id=args.source_version_id,
                         **options)
    else:
        result = QuerySession(args.store).execute(args.command, selector, **options)
    return emit_report(result, quiet=args.quiet)


def validate_store(args):
    _select_store_snapshot(args)
    return emit_report(validate_snapshot(current_snapshot(args.store)), quiet=args.quiet)


def audit_dependencies(args):
    _select_store_snapshot(args)
    from ...domain.status import reviewed_cycles
    if args.corpus:
        from ...corpus import project
        graph_input, scope = project(args.corpus, args.registry_revision, args.source_version_id)
        graph = graph_input.graph
    else:
        from ...store import load_graph
        graph, _ = load_graph(args.store)
        scope = {'snapshot_id': graph['snapshot_id']}
    result = {'scope': scope, 'issues': reviewed_cycles(graph), 'policy': 'Active reviewed logic only; citation cycles are retained'}
    return emit_report(result, quiet=args.quiet)


def mcp_config(args):
    from pathlib import Path
    session = _ai_session(args)
    executable, *arguments = cli_command('mcp', 'serve')
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
    return emit_report(result, quiet=args.quiet)


def mcp_serve(args):
    from ...mcp.server import serve_stdio
    return serve_stdio(_ai_session(args), verbose=args.verbose)


def query_tool(args):
    result = _ai_session(args).invoke(args.tool, read_json(args.arguments))
    return _emit_tool_result(args, result)


def _emit_tool_result(args, result):
    if result['ok']:
        return emit_report(result, quiet=args.quiet)
    error = QueryError(result['error'])
    if args.json:
        return report_error(error, args.command, json_mode=True)
    print_json(result)
    return error.exit_code
