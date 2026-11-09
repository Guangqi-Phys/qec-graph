"""Arguments and usage help for the command-line entry point."""
from __future__ import annotations

import argparse

from .. import __version__
from .errors import UsageError


_QUICK_HELP = """Usage: qec-graph <command> [options]

  init       Create a workspace
  sync       Import source packages from inputs/
  status     Report import progress and failures
  validate   Check the current release
  search     Find source blocks and records
  mcp serve  Start the read-only MCP server

Run qec-graph --help for all commands or qec-graph help <command> for options."""


class _ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_argument('--json', action='store_true', default=argparse.SUPPRESS,
                          help='Print detailed reports and structured errors')
        self.add_argument('--debug', action='store_true', default=argparse.SUPPRESS,
                          help='Show a traceback for unexpected failures')

    def error(self, message):
        raise UsageError(message)


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


def _add_source_arguments(parser):
    parser.add_argument("entry")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--config")
    parser.add_argument('--strict', action='store_true', help='Keep partial extraction in staging without changing CURRENT')
    parser.add_argument('--incremental', action='store_true', help='Reuse content-checked per-file ASTs; rebuild semantic projections')


def _build_parser():
    parser = _ArgumentParser(prog="qec-graph", usage="%(prog)s <command> [options]",
                             description="LaTeX source blocks and typed QEC graphs with explicit evidence checks")
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    sub.add_parser('version', help='Show the installed QEC Graph version')
    help_command = sub.add_parser('help', help='Show help for a specific command')
    help_command.add_argument('topic', nargs='?')
    doctor = sub.add_parser('doctor', help='Inspect workspace health without writing files')
    doctor.add_argument('--workspace')
    snapshot = sub.add_parser('snapshot', help='Inspect local snapshots and stored registry states')
    snapshot_list = snapshot.add_subparsers(dest='snapshot_action', required=True).add_parser(
        'list', help='List snapshot IDs and identify the current pointer')
    scope = snapshot_list.add_mutually_exclusive_group()
    for option in ('--workspace', '--store', '--corpus'):
        scope.add_argument(option)
    inputs = sub.add_parser('inputs', help='List, quarantine, or restore inbox packages')
    input_actions = inputs.add_subparsers(dest='input_action', required=True, metavar='<action>')
    for name, description in (('list', 'List inbox and quarantined packages'),
                              ('quarantine', 'Move an inbox package aside'),
                              ('restore', 'Return a quarantined package to the inbox')):
        cmd = input_actions.add_parser(name, help=description)
        cmd.add_argument('--workspace')
        if name != 'list':
            cmd.add_argument('name', help='Exact inbox file name')
    for action in ('init', 'sync', 'rebuild', 'status'):
        workspace = sub.add_parser(action, help=f'{action.capitalize()} a managed QEC workspace')
        workspace.add_argument('--workspace')
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
    cmd.add_argument("--force", action="store_true", help="Allow replacing CURRENT when it includes annotations or a catalog")
    cmd = sub.add_parser("search", help="Search titles, labels and text")
    cmd.add_argument("query")
    _add_query_scope(cmd, workspace=True)
    cmd.add_argument("--kind")
    cmd.add_argument("--limit", type=int, default=20)
    cmd = sub.add_parser("show", help="Read one node with its incoming/outgoing edges")
    cmd.add_argument("id_or_label")
    _add_query_scope(cmd, workspace=True)
    for name, description in (("deps", "Trace active graph dependencies"),
                              ("impact", "Trace potential impact through graph dependencies"),
                              ("context", "Read bounded evidence and source context")):
        cmd = sub.add_parser(name, help=description)
        cmd.add_argument("id_or_label")
        _add_query_scope(cmd, workspace=True)
        cmd.add_argument("--depth", type=int, default=2)
        cmd.add_argument("--include-candidates", action="store_true")
        cmd.add_argument("--max-nodes", type=int, default=60)
    cmd = sub.add_parser("validate", help="Validate hashes, source spans, endpoints and SQLite")
    group = cmd.add_mutually_exclusive_group()
    group.add_argument("--store")
    group.add_argument("--workspace")
    cmd.add_argument('--snapshot')
    parser.set_defaults(json=False, debug=False)
    return parser, sub


def parse_command(argv: list[str]) -> argparse.Namespace | None:
    if not argv:
        print(_QUICK_HELP)
        return None
    start = next((i for i, arg in enumerate(argv) if arg not in {'--json', '--debug'}), len(argv))
    pair = argv[start:start + 2]
    if pair == ['mcp', 'serve']:
        argv[start:start + 2] = ['serve-mcp']
    if pair == ['human', 'build']:
        argv[start:start + 2] = ['human-build']
    if pair in (['software', 'import-seed'], ['software', 'coverage'], ['software', 'refresh']):
        argv[start:start + 2] = ['software-' + pair[1]]
    if pair == ['review', 'list'] and '--corpus' not in argv:
        argv[start:start + 2] = ['review-list']
    parser, sub = _build_parser()
    name = argv[start] if start < len(argv) else None
    if name and not name.startswith('-') and name not in sub.choices:
        raise UsageError(f'Unknown command {name!r}')
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        exc.command = name if name in sub.choices else None
        raise
    if args.command == 'help':
        if args.topic is None:
            parser.print_help()
        elif args.topic in sub.choices:
            sub.choices[args.topic].print_help()
        else:
            error = UsageError(f'Unknown help topic {args.topic!r}')
            error.command = 'help'
            raise error
        return None
    return args
