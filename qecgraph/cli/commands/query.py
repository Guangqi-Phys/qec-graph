"""CLI handlers for query commands."""
from __future__ import annotations

from ...graph import read_json
from ...query import context, dependencies, search, show
from ...store import current_snapshot, snapshot_reference, validate_snapshot
from ..errors import QueryError
from ..process import cli_command
from ..render import emit_report, print_json, report_error


def _workspace_session(args, **budgets):
    from ...workspace import Workspace
    from ...workspace_query import WorkspaceSession
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
    from ...ai_tools import ReadOnlySession
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


def _select_store_snapshot(args):
    if getattr(args, 'release', None):
        raise ValueError('--release requires --workspace or --machine')
    if getattr(args, 'corpus', None):
        if args.snapshot:
            raise ValueError('--snapshot belongs to store queries; use --registry-revision for a corpus')
    else:
        if getattr(args, 'registry_revision', None) or getattr(args, 'source_version_id', None):
            raise ValueError('Corpus scope arguments require --corpus')
        args.store = snapshot_reference(args.store, args.snapshot)


def graph_query(args):
    if args.workspace or args.machine:
        return _emit_tool_result(args, _workspace_query(args))
    _select_store_snapshot(args)
    if getattr(args, 'corpus', None):
        from ...corpus import execute
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
    elif args.command == "context":
        result = context(args.store, args.id_or_label, args.depth, args.include_candidates, args.max_nodes)
    else:
        result = dependencies(args.store, args.id_or_label, args.depth, args.include_candidates,
                              args.command == "impact", args.max_nodes)
    return emit_report(result, quiet=args.quiet)


def validate_store(args):
    _select_store_snapshot(args)
    return emit_report(validate_snapshot(current_snapshot(args.store)), quiet=args.quiet)


def audit_dependencies(args):
    _select_store_snapshot(args)
    from ...status import reviewed_cycles
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
    from ...mcp_server import serve_stdio
    return serve_stdio(_ai_session(args))


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
