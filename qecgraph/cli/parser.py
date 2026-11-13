"""Arguments and usage help for the command-line entry point."""
from __future__ import annotations

import argparse
from difflib import get_close_matches

from .. import __version__
from .errors import UsageError
from .help import GUIDE_URL, TOPICS, command_epilog


_QUICK_HELP = """Usage: qec-graph <command> [options]

  init       Create a workspace
  sync       Import source packages from inputs/
  status     Report import progress and failures
  validate   Check the current release
  search     Find source blocks and records
  mcp serve  Start the read-only MCP server
  ai status  Inspect the optional AI provider configuration

Run qec-graph --help for all commands or qec-graph help <command> for options."""


class _ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, global_options=True, **kwargs):
        kwargs.setdefault('formatter_class', argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)
        if not global_options:
            return
        self.add_argument('--json', action='store_true', default=argparse.SUPPRESS,
                          help='Print detailed reports and structured errors')
        self.add_argument('--debug', action='store_true', default=argparse.SUPPRESS,
                          help='Show a traceback for unexpected failures')
        self.add_argument('--verbose', action='store_true', default=argparse.SUPPRESS,
                          help='Show diagnostic progress on stderr')
        self.add_argument('--quiet', action='store_true', default=argparse.SUPPRESS,
                          help='Suppress progress and successful reports; keep errors and explicit JSON')
        self.add_argument('--color', choices=('auto', 'always', 'never'), default=argparse.SUPPRESS,
                          help='Control color in progress and summaries (default: auto)')
        self.add_argument('--progress', choices=('auto', 'plain', 'off'), default=argparse.SUPPRESS,
                          help='Activity on stderr: live terminal, plain log, or off (default: auto)')

    def error(self, message):
        raise UsageError(message)


def _add_query_scope(parser):
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--workspace', help='Path to the QEC workspace')
    scope.add_argument('--machine', help='Path to the mounted machine directory')
    parser.add_argument('--release', help='Exact workspace release ID; omit to use CURRENT')


def _add_research_scope(parser):
    _add_query_scope(parser)
    parser.add_argument('--limit', type=int, help='Maximum rows to return')
    parser.add_argument('--offset', type=int, help='Number of matching workspace rows to skip')
    parser.add_argument('--max-chars', type=int, help='Maximum Unicode codepoints in the workspace response data')


def _coordinate(value):
    try:
        return int(value)
    except ValueError:
        return float(value)


def _add_ai_arguments(parser):
    _add_query_scope(parser)
    parser.add_argument('--profile', choices=('research', 'compatible'),
                        help='Read tool profile (default: research)')
    parser.add_argument('--session-max-nodes', type=int, default=100,
        help='Maximum nodes per session result (default: %(default)s)')
    parser.add_argument('--session-max-depth', type=int, default=4,
        help='Maximum dependency depth (default: %(default)s)')
    parser.add_argument('--session-max-chars', type=int, default=64000,
        help='Maximum codepoints per session result (default: %(default)s)')
    parser.add_argument('--session-max-results', type=int, default=50,
        help='Maximum search rows per session result (default: %(default)s)')


def _add_source_arguments(parser):
    parser.add_argument("entry", help='Path to the root LaTeX file')
    parser.add_argument("--project-id", required=True, help='Stable project ID')
    parser.add_argument("--out", required=True, help='Output directory for the command result')
    parser.add_argument("--project-root", help='Root directory of the source tree')
    parser.add_argument("--config", help='Path to a LaTeX parser configuration file')
    parser.add_argument('--strict', action='store_true', help='Keep partial extraction in staging without changing CURRENT')
    parser.add_argument('--incremental', action='store_true', help='Reuse content-checked per-file ASTs; rebuild semantic projections')


_GROUPS = {
    'workspace': ('Manage a local QEC workspace', {
        'init': 'init', 'sync': 'sync', 'rebuild': 'rebuild', 'status': 'status',
        'validate': 'validate',
    }),
    'query': ('Search and trace evidence in a fixed scope', {
        'search': 'search', 'show': 'show', 'deps': 'deps', 'impact': 'impact',
        'context': 'context', 'codes': 'codes', 'performance': 'query-performance',
        'software': 'query-software',
    }),
    'mcp': ('Configure or serve read-only MCP tools', {
        'serve': 'serve-mcp', 'config': 'mcp-config',
    }),
    'human': ('Render human-readable views', {'build': 'human-build'}),
    'ai': ('Configure and test optional AI providers', {
        'test': 'ai-test', 'status': 'ai-status', 'config': 'ai-config', 'proposals': 'ai-proposals',
    }),
    'software': ('Manage the software directory', {
        'import-seed': 'software-import-seed', 'coverage': 'software-coverage',
        'refresh': 'software-refresh',
    }),
    'maintain': ('Inspect a workspace', {'doctor': 'doctor', 'snapshot': 'snapshot'}),
}


_SHORTCUTS = {'init', 'sync', 'rebuild', 'status', 'validate', 'search', 'show',
              'deps', 'impact', 'context', 'doctor', 'snapshot'}
_GROUP_ONLY = {'query-performance', 'query-software',
               'ai-test', 'ai-status', 'ai-config', 'ai-proposals'}
_LEGACY_PATHS = {command: f'{group} {verb}' for group, (_, actions) in _GROUPS.items()
                 for verb, command in actions.items() if command not in _SHORTCUTS | _GROUP_ONLY}


def _print_aliases():
    print('Legacy commands remain available. These grouped names are preferred:\n')
    for name, replacement in sorted(_LEGACY_PATHS.items()):
        display = name
        print(f'  {display:22} {replacement}')


def _add_snapshot_actions(parser, add_action):
    actions = parser.add_subparsers(dest='snapshot_action', required=True, metavar='<action>')
    listing = add_action(actions, 'list', 'List snapshot IDs and identify the current pointer', '--workspace ./qec')
    listing.add_argument('--workspace', help='Path to the QEC workspace')


def _add_input_actions(parser, add_action):
    actions = parser.add_subparsers(dest='input_action', required=True, metavar='<action>')
    for name, description in (('list', 'List inbox and quarantined packages'),
                              ('quarantine', 'Move an inbox package aside'),
                              ('restore', 'Return a quarantined package to the inbox')):
        example = '--workspace ./qec' if name == 'list' else 'paper.zip --workspace ./qec'
        cmd = add_action(actions, name, description, example)
        cmd.add_argument('--workspace',
            help='Path to the QEC workspace; omit to use local discovery where supported')
        if name != 'list':
            cmd.add_argument('name', help='Exact inbox file name')


def _register_commands(add):
    add('version', help='Show the installed QEC Graph version')
    help_command = add('help', help='Show help for a specific command')
    help_command.add_argument('topic', nargs='*', metavar='command',
        help='Command path or topic: workspace sync, errors, json, or aliases')
    doctor = add('doctor', help='Inspect workspace health without writing files')
    doctor.add_argument('--workspace',
        help='Path to the QEC workspace; omit to use local discovery where supported')
    add('snapshot', help='Inspect local snapshots and stored registry states')
    add('inputs', help='List, quarantine, or restore inbox packages')
    for action, description in (('init', 'Create inputs/ and qecgraph.toml without extracting'),
                                ('sync', 'Import new source packages from inputs/'),
                                ('rebuild', 'Verify and replay all archived source packages'),
                                ('status', 'Report indexed, pending, and failed packages')):
        workspace = add(action, help=description)
        workspace.add_argument('--workspace',
            help='Path to the QEC workspace; omit to use the current directory' if action == 'init'
            else 'Path to the QEC workspace; omit to use local discovery where supported')
        if action in ('sync', 'rebuild'):
            workspace.add_argument('--keep-inputs', action='store_true',
                help='Retain successfully archived packages in the inbox')
            workspace.add_argument('--no-human', action='store_true', help='Skip the separate Obsidian renderer')
        if action == 'sync':
            workspace.add_argument('--dry-run', action='store_true',
                help='Report pending work without importing packages')
        if action == 'rebuild':
            workspace.add_argument('--include-inputs', action='store_true',
                help='Ingest new inbox files as well as replaying the archive')
    for name, description in (('ai-test', 'Test the configured AI provider without sending paper text'),
                              ('ai-status', 'Report the selected AI provider/model and key source'),
                              ('ai-config', 'Show the workspace AI configuration with secrets redacted'),
                              ('ai-proposals', 'List registered AI extraction artifacts')):
        cmd = add(name, help=description)
        cmd.add_argument('--workspace',
            help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd = add('human-build', help='Render Obsidian pages from the current fixed machine release')
    cmd.add_argument('--workspace',
        help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd.add_argument('--release', help='Exact workspace release ID; omit to use CURRENT')
    cmd = add('asset-add', help='Copy one explicit non-human asset into the content-addressed machine store')
    cmd.add_argument('input', help='Path to the input file or directory described above')
    cmd.add_argument('--workspace',
        help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd.add_argument('--media-type', default='application/octet-stream',
        help='Media type for the archived file (default: %(default)s)')
    for name, description in (('software-import-seed', 'Import the bundled software catalogue'),
                              ('software-coverage', 'Report the software records indexed in the workspace'),
                              ('software-refresh', 'Refresh metadata for selected software projects')):
        cmd = add(name, help=description)
        cmd.add_argument('--workspace',
            help='Path to the QEC workspace; omit to use local discovery where supported')
        if name == 'software-refresh':
            cmd.add_argument('--project-id', help='Stable project ID')
            cmd.add_argument('--limit', type=int, default=20,
                help='Maximum number of results or entries to process (default: %(default)s)')
            cmd.add_argument('--timeout', type=int, default=8,
                help='Per-request time limit in seconds (default: %(default)s)')
    cmd = add('research-import', help='Validate and publish exact research records without evidence promotion')
    cmd.add_argument('input', help='Path to the input file or directory described above')
    cmd.add_argument('--workspace',
        help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd.add_argument('--format', choices=['records', 'software-seed', 'synthetic-fixture'], default='records',
        help='Format of the research record input (default: %(default)s)')
    cmd = add('mcp-config', help='Print a reviewable fixed-scope client config without editing user settings')
    _add_ai_arguments(cmd)
    cmd = add('serve-mcp', help='Serve only fixed-scope read tools over local MCP stdio')
    _add_ai_arguments(cmd)
    cmd = add('query-tool', help='Call the fixed-scope read-only AI contract from JSON')
    cmd.add_argument('tool', help='Exact name from the read-only MCP tool list')
    cmd.add_argument('--arguments', required=True, help='JSON file of tool arguments')
    _add_ai_arguments(cmd)
    cmd = add('check-css', help='Validate binary check matrices; optionally enumerate a small distance')
    cmd.add_argument('--hx', required=True, help='Path to the X check matrix JSON')
    cmd.add_argument('--hz', required=True, help='Path to the Z check matrix JSON')
    cmd.add_argument('--lx', help='Path to the optional X logical witness matrix JSON')
    cmd.add_argument('--lz', help='Path to the optional Z logical witness matrix JSON')
    cmd.add_argument('--enumerate-distance', action='store_true', help='Enumerate the distance for small inputs')
    cmd.add_argument('--max-n', type=int, default=20,
        help='Largest number of qubits to enumerate (default: %(default)s)')
    cmd = add('check-experiment', help='Check explicit experiment/metric JSON; no evidence promotion')
    cmd.add_argument('input', help='Path to the input file or directory described above')
    cmd = add('codes', help='Exact code constraints, metric and currently bound distance evidence')
    _add_research_scope(cmd)
    cmd.add_argument('--n-min', type=int, help='Minimum physical qubit count')
    cmd.add_argument('--n-max', type=int, help='Maximum physical qubit count')
    cmd.add_argument('--distance-at-least', type=int, help='Require current evidence for at least this distance')
    cmd.add_argument('--metric-id', help='Exact metric ID for the distance filter')
    cmd.add_argument('--metric-revision', help='Exact metric revision for source-reported distance bounds')
    cmd.add_argument('--evidence-policy', choices=['verified', 'source_reported'],
                     help='Distance evidence policy; source_reported requires an exact metric revision (default: verified)')
    cmd.add_argument('--sector', choices=['X', 'Z', 'joint'],
        help='Logical sector for the distance filter (default: joint)')
    cmd = add('query-performance', help='Find reported performance points with their experimental context')
    _add_research_scope(cmd)
    cmd.add_argument('--code-id', help='Exact code ID')
    cmd.add_argument('--decoder-id', help='Exact decoder ID')
    cmd.add_argument('--noise-model-id', help='Exact noise model ID')
    cmd.add_argument('--metric-id', help='Exact metric ID')
    cmd.add_argument('--complete-only', action='store_true', default=None,
                     help='Require all comparison context to be bound')
    cmd.add_argument('--coordinate-name', help='Name of the reported coordinate')
    cmd.add_argument('--coordinate', type=_coordinate, help='Requested coordinate value')
    cmd.add_argument('--selection', choices=['exact', 'nearest_reported'],
                     help='Select reported coordinates (default: exact)')
    cmd = add('query-software', help='Find software and its revision-bound catalogue evidence')
    _add_research_scope(cmd)
    cmd.add_argument('--query', help='Match a software name, alias, or ID')
    cmd.add_argument('--role', help='Require an exact catalogue role')
    cmd = add("split", help="Write source-only semantic fragments and return their exact file paths")
    _add_source_arguments(cmd)
    cmd.add_argument("--force", action="store_true", help="Allow replacing CURRENT when it includes annotations or a catalog")
    cmd = add("search", help="Search titles, labels and text")
    cmd.add_argument("query", help='Literal search text')
    _add_query_scope(cmd)
    cmd.add_argument("--kind", help='Only return records and blocks of this kind')
    cmd.add_argument("--view", choices=("raw", "reading"), default="raw",
                     help="Search the raw index or the workspace reading projection")
    cmd.add_argument("--limit", type=int, default=20,
        help='Maximum number of results or entries to process (default: %(default)s)')
    cmd = add("show", help="Read one node with its incoming/outgoing edges")
    cmd.add_argument("id_or_label", help='Exact ID or unique label within the selected scope')
    _add_query_scope(cmd)
    cmd.add_argument('--revision', help='Exact workspace research record revision')
    for name, description in (("deps", "Trace active graph dependencies"),
                              ("impact", "Trace potential impact through graph dependencies"),
                              ("context", "Read bounded evidence and source context")):
        cmd = add(name, help=description)
        cmd.add_argument("id_or_label", help='Exact ID or unique label within the selected scope')
        _add_query_scope(cmd)
        if name == 'context':
            cmd.add_argument('--revision', help='Exact workspace research record revision')
        cmd.add_argument("--depth", type=int, default=2,
            help='Maximum number of dependency steps (default: %(default)s)')
        cmd.add_argument("--include-candidates", action="store_true",
            help='Include candidate relations explicitly')
        cmd.add_argument("--max-nodes", type=int, default=60,
            help='Maximum number of returned nodes (default: %(default)s)')
    cmd = add("validate", help="Validate hashes, source spans, endpoints and SQLite")
    cmd.add_argument('--workspace', help='Path to the QEC workspace')


def _build_parser(entrypoint=None):
    parser = _ArgumentParser(prog='qec-graph', usage='%(prog)s <command> [options]',
                             description='LaTeX source blocks and typed QEC graphs with explicit evidence checks',
                             epilog='Examples:\n  qec-graph init --workspace ./qec\n  qec-graph sync --dry-run\n'
                                    '  qec-graph query search HGP --workspace ./qec\n\n'
                                    f'Legacy commands: qec-graph help aliases\nGuide: {GUIDE_URL}')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    sub = parser.add_subparsers(dest='command', required=True, metavar='<command>')
    topics: dict[tuple[str, ...], argparse.ArgumentParser] = {}
    groups = {}
    for name, (description, actions) in _GROUPS.items():
        action = next(iter(actions))
        group = sub.add_parser(name, prog=f'qec-graph {name}', help=description, description=description,
                               epilog=command_epilog(actions[action], f'qec-graph {name} {action}'))
        groups[name] = group.add_subparsers(dest='action', required=True, metavar='<action>')
        topics[name,] = group

    definitions = {}

    def add(name, *, help):
        # Build options once. The public parents API reuses those definitions
        # for the grouped command and any existing flat entry point.
        options = _ArgumentParser(prog=f'qec-graph {name}', add_help=False, global_options=False)
        definitions[name] = options, help
        return options

    def add_leaf_actions(path, command):
        def add_action(actions, name, description, example):
            prog = f'{topics[path].prog} {name}'
            epilog = f'Example:\n  {prog} {example}\n\nGuide: {GUIDE_URL}'
            child = actions.add_parser(name, prog=prog, help=description, description=description, epilog=epilog)
            topics[(*path, name)] = child
            return child

        if command == 'snapshot':
            _add_snapshot_actions(topics[path], add_action)
        elif command == 'inputs':
            _add_input_actions(topics[path], add_action)

    _register_commands(add)
    for name, (options, description) in definitions.items():
        if name in _GROUP_ONLY:
            continue
        prog = entrypoint[1] if entrypoint and entrypoint[0] == name else f'qec-graph {name}'
        listing = {} if name in _LEGACY_PATHS else {'help': description}
        topics[name,] = sub.add_parser(name, parents=[options], prog=prog, **listing,
                                       description=description, epilog=command_epilog(name, prog))
        add_leaf_actions((name,), name)
    for name, (_, actions) in _GROUPS.items():
        for action, command in actions.items():
            options, description = definitions[command]
            prog = f'qec-graph {name} {action}'
            nested = groups[name].add_parser(action, parents=[options], prog=prog, help=description,
                                              description=description, epilog=command_epilog(command, prog))
            nested.set_defaults(command=command)
            topics[name, action] = nested
            add_leaf_actions((name, action), command)
    parser.set_defaults(json=False, debug=False, quiet=False, verbose=False, color='auto')
    return parser, topics


def _command_index(argv: list[str], start=0) -> int:
    while start < len(argv):
        flag = argv[start]
        if flag in {'--json', '--debug', '--quiet', '--verbose'} or flag.startswith(('--color=', '--progress=')):
            start += 1
        elif flag in {'--color', '--progress'}:
            start += 2
        else:
            return start
    return len(argv)


def parse_command(argv: list[str], *, entrypoint: tuple[str, str] | None = None) -> argparse.Namespace | None:
    if not argv:
        print(_QUICK_HELP)
        return None
    start = _command_index(argv)
    name = argv[start] if start < len(argv) else None
    action_index = _command_index(argv, start + 1)
    parser, topics = _build_parser(entrypoint)
    if name and not name.startswith('-') and (name,) not in topics:
        error = UsageError(f'Unknown command {name!r}')
        matches = get_close_matches(name, [topic[0] for topic in topics if len(topic) == 1], n=1)
        if matches:
            error.hint = f'Run qec-graph {matches[0]} --help for usage.'
        raise error
    if name in _GROUPS and action_index < len(argv):
        action = argv[action_index]
        if not action.startswith('-') and (name, action) not in topics:
            error = UsageError(f'Unknown action {action!r} for {name}')
            error.command = name
            matches = get_close_matches(action, _GROUPS[name][1], n=1)
            error.hint = (f'Run qec-graph {name} {matches[0]} --help for usage.' if matches
                          else f'Run qec-graph {name} --help for available actions.')
            raise error
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        exc.command = (name) if (name,) in topics else None
        if name in _GROUPS and action_index < len(argv):
            exc.command = _GROUPS[name][1].get(argv[action_index], exc.command)
        if entrypoint is not None:
            exc.hint = f'Run {entrypoint[1]} --help for usage.'
        raise
    if args.command == 'help':
        topic = tuple(args.topic)
        if not topic:
            parser.print_help()
        elif topic in topics:
            topics[topic].print_help()
        elif len(topic) == 1 and topic[0] in TOPICS:
            print(f'{TOPICS[topic[0]]}\n\nGuide: {GUIDE_URL}')
        elif topic == ('aliases',):
            _print_aliases()
        else:
            error = UsageError(f'Unknown help topic {" ".join(topic)!r}')
            error.command = 'help'
            raise error
        return None
    flat_name = name
    args.alias = None
    if entrypoint is None and not hasattr(args, 'action') and flat_name in _LEGACY_PATHS:
        display = flat_name
        args.alias = (display, _LEGACY_PATHS[flat_name])
    args.display_command = next((f'{group} {verb}' for group, (_, actions) in _GROUPS.items()
                                 for verb, command in actions.items()
                                 if command == args.command and command not in _SHORTCUTS), args.command)
    if args.command == 'inputs':
        args.display_command += ' ' + args.input_action
    args.verbose = args.verbose and not args.quiet
    args.progress = 'off' if args.quiet else getattr(args, 'progress', 'auto')
    args.quiet = args.quiet and not args.json
    return args
