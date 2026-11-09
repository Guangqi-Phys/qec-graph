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

Run qec-graph --help for all commands or qec-graph help <command> for options."""


class _ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('formatter_class', argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)
        self.add_argument('--json', action='store_true', default=argparse.SUPPRESS,
                          help='Print detailed reports and structured errors')
        self.add_argument('--debug', action='store_true', default=argparse.SUPPRESS,
                          help='Show a traceback for unexpected failures')
        self.add_argument('--verbose', action='store_true', default=argparse.SUPPRESS,
                          help='Show diagnostic progress on stderr')
        self.add_argument('--quiet', action='store_true', default=argparse.SUPPRESS,
                          help='Suppress progress and successful reports; keep errors and explicit JSON')
        self.add_argument('--color', choices=('auto', 'always', 'never'), default=argparse.SUPPRESS,
                          help='Control color in terminal summaries (default: auto)')

    def error(self, message):
        raise UsageError(message)


def _add_query_scope(parser, *, workspace=False):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--store', help='Path to a standalone snapshot store')
    group.add_argument('--corpus', help='Path to a legacy multi-document corpus')
    if workspace:
        group.add_argument('--workspace',
            help='Path to the QEC workspace; omit to use local discovery where supported')
        group.add_argument('--machine', help='Only the mounted machine directory (no workspace access)')
        parser.add_argument('--release', help='Exact workspace release ID; omit to use CURRENT')
    parser.add_argument('--snapshot', help='Fixed store snapshot ID')
    parser.add_argument('--registry-revision', help='Fixed corpus state revision')
    parser.add_argument('--source-version-id', help='Restrict corpus source scope')


def _add_research_scope(parser, *, legacy_corpus=False):
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--workspace', help='Path to the QEC workspace')
    scope.add_argument('--machine', help='Path to the mounted machine directory')
    if legacy_corpus:
        scope.add_argument('--corpus', help='Path to a legacy multi-document corpus')
        parser.add_argument('--registry-revision', help='Exact legacy corpus state ID; omit to use CURRENT')
    parser.add_argument('--release', help='Exact workspace release ID; omit to use CURRENT')
    parser.add_argument('--limit', type=int, help='Maximum rows to return')
    parser.add_argument('--offset', type=int, help='Number of matching workspace rows to skip')
    parser.add_argument('--max-chars', type=int, help='Maximum Unicode codepoints in the workspace response data')


def _coordinate(value):
    try:
        return int(value)
    except ValueError:
        return float(value)


def _add_ai_arguments(parser):
    _add_query_scope(parser, workspace=True)
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
        'validate': 'validate', 'migrate': 'workspace-migrate',
    }),
    'query': ('Search and trace evidence in a fixed scope', {
        'search': 'search', 'show': 'show', 'deps': 'deps', 'impact': 'impact',
        'context': 'context', 'codes': 'codes', 'performance': 'query-performance',
        'software': 'query-software',
    }),
    'review': ('Create, inspect, or apply proposals', {
        'propose': 'review', 'list': 'review-list', 'show': 'review-show', 'decide': 'review-decide', 'apply': 'apply',
        'import': 'extract-submit',
    }),
    'lean': ('Build, import, or inspect Lean evidence', {
        'build': 'lean-build', 'import': 'lean-import', 'status': 'lean-status',
    }),
    'mcp': ('Configure or serve read-only MCP tools', {
        'serve': 'serve-mcp', 'config': 'mcp-config',
    }),
    'human': ('Render human-readable views', {'build': 'human-build'}),
    'software': ('Manage the software directory', {
        'import-seed': 'software-import-seed', 'coverage': 'software-coverage',
        'refresh': 'software-refresh',
    }),
    'maintain': ('Inspect, watch, or recover graph stores', {
        'watch': 'watch', 'recover': 'recover-store', 'validate-staged': 'validate-staged',
        'audit-dependencies': 'audit-dependencies', 'doctor': 'doctor', 'snapshot': 'snapshot',
    }),
}


_SHORTCUTS = {'init', 'sync', 'rebuild', 'status', 'validate', 'search', 'show',
              'deps', 'impact', 'context', 'doctor', 'snapshot'}
_GROUP_ONLY = {'query-performance', 'query-software', 'review-show'}
_LEGACY_PATHS = {command: f'{group} {verb}' for group, (_, actions) in _GROUPS.items()
                 for verb, command in actions.items() if command not in _SHORTCUTS | _GROUP_ONLY}


def _print_aliases():
    print('Legacy commands remain available. These grouped names are preferred:\n')
    for name, replacement in sorted(_LEGACY_PATHS.items()):
        display = 'review FILE' if name == 'review' else name
        print(f'  {display:22} {replacement}')


def _add_snapshot_actions(parser, add_action):
    actions = parser.add_subparsers(dest='snapshot_action', required=True, metavar='<action>')
    listing = add_action(actions, 'list', 'List snapshot IDs and identify the current pointer', '--workspace ./qec')
    scope = listing.add_mutually_exclusive_group()
    for option in ('--workspace', '--store', '--corpus'):
        scope.add_argument(option, help='Select the workspace, store, or corpus for the snapshot listing')


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
    for action, description in (('init', 'Create a workspace and import its inbox'),
                                ('sync', 'Import new source packages from inputs/'),
                                ('rebuild', 'Verify and replay all archived source packages'),
                                ('status', 'Report indexed, pending, and failed packages')):
        workspace = add(action, help=description)
        workspace.add_argument('--workspace',
            help='Path to the QEC workspace; omit to use local discovery where supported')
        if action != 'status':
            workspace.add_argument('--keep-inputs', action='store_true',
                help='Retain successfully archived packages in the inbox')
            workspace.add_argument('--no-human', action='store_true', help='Skip the separate Obsidian renderer')
        if action == 'init':
            workspace.add_argument('--no-ingest', action='store_true',
                help='Create the workspace without ingesting packages')
        if action == 'sync':
            workspace.add_argument('--dry-run', action='store_true',
                help='Report pending work without importing packages')
        if action == 'rebuild':
            workspace.add_argument('--include-inputs', action='store_true',
                help='Ingest new inbox files as well as replaying the archive')
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
    cmd = add('extract-request', help='Export bounded, provenance-bound source excerpts for an optional provider')
    cmd.add_argument('source_version', help='Exact source version ID in the selected release')
    cmd.add_argument('--workspace',
        help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd.add_argument('--release', help='Exact workspace release ID; omit to use CURRENT')
    cmd.add_argument('--max-chars', type=int, default=24000,
        help='Maximum source codepoints per request (default: %(default)s)')
    cmd.add_argument('--offset', type=int, default=0,
        help='Codepoint offset for the next excerpt (default: %(default)s)')
    cmd = add('extract-submit', help='Validate a local provider response and queue a draft')
    cmd.add_argument('request_id', help='ID of the saved extraction request')
    cmd.add_argument('response', help='Path to the local provider response JSON')
    cmd.add_argument('--workspace',
        help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd = add('review-show', help='Read an exact provider draft or legacy corpus proposal')
    cmd.add_argument('proposal_id', help='Exact draft or proposal ID')
    scope = cmd.add_mutually_exclusive_group()
    scope.add_argument('--workspace', help='Path to the QEC workspace; omit to discover it locally')
    scope.add_argument('--corpus', help='Path to a legacy corpus containing the proposal')
    cmd = add('extract-review', help='Record an explicit human decision on an exact provider draft')
    cmd.add_argument('proposal_id', help='Exact proposal ID')
    cmd.add_argument('--workspace',
        help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd.add_argument('--reviewer', required=True, help='Stable identifier of the person making the decision')
    cmd.add_argument('--decision', choices=['approve', 'reject'], required=True,
        help='Decision to bind to the exact proposal')
    cmd.add_argument('--rationale', required=True, help='Explain the review decision')
    cmd = add('workspace-migrate', help='Copy a legacy corpus into a new workspace; retain all exact revisions')
    cmd.add_argument('--corpus', required=True, help='Path to a legacy multi-document corpus')
    cmd.add_argument('--workspace', required=True,
        help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd.add_argument('--registry-revision', help='Exact corpus state ID; omit to use CURRENT')
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
    cmd = add('review-list', help='List source-linked proposals without approving them')
    cmd.add_argument('--workspace',
        help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd = add('lean-build', help='Explicitly build/export/audit a pinned Lean project; never invoked by read tools')
    cmd.add_argument('--project', required=True, help='Path to the pinned Lean project')
    cmd.add_argument('--out', required=True, help='Output directory for the command result')
    cmd.add_argument('--lake', help='Explicit Lake executable')
    cmd.add_argument('--build-only', action='store_true', help='Run the build without exporting declarations')
    cmd = add('lean-import', help='Import an actual Lean export with current input or explicit historical bindings')
    cmd.add_argument('report', help='Path to the actual Lean build report JSON')
    cmd.add_argument('--corpus', required=True, help='Path to a legacy multi-document corpus')
    cmd.add_argument('--project-id', required=True, help='Stable project ID')
    cmd.add_argument('--project', help='Path to the pinned Lean project')
    cmd.add_argument('--mapping', help='Path to a JSON object or list of exact declaration mappings')
    cmd.add_argument('--historical', action='store_true',
        help='Allow import as historical evidence using recorded bindings')
    cmd = add('lean-status', help='Read Lean build freshness without executing Lean')
    cmd.add_argument('--corpus', required=True, help='Path to a legacy multi-document corpus')
    cmd.add_argument('--registry-revision', help='Exact corpus state ID; omit to use CURRENT')
    cmd = add('mcp-config', help='Print a reviewable fixed-scope client config without editing user settings')
    _add_ai_arguments(cmd)
    cmd = add('serve-mcp', help='Serve only fixed-scope read tools over local MCP stdio')
    _add_ai_arguments(cmd)
    cmd = add('query-tool', help='Call the fixed-scope read-only AI contract from JSON')
    cmd.add_argument('tool', help='Exact name from the read-only MCP tool list')
    cmd.add_argument('--arguments', required=True, help='JSON file of tool arguments')
    _add_ai_arguments(cmd)
    cmd = add('watch', help='Debounced content polling; rebuild through the shared ingestion pipeline')
    _add_source_arguments(cmd)
    cmd.add_argument('--annotations', help='Path to the source annotation sidecar JSON')
    cmd.add_argument('--catalog', help='Directory of existing JSON records')
    cmd.add_argument('--interval', type=float, default=0.5,
        help='Polling interval in seconds (default: %(default)s)')
    cmd.add_argument('--debounce', type=float, default=0.25,
        help='Seconds of quiet before ingestion (default: %(default)s)')
    cmd.add_argument('--max-polls', type=int, help='Stop after this many polling cycles')
    cmd.add_argument('--once', action='store_true', help='Run a single poll and exit')
    cmd = add('recover-store', help='Validate CURRENT and inventory abandoned tool-owned builds')
    cmd.add_argument('--store', required=True, help='Path to a standalone snapshot store')
    cmd.add_argument('--remove-abandoned', action='store_true',
        help='Remove only validated tool-owned abandoned builds')
    cmd = add('validate-staged', help='Validate an explicitly selected staged snapshot')
    cmd.add_argument('--store', required=True, help='Path to a standalone snapshot store')
    cmd.add_argument('--snapshot', required=True, help='Exact immutable snapshot ID')
    cmd = add('audit-dependencies', help='Report SCCs only in active reviewed logical dependencies')
    _add_query_scope(cmd)
    cmd = add('apply', help='Atomically publish a reviewed proposal with input conflict checks')
    cmd.add_argument('proposal_id', help='Exact proposal ID')
    cmd.add_argument('--review-id', required=True, help='Exact review decision ID for the proposal')
    cmd.add_argument('--corpus', required=True, help='Path to a legacy multi-document corpus')
    cmd = add('review', help='Create an inspectable proposal, without applying changes')
    cmd.add_argument('input', help='JSON with changes and rationale')
    cmd.add_argument('--corpus', required=True, help='Path to a legacy multi-document corpus')
    cmd.add_argument('--actor-id', required=True, help='Stable identifier of the actor')
    cmd.add_argument('--actor-kind', choices=['ai', 'program', 'human'], default='ai',
        help='Kind of actor creating the record (default: %(default)s)')
    cmd = add('review-decide', help='Bind an explicit decision to an exact proposal')
    cmd.add_argument('proposal_id', help='Exact proposal ID')
    cmd.add_argument('--corpus', required=True, help='Path to a legacy multi-document corpus')
    cmd.add_argument('--actor-id', required=True, help='Stable identifier of the actor')
    cmd.add_argument('--actor-kind', choices=['ai', 'program', 'human'], default='ai',
        help='Kind of actor creating the record (default: %(default)s)')
    cmd.add_argument('--decision', choices=['approve', 'reject'], required=True,
        help='Decision to bind to the exact proposal')
    cmd.add_argument('--rationale', required=True, help='Explain the review decision')
    cmd.add_argument('--checked-scope', choices=['statement', 'hypotheses', 'dependencies'], action='append', default=[],
        help='Part of the claim checked; repeat to include more than one')
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
    _add_research_scope(cmd, legacy_corpus=True)
    cmd.add_argument('--n-min', type=int, help='Minimum physical qubit count')
    cmd.add_argument('--n-max', type=int, help='Maximum physical qubit count')
    cmd.add_argument('--distance-at-least', type=int, help='Require current evidence for at least this distance')
    cmd.add_argument('--metric-definition-id', help='Exact metric ID for the distance filter')
    cmd.add_argument('--metric-revision', help='Exact metric revision for source-reported distance bounds')
    cmd.add_argument('--evidence-policy', choices=['verified', 'source_reported'],
                     help='Workspace distance evidence policy (default: verified)')
    cmd.add_argument('--sector', choices=['X', 'Z', 'joint'],
        help='Logical sector for the distance filter (default: joint)')
    cmd.add_argument('--construction', help='Exact construction ID or kind (legacy corpus only)')
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
    cmd = add('validate-corpus', help='Check typed records, references, sources and managed assets')
    cmd.add_argument('--corpus', required=True, help='Path to a legacy multi-document corpus')
    cmd.add_argument('--registry-revision', help='Exact corpus state ID; omit to use CURRENT')
    cmd = add('migrate', help='Adapt legacy inputs into a new location with a rejection report')
    cmd.add_argument('input', help='Path to the input file or directory described above')
    cmd.add_argument('--out', required=True, help='Output directory for the command result')
    cmd.add_argument('--source-root', help='Root directory for the legacy record assets')
    cmd = add('migration-import', help='Import adapted records and managed assets atomically')
    cmd.add_argument('input', help='Path to the input file or directory described above')
    cmd.add_argument('--corpus', required=True, help='Path to a legacy multi-document corpus')
    for name in ('record-add', 'claim-link'):
        cmd = add(name, help="Add an explicit record or provenance mapping from JSON")
        cmd.add_argument("input", help='Path to the input file or directory described above')
        cmd.add_argument("--corpus", required=True, help='Path to a legacy multi-document corpus')
    cmd = add("register", help="Archive a store as an explicit work/source version in a corpus")
    cmd.add_argument("--corpus", required=True, help='Path to a legacy multi-document corpus')
    cmd.add_argument("--store", required=True, help='Path to a standalone snapshot store')
    cmd.add_argument("--work-id", required=True, help='Stable identity shared across source versions')
    cmd.add_argument("--source-version-id", required=True, help='Stable identity of this exact source version')
    cmd.add_argument("--title", help='Display title for the registered work')
    cmd.add_argument("--upstream-version", help='Version string from the source provider, such as v2')
    cmd = add("ingest", help="Parse a LaTeX project and write an immutable snapshot")
    _add_source_arguments(cmd)
    cmd.add_argument("--annotations", help='Path to the source annotation sidecar JSON')
    cmd.add_argument("--catalog", help="Directory of existing JSON records, such as the earlier starter records/")
    cmd = add("split", help="Write source-only semantic fragments and return their exact file paths")
    _add_source_arguments(cmd)
    cmd.add_argument("--force", action="store_true", help="Allow replacing CURRENT when it includes annotations or a catalog")
    cmd = add("search", help="Search titles, labels and text")
    cmd.add_argument("query", help='Literal search text')
    _add_query_scope(cmd, workspace=True)
    cmd.add_argument("--kind", help='Only return records and blocks of this kind')
    cmd.add_argument("--limit", type=int, default=20,
        help='Maximum number of results or entries to process (default: %(default)s)')
    cmd = add("show", help="Read one node with its incoming/outgoing edges")
    cmd.add_argument("id_or_label", help='Exact ID or unique label within the selected scope')
    _add_query_scope(cmd, workspace=True)
    cmd.add_argument('--revision', help='Exact workspace research record revision')
    for name, description in (("deps", "Trace active graph dependencies"),
                              ("impact", "Trace potential impact through graph dependencies"),
                              ("context", "Read bounded evidence and source context")):
        cmd = add(name, help=description)
        cmd.add_argument("id_or_label", help='Exact ID or unique label within the selected scope')
        _add_query_scope(cmd, workspace=True)
        if name == 'context':
            cmd.add_argument('--revision', help='Exact workspace research record revision')
        cmd.add_argument("--depth", type=int, default=2,
            help='Maximum number of dependency steps (default: %(default)s)')
        cmd.add_argument("--include-candidates", action="store_true",
            help='Include candidate relations explicitly')
        cmd.add_argument("--max-nodes", type=int, default=60,
            help='Maximum number of returned nodes (default: %(default)s)')
    cmd = add("validate", help="Validate hashes, source spans, endpoints and SQLite")
    group = cmd.add_mutually_exclusive_group()
    group.add_argument("--store", help='Path to a standalone snapshot store')
    group.add_argument("--workspace",
        help='Path to the QEC workspace; omit to use local discovery where supported')
    cmd.add_argument('--snapshot', help='Exact immutable snapshot ID')


def _build_parser(entrypoint=None):
    parser = _ArgumentParser(prog='qec-graph', usage='%(prog)s <command> [options]',
                             description='LaTeX source blocks and typed QEC graphs with explicit evidence checks',
                             epilog='Examples:\n  qec-graph init --workspace ./qec\n  qec-graph sync --dry-run\n'
                                    '  qec-graph query search HGP --workspace ./qec\n\n'
                                    f'Legacy commands: qec-graph help aliases\nGuide: {GUIDE_URL}')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    sub = parser.add_subparsers(dest='command', required=True, metavar='<command>')
    topics = {}
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
        options = argparse.ArgumentParser(prog=f'qec-graph {name}', add_help=False)
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
        if name == 'review':
            legacy = sub.add_parser('review-propose', parents=[options], prog='qec-graph review',
                                    description=description, epilog=command_epilog(name, 'qec-graph review'))
            legacy.set_defaults(command='review')
            topics['review-propose',] = legacy
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
        if flag in {'--json', '--debug', '--quiet', '--verbose'} or flag.startswith('--color='):
            start += 1
        elif flag == '--color':
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
    if name == 'review' and action_index < len(argv):
        argument = argv[action_index]
        # A legacy review took a JSON filename directly, which can also
        # be a grouped action name. Actor options identify the old form.
        legacy_actor = any(flag == '--actor-id' or flag.startswith('--actor-id=') for flag in argv[start + 1:])
        path_like = not argument.startswith('-') and ('/' in argument or argument.endswith('.json'))
        if (argument not in {*_GROUPS['review'][1], '--help', '-h'} and (legacy_actor or path_like)
                or argument in {'list', 'show', 'import'} and legacy_actor):
            argv[start] = 'review-propose'
            name = 'review-propose'
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
        exc.command = ('review' if name == 'review-propose' else name) if (name,) in topics else None
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
    flat_name = 'review' if name == 'review-propose' else name
    args.alias = None
    if entrypoint is None and not hasattr(args, 'action') and flat_name in _LEGACY_PATHS:
        display = 'review FILE' if flat_name == 'review' else flat_name
        args.alias = (display, _LEGACY_PATHS[flat_name])
    args.verbose = args.verbose and not args.quiet
    args.quiet = args.quiet and not args.json
    return args
