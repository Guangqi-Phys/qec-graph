# Codebase audit remediation

This ledger tracks section 9 of the 2026-11-09 codebase assessment, including
the related proposals in sections 3–8. The work started from `cfdb783`.
Each entry is complete only when its acceptance evidence has been checked.

| Item | Change | Status and evidence |
| --- | --- | --- |
| 1 | License and package metadata | In progress. Added the MIT notice for QEC Graph and PEP 639 metadata. A fresh wheel matched the source README and included the exact license. Twine and clean source-distribution verification are tracked in item 8. |
| 2 | CI on pull requests and pushes | Open. |
| 3 | Consistent status and explicit JSON output | Complete for workspace maintenance. Explicit and implicit workspace selection produce the same text. The CLI contract tests check exit code 2 in text and JSON, and release verification requests JSON explicitly. |
| 4 | Version, help, and usage exit code | Complete. CLI tests cover version, concise no-argument help, command help, and usage exit 64. The changelog documents the exit-code migration. |
| 5 | Validate review, claim-link, and experiment inputs | Complete. CLI tests reject missing or malformed fields before writing. Review and QEC validation suites pass. |
| 6 | Protect annotated stores from source-only split | Complete. The store checks the bound CURRENT manifest while holding the writer lock. The regression covers refusal, explicit replacement, and validation of the previous snapshot. |
| 7 | List, quarantine, and restore inbox packages | Open. |
| 8 | Build and check fresh release artifacts | Open. |
| 9 | Ignore generated state and development caches | Complete. Git ignore checks cover local graph state, macOS metadata, and coverage, lint, and test caches. |
| 10 | Documentation index and factual corrections | Open. |
| 11 | Separate CLI parsing, rendering, and dispatch | Open. |
| 12 | Stable error taxonomy and JSON error contract | Open. |
| 13 | Grouped help, examples, and alias migration | Open. |
| 14 | Query workspaces directly through the MCP query layer | Complete in `4067e6e`. Five CLI queries matched their tool results at a pinned release after CURRENT advanced. The workspace query suite passed. |
| 15 | Doctor, version command, and snapshot listing | Open. |
| 16 | Package all current schemas and expand research contracts | Open. Preserve validation across revisions and runtime-only invariants. |
| 17 | Single packaged software seed and explicit test fixtures | Open. |
| 18 | Organize documentation by purpose | Open. Preserve referenced entry points while migrating links. |
| 19 | CLI, renderer, schema, and docs tests with coverage | Open. |
| 20 | Lint, type, coverage, and pre-commit configuration | Open. |
| 21 | Consolidate validation evidence and index current runs | Open. Retain verifiable historical provenance. |
| 22 | Share storage and publication primitives | Open. |
| 23 | Share query logic across store, corpus, and workspace | Open. Preserve scope and evidence semantics. |
| 24 | Stage graph construction and test parser boundaries | Open. |
| 25 | Improve generated Obsidian pages and migration | Open. |
| 26 | Verify release artifacts before publication | Open. |
| 27 | Verify Linux and MCP isolation | Open. |
| 28 | Pin expected results for a real-paper corpus | Open. Check redistribution rights for any fixture committed to Git. |
| 29 | Add reproducible performance benchmarks | Open. |
| 30 | Single-source the version and evaluate the optional source layout | Open. |

The assessment also proposes contribution, security, citation, and change
history files, packaging the useful source distribution fixtures, documenting
all command contracts, and adding output and accessibility controls. Track
these alongside items 1, 8, 10, 12, and 13.

## Decisions requiring a different treatment

- Section 4.2 proposes deleting the ignored `qec_graph_codex_handoff/` tree.
  The directory can hold local copies and changes that Git cannot recover.
  Repository cleanup can document its historical role and keep it out of
  distributions without removing local data.
- The split repair must protect CURRENT even if another writer is active.
  A preflight in the CLI alone would leave a race. Implement the check inside
  the store writer lock and preserve the previous immutable snapshot.
