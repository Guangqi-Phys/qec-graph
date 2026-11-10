# Operations and maintenance

> **Status: Current.** Daily workspace usage lives in the [user guides](../user/README.md).
> This section covers the supported legacy store/corpus surface, review and evidence.

> [!IMPORTANT]
> These pages assume you already have a checkout and a working Python
> environment. They do not replace the workspace guide for daily operations.

## On this page

- [Operations map](#operations-map)
- [Validation](#validation)
- [Benchmarks](#benchmarks)

## Operations map

| Page | Surface | Use when |
|---|---|---|
| [Legacy store and corpus maintenance](maintenance.md) | Legacy store/corpus | Ingest, validate, migrate or recover a single-paper store or corpus |
| [Corpus](corpus.md) | Legacy corpus | Register works/versions, map sources, run fixed-revision queries |
| [Review](review.md) | Legacy corpus | Validate typed records, bind evidence, apply reviewed proposals |
| [Workspace guide](../user/workspace.md) | Workspace | Current daily workflow (linked here for convenience) |
| [Advanced usage](../user/advanced-usage.md) | Workspace/CLI | Release checks, exit codes and grouped commands |

## Validation

Validation reports are evidence of their recorded inputs, commands and commits.
Check the report's scope before applying it to a newer build.

- [Validation index](../../validation/README.md)
- [Workspace acceptance report](../../validation/rfc002/REPORT.md)
- [Pinned arXiv fixture instructions](../../tests/golden/README.md)

## Benchmarks

Run `python tools/bench.py --out build/benchmark.json` for the generated
incremental workload. Pass `--archive-dir` to measure the six pinned arXiv
inputs. The report records raw samples, medians, runtime versions and query
settings; “fresh” means a new application store under ordinary OS caches.
See the [measured baseline](../../validation/audit-0.4.0rc1/benchmark.json).
