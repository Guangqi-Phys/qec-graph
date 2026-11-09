"""Examples and help topics for the public CLI."""

from __future__ import annotations

GUIDE_URL = 'https://github.com/Guangqi-Phys/qec-graph/blob/main/docs/ADVANCED_USAGE.md'

EXAMPLES = {
    'version': '',
    'help': 'workspace sync',
    'doctor': '--workspace ./qec --json',
    'snapshot': 'list --workspace ./qec',
    'inputs': 'quarantine paper.zip --workspace ./qec',
    'init': '--workspace ./qec',
    'sync': '--dry-run',
    'rebuild': '--include-inputs --json',
    'status': '--json',
    'human-build': '--workspace ./qec',
    'asset-add': 'results.csv --workspace ./qec --media-type text/csv',
    'extract-request': 'SOURCE_VERSION_ID --workspace ./qec --max-chars 12000',
    'extract-submit': 'REQUEST_ID response.json --workspace ./qec',
    'extract-review': 'PROPOSAL_ID --reviewer ada --decision reject --rationale "Missing source binding"',
    'workspace-migrate': '--corpus ./corpus --workspace ./qec-new',
    'software-import-seed': '--workspace ./qec',
    'software-coverage': '--workspace ./qec',
    'software-refresh': '--workspace ./qec --limit 3',
    'research-import': 'records.json --workspace ./qec',
    'review-list': '--workspace ./qec',
    'lean-build': '--project ./lean --out ./build/lean',
    'lean-import': 'lean-report.json --corpus ./corpus --project-id demo --project ./lean',
    'lean-status': '--corpus ./corpus',
    'mcp-config': '--workspace ./qec',
    'serve-mcp': '--machine ./qec/machine',
    'query-tool': 'qec_find_performance --arguments filters.json --workspace ./qec',
    'watch': 'main.tex --project-id demo --out ./store --once',
    'recover-store': '--store ./store',
    'validate-staged': '--store ./store --snapshot SNAPSHOT_ID',
    'audit-dependencies': '--corpus ./corpus',
    'apply': 'PROPOSAL_ID --review-id REVIEW_ID --corpus ./corpus',
    'review': 'proposal.json --corpus ./corpus --actor-id ada --actor-kind human',
    'review-decide': 'PROPOSAL_ID --corpus ./corpus --actor-id ada --actor-kind human '
                     '--decision approve --rationale "Checked exact statement" --checked-scope statement',
    'check-css': '--hx HX.json --hz HZ.json --enumerate-distance',
    'check-experiment': 'experiment-and-metric.json',
    'codes': '--corpus ./corpus --n-max 100 --limit 10',
    'validate-corpus': '--corpus ./corpus',
    'migrate': './legacy/records --source-root ./legacy --out ./adapted',
    'migration-import': './adapted --corpus ./corpus',
    'record-add': 'claim.json --corpus ./corpus',
    'claim-link': 'claim-link.json --corpus ./corpus',
    'register': '--corpus ./corpus --store ./store --work-id work:demo --source-version-id version:demo:1',
    'ingest': 'main.tex --project-id demo --out ./store --strict',
    'split': 'main.tex --project-id demo --out ./fragments',
    'search': 'HGP --workspace ./qec --limit 10',
    'show': 'thm:hgp-length --store ./store',
    'deps': 'thm:hgp-length --store ./store --depth 2',
    'impact': 'def:css --store ./store --depth 2',
    'context': 'thm:hgp-length --store ./store --max-nodes 30',
    'validate': '--workspace ./qec --json',
}

TOPICS = {
    'errors': '''Exit codes
  0    completed successfully
  1    input, storage, or internal failure
  2    partial operation or validation failures
  4    required file or exact query target missing
  5    another writer holds the lock
  64   invalid command syntax
  130  interrupted

Use --json for structured errors and --debug for unexpected failures.''',
    'json': '''JSON output
  Pass --json before or after the command for detailed reports and
  versioned errors. A partial operation retains its detailed report.
  MCP reserves stdout for protocol frames.

Examples:
  qec-graph status --json
  qec-graph --json query show SOURCE_ID --workspace ./qec''',
}


def command_epilog(command: str, prog: str) -> str:
    args = EXAMPLES[command]
    return f'Example:\n  {prog} {args}'.rstrip() + f'\n\nGuide: {GUIDE_URL}'
