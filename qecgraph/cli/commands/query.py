"""CLI handlers for query commands."""
from __future__ import annotations

from ...core.graph import read_json
from ...core.progress import phase
from ..errors import QueryError
from ..process import cli_command
from ..render import emit_report, print_json, report_error


def _workspace_session(args, **budgets):
    from ...workspace import Workspace
    from ...workspace_query import WorkspaceSession
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
    arguments = {name: getattr(args, name) for name in (*fields[subject], 'limit', 'offset', 'max_chars')
                 if getattr(args, name) is not None}
    return _emit_tool_result(args, _workspace_session(args).invoke('qec_find_' + subject, arguments))


def _ai_session(args):
    return _workspace_session(args, profile=args.profile or 'research', max_nodes=args.session_max_nodes,
                              max_depth=args.session_max_depth, max_chars=args.session_max_chars,
                              max_results=args.session_max_results)


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


def graph_query(args):
    return _emit_tool_result(args, _workspace_query(args))


def mcp_config(args):
    session = _ai_session(args)
    executable, *arguments = cli_command('mcp', 'serve')
    arguments += ['--machine', str(session.machine), '--release', session.release, '--profile', session.profile]
    for name in ('nodes', 'depth', 'chars', 'results'):
        arguments += ['--session-max-' + name, str(getattr(args, 'session_max_' + name))]
    result = {'mcpServers': {'qecgraph': {'command': executable, 'args': arguments}}}
    return emit_report(result, quiet=args.quiet)


def mcp_serve(args):
    from ...mcp.server import serve_stdio
    session = _ai_session(args)
    phase('MCP ready; waiting for requests', detail='Read-only stdio session')
    return serve_stdio(session, verbose=args.verbose)


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
