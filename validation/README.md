# Validation evidence

> **Status: Evidence index.** Reports describe runs against specific source
> revisions; they are not substitutes for the current design or a new test run.

> **English** · [中文](README.zh-CN.md)

> [!NOTE]
> Lean is **deferred/experimental** in 0.4.x. Everything under
> `validation/lean-experimental/` is regression evidence, not a supported
> verification claim. Database, query and MCP paths do not invoke Lean.

- [Validation matrix](index.json) gives the area/lifecycle/path view in machine-readable form.

## How to use this tree

- **Current release evidence** is under `audit/0.4.0rc1/` and
  `workspace-0.4.0rc1/`.
- **Older stages** are grouped by the subsystem they exercised: baseline,
  corpus, review, incremental and MCP.
- **Lean experiments** are isolated under `lean-experimental/`; they are kept
  only so the historical regression tests remain meaningful.
- **`legacy-report-0.3.0.md`** is the old stage-by-stage report. It is retained
  for provenance; follow its links only as historical context.
- **`archive.sha256`** is the manifest for the removed bulk evidence. It is
  kept for auditability; the bytes are available in Git history.

## Current 0.4.0rc1

| Area | Evidence |
|---|---|
| Test/coverage log | [unit-tests.log](audit/0.4.0rc1/unit-tests.log) |
| Audit batches | [batch-3](audit/0.4.0rc1/batch-3.json), [batch-4](audit/0.4.0rc1/batch-4.json), [batch-5](audit/0.4.0rc1/batch-5.json), [batch-6](audit/0.4.0rc1/batch-6.json) |
| Distribution checks | [summary.json](audit/0.4.0rc1/summary.json) |
| Linux MCP isolation | [linux-isolation.json](audit/0.4.0rc1/linux-isolation.json) |
| macOS MCP isolation | [macos-isolation.json](audit/0.4.0rc1/macos-isolation.json) |
| Obsidian reading view | [obsidian.json](audit/0.4.0rc1/obsidian.json), [screenshot](audit/0.4.0rc1/obsidian-theorem.png) |
| Pinned arXiv corpus | [golden-arxiv.json](audit/0.4.0rc1/golden-arxiv.json) |
| Performance baseline | [benchmark.json](audit/0.4.0rc1/benchmark.json) |
| Workspace acceptance | [report.md](workspace-0.4.0rc1/report.md), [installed.json](workspace-0.4.0rc1/installed.json), [distributions.json](workspace-0.4.0rc1/distributions.json) |

## Functional evidence

| Directory | What it covers |
|---|---|
| [`baseline-0.3.0/`](baseline-0.3.0/) | Original prototype install/reproduction baseline |
| [`corpus/`](corpus/) | Multi-document registry import and migration |
| [`review/`](review/) | Typed-record validation, review decisions and apply |
| [`incremental/`](incremental/) | Full-vs-incremental equivalence and recovery |
| [`mcp/`](mcp/) | Read-only stdio client sessions |
| [`lean-experimental/`](lean-experimental/) | Unsupported Lean export/mapping/trust experiments |
| [`workspace-0.4.0rc1/`](workspace-0.4.0rc1/) | Current workspace acceptance and install replay |

## Historical releases

| Directory | What it covers |
|---|---|
| [`release-0.3.0/`](release-0.3.0/) | Fixed-commit 0.3.0 replay and installation checks |
| [`handoff-0.3.0/`](handoff-0.3.0/) | Original handoff evidence |
| [`legacy-report-0.3.0.md`](legacy-report-0.3.0.md) | Stage-by-stage historical report |

Historical reports and their links may describe superseded paths. Use
[the documentation index](../docs/README.md) for current behavior.
