# Operations and maintenance

> **Status: Current.** Daily workspace usage lives in the [user guides](../user/README.md).
> This section covers the supported legacy store/corpus surface, review and evidence.

> **English** · [中文](README.zh-CN.md)

> [!IMPORTANT]
> These pages assume you already have a checkout and a working Python
> environment. They do not replace the workspace guide for daily operations.

## On this page

- [Operations map](#operations-map)
- [Validation](#validation)
- [Benchmarks](#benchmarks)

## Operations map

| Page | Surface | Type | Use when |
|---|---|---|---|
| [Legacy store and corpus maintenance](maintenance.md) | Legacy store/corpus | How-to | Ingest, validate, migrate or recover a single-paper store or corpus |
| [Corpus](corpus.md) | Corpus | Reference | Register works/versions, map sources, run fixed-revision queries |
| [Review](review.md) | Corpus | How-to / reference | Validate typed records, bind evidence, apply reviewed proposals |
| [Workspace guide](../user/workspace.md) | Workspace | How-to | Current daily workflow (linked here for convenience) |
| [Advanced usage](../user/advanced-usage.md) | Workspace/CLI | How-to / reference | Release checks, exit codes and grouped commands |

## Validation

Validation reports are evidence of their recorded inputs, commands and commits.
Check the report's scope before applying it to a newer build.

- [Validation index](../../validation/README.md)
- [Workspace acceptance report](../../validation/workspace-0.4.0rc1/report.md)
- [Pinned arXiv fixture instructions](../../tests/golden/README.md)

## Benchmarks

Run `python tools/bench.py --out build/benchmark.json` for the generated
incremental workload. Pass `--archive-dir` to measure the six pinned arXiv
inputs. The report records raw samples, medians, runtime versions and query
settings; “fresh” means a new application store under ordinary OS caches.
See the [measured baseline](../../validation/audit/0.4.0rc1/benchmark.json).
