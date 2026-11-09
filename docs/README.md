# QEC Graph documentation

Start with the [project README](../README.md) to install QEC Graph, import a
paper, and connect an MCP client.

| Use QEC Graph | What it covers |
| --- | --- |
| [Advanced usage](ADVANCED_USAGE.md) | Installation, workspace maintenance, queries, and migration |
| [Data and search](DATA_AND_SEARCH.md) | Record types, evidence, and search scope |
| [Workspace guide](rfc-002/WORKSPACE.md) | Configuration, archives, research review, and isolation |
| [Changelog](../CHANGELOG.md) | Changes to commands, output, and compatibility |

| Maintain or extend it | What it covers |
| --- | --- |
| [Architecture](01_ARCHITECTURE.md) and [graph contract](02_QEC_GRAPH_SPEC.md) | Source authority, graph relations, and snapshot invariants |
| [Splitter](03_SPLITTER.md) and [corpus](09_CORPUS.md) | Individual papers and legacy registries |
| [Incremental ingestion](11_INCREMENTAL.md) and [MCP protocol](12_AI_MCP.md) | Store, corpus, and fixed-session behavior |
| [Lean verification](13_LEAN_EXECUTION.md) | Builds, provenance, and trust boundaries |
| [Development entry point](../START_HERE.md) | Local setup, reproduction, and project conventions |
| [Audit remediation](AUDIT_REMEDIATION.md) | Recommendation status and verification evidence |
| [Contributing](../CONTRIBUTING.md), [security](../SECURITY.md), and [citation](../CITATION.cff) | Development checks, vulnerability reports, and citing the project |

The [initial implementation audit](../IMPLEMENTATION_AUDIT.md),
[RFC design pack](rfc-002/README.md), [prototype references](reference/EXAMPLE_EXPECTATIONS.md),
and [0.3.0 release notes](14_RELEASE.md) describe their recorded baselines.
For the workspace implementation and its tested boundaries, see the
[implementation report](rfc-002/IMPLEMENTATION.md) and
[acceptance report](../validation/rfc002/REPORT.md).
