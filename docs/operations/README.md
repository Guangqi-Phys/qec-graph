# Operations and maintenance

- [Maintenance](maintenance.md): source changes, index rebuilds, backups, and recovery
- [Corpus](../09_CORPUS.md), [review](../10_VALIDATION_REVIEW.md), and [workspace migration](../user/workspace.md)
- [Release build and verification](../user/advanced-usage.md#installation-options) and [changelog](../../CHANGELOG.md)
- [Development entry point](../../START_HERE.md), [contributing](../../CONTRIBUTING.md), and [security reporting](../../SECURITY.md)
- [Citation metadata](../../CITATION.cff)
- [Audit remediation](../AUDIT_REMEDIATION.md), [validation evidence](../../validation/README.md), and [workspace acceptance](../../validation/rfc002/REPORT.md)

Validation reports are evidence of their recorded inputs, commands, and
commits. Check the report's scope before applying its results to a newer build.

Run `python tools/bench.py --out build/benchmark.json` for the generated
incremental workload. Pass `--archive-dir` to measure the six pinned arXiv
inputs too. The report includes raw samples, medians, runtime versions, and
query settings. Fresh means a new application store under ordinary OS caches.
See the [source instructions](../../tests/golden/README.md) and the
[measured baseline](../../validation/audit-0.4.0rc1/benchmark.json).
