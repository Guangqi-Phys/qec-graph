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
| Recalculate/check preparation acceptance | `python tools/report_preparation.py --manifest test-sources/arxiv-sources/manifest.json --replay build/preparation-replay --cases validation/preparation_cases.json --out build/preparation-acceptance.json --check` |
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

The current [preparation acceptance report](preparation_acceptance.json) is generated
from the full `compile-prepare-v19` replay, with every material bundle reopened,
counts and source-bound syntax probes recalculated, and corpus/code snapshots
checked. Use `report_preparation.py` without `--check` to create a report first;
repeat the same arguments with `--check` to detect drift without compilation or
model calls. The committed report's `replay.argv` records the actual support paths,
entry hints and probe configuration; the comparison pins the v18 baseline at
`ff69adf`. Native tool outcomes remain in the bundles, not copied test-suite claims.

This corpus contains 47 TeX inputs and one PDF negative case. v19 has 46 ready,
one TeX partial and one expected PDF failure. Three newly ready papers preserve
reference ambiguity; unique reference binding counts do not increase. The report also lists
body completeness, verified projections and native dialects. Coverage counts and
remaining failures are mechanical preparation evidence, not scientific answer gold
or mathematical validation. [Review 06](../docs/reviews/review-2026-11-17-compile-prepare-testing/06-preserved-reference-ambiguity-acceptance.zh-CN.md)
records the comparable before/after numbers, executed checks, dependency provenance
and outstanding work. The case-only asset match remains non-portable to a
case-sensitive filesystem. The pinned machine-copy evaluation remains unaccepted
because its registry schema is incompatible. Human.md and the original database
are unchanged.

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
The current gate retains 85 legacy functions over complexity 10, with no new
regressions. The earlier explicit review of 16 omitted ceilings is retained at
`59a0b9f:validation/preparation_acceptance.json`; it is not a new validation claim.
New compilation/preparation functions remain at complexity 10 or below.

## Adding evidence

Attach new logs or reports to the release/CI run that produced them, or add a
new versioned directory only while that version is current. Do not copy old
reports forward or edit a recorded result to match newer code.
