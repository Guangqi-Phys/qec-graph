"""Examples and help topics for the public CLI."""

from __future__ import annotations

GUIDE_URL = 'https://github.com/Guangqi-Phys/qec-graph/blob/main/docs/user/advanced-usage.md'

EXAMPLES = {
    'version': '',
    'help': 'workspace sync',
    'doctor': '--workspace ./qec --json',
    'snapshot': 'list --workspace ./qec',
    'inputs': 'quarantine paper.zip --workspace ./qec',
    'init': '',
    'sync': '--dry-run',
    'rebuild': '--include-inputs --json',
    'status': '--json',
    'human-build': '--workspace ./qec',
    'ai-test': '--workspace ./qec',
    'ai-status': '--workspace ./qec',
    'ai-config': '--workspace ./qec',
    'ai-proposals': '--workspace ./qec',
    'asset-add': 'results.csv --workspace ./qec --media-type text/csv',
    'software-import-seed': '--workspace ./qec',
    'software-coverage': '--workspace ./qec',
    'software-refresh': '--workspace ./qec --limit 3',
    'research-import': 'records.json --workspace ./qec',
    'review-list': '--workspace ./qec',
    'mcp-config': '--workspace ./qec',
    'serve-mcp': '--machine ./qec/machine',
    'query-tool': 'qec_find_performance --arguments filters.json --workspace ./qec',
    'check-css': '--hx HX.json --hz HZ.json --enumerate-distance',
    'check-experiment': 'experiment-and-metric.json',
    'codes': '--workspace ./qec --n-max 100 --limit 10',
    'query-performance': '--workspace ./qec --metric-id METRIC_ID --complete-only',
    'query-software': '--machine ./qec/machine --query Stim --limit 10',
    'split': 'main.tex --project-id demo --out ./fragments',
    'search': 'HGP --workspace ./qec --limit 10',
    'show': 'thm:hgp-length --workspace ./qec',
    'deps': 'thm:hgp-length --workspace ./qec --depth 2',
    'impact': 'def:css --workspace ./qec --depth 2',
    'context': 'thm:hgp-length --workspace ./qec --max-nodes 30',
    'validate': '--workspace ./qec --json',
}

TOPICS = {
    'progress': '''Terminal progress
  All business commands describe their current activity on stderr.
  Known work uses a compact amber micro-dot matrix, exact counts and one-decimal percentages.
  Only major-stage results remain in terminal scrollback; small steps disappear when done.
  Unknown work shows an animated indicator and elapsed time, never an invented ETA.
  AI has its own breathing light beside "AI"; it indicates a pending request, not a percentage.
  Each paper shows its current task and completed count; finished/queued task rows are hidden.
  The AI batch counts completed tasks across all scheduled papers (3/8 = 37.5%).
  AI details include provider/model, attempts, timeout, retry and response validation.
  Reused proposals count once; failed tasks are summarized and never counted as done.

  --progress auto   Live display when stderr is a terminal (default)
  --progress plain  Append-only major-stage log, including in CI and pipes
  --progress off    Suppress activity; keep reports and errors
  --verbose         Diagnostic activity log without animation
  --quiet           Suppress activity and successful human reports
  --color never     Keep the layout without color

  JSON and MCP stdout stay machine-readable. Help and version return immediately.
  MCP uses plain service activity; redirected stderr is silent in auto mode.

Example:
  qec-graph sync --json --progress plain > report.json''',
    'errors': '''Exit codes
  0    completed successfully
  1    input, storage, or internal failure
  2    partial operation or validation failures
  4    required file or exact query target missing
  5    writer lock or input destination conflict
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
