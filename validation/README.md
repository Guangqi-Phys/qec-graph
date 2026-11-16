# Validation evidence

> **Status: Current (0.6.x).** This is an index of executable checks, not a
> historical run archive.

> **English** · [中文](README.zh-CN.md)

Historical run artifacts are not shipped. Earlier release evidence remains in
Git history; this tree keeps current checks and explicitly scoped acceptance
results so stale reports cannot be mistaken for a claim about the current code.

## Current checks

| Check | Command |
|---|---|
| Unit, integration and contract tests | `python -m unittest discover -s tests` |
| Compile-first preparation, zero AI | `python tools/reproduce_preparation.py --manifest test-sources/arxiv-sources/manifest.json --out build/preparation-replay --entries validation/preparation_entries.json --cases validation/preparation_cases.json` |
| End-to-end extraction and query reproduction | `python tools/reproduce.py --out build/reproduce` |
| Direct reading / search / task context evidence | `python tools/reproduce_knowledge.py --out build/knowledge-synthetic.json --include-payloads` |
| Registered real-source reading (read-only) | `python tools/reproduce_knowledge.py --machine /path/to/machine --out build/knowledge-real.json --include-payloads` |
| Workspace, MCP and isolation checks | `python tools/reproduce_workspace.py` and `python tools/reproduce_mcp.py` |
| Release distributions | `python -m build` then `python tools/check_distribution.py dist/` |
| Release binaries | The `Standalone Release` GitHub workflow |
| AI configuration and provider probe | `qec-graph ai status` and `qec-graph ai test` |
| AI proposals | `qec-graph ai proposals --json` |

A check is evidence only for the exact source revision and environment in which
it ran. A passing test does not make a paper's theorem true, a distance bound
mathematically verified, or a Lean declaration semantically matched.

The current [preparation acceptance report](preparation_acceptance.json) records
47 TeX inputs plus a PDF negative case: 45 compile, 40 have complete bibliography
bindings, and 18 meet the full preparation gate. The other 29 TeX inputs remain
partial. Twenty source-bound syntax probes pass on five papers; they are mechanical
checks, not independent human gold. Three explicit entry overrides are versioned
in `preparation_entries.json`; historical TeX support URLs/hashes and commands are
in the report. The pinned machine evaluation remains unaccepted because its
registry schema is incompatible. No original database or Human.md was changed.

`validation/retrieval_qa.json` contains eight source-bound engineering questions for the
review's five-paper release. Anchors were selected after viewing retrieved passages;
this is a navigation smoke set, not independent relevance gold. Run
`python tools/eval_retrieval.py --machine /path/to/copied-machine --cases validation/retrieval_qa.json --out build/retrieval-eval.json`.
It reports recall@5/10, reciprocal rank@10, concise response characters, latency and
failures for literal and BM25 modes on the same current implementation. It makes no
model calls and excludes AI proposals. Fifty human-reviewed scientific questions
and per-skill precision samples remain outstanding.

The complexity regression gate is `python tools/check_complexity.py`. Changes to
`validation/complexity_baseline.json` require explicit review; it records legacy
debt and does not mean the existing functions are simple.
The preparation report includes the explicit review of 16 omitted legacy ceilings:
each is checked against starting revision `3ef28ae`, with no increase accepted.
New compilation/preparation functions remain at complexity 10 or below.

## Adding evidence

Attach new logs or reports to the release/CI run that produced them, or add a
new versioned directory only while that version is current. Do not copy old
reports forward or edit a recorded result to match newer code.
