# Codebase audit remediation

This ledger tracks section 9 of the 2026-11-09 codebase assessment, including
the related proposals in sections 3–8. The work started from `cfdb783`.
Each entry is complete only when its acceptance evidence has been checked.

| Item | Change | Status and evidence |
| --- | --- | --- |
| 1 | License and package metadata | Complete. Wheel and source distribution include the MIT license and PEP 639 metadata. Both passed strict Twine and source-content checks. |
| 2 | CI on pull requests and pushes | In progress. Added Linux and macOS jobs for lint, mypy, coverage, distribution verification, and installed workspace checks. Local equivalents passed. Hosted runs await the scheduled push. |
| 3 | Consistent status and explicit JSON output | Complete for workspace maintenance. Explicit and implicit workspace selection produce the same text. The CLI contract tests check exit code 2 in text and JSON, and release verification requests JSON explicitly. |
| 4 | Version, help, and usage exit code | Complete. CLI tests cover version, concise no-argument help, command help, and usage exit 64. The changelog documents the exit-code migration. |
| 5 | Validate review, claim-link, and experiment inputs | Complete. CLI tests reject missing or malformed fields before writing. Review and QEC validation suites pass. |
| 6 | Protect annotated stores from source-only split | Complete. The store checks the bound CURRENT manifest while holding the writer lock. The regression covers refusal, explicit replacement, and validation of the previous snapshot. |
| 7 | List, quarantine, and restore inbox packages | Complete. The lifecycle test verifies preserved bytes and receipt, a clear daily status, and restoration that refuses to overwrite a replacement. Explicit rebuild still checks every archived package. |
| 8 | Build and check fresh release artifacts | Complete for the source changes. A clean export of `ffdbb5e` passed strict Twine, exact metadata checks, wheel installation and workspace verification, and all 165 tests from the unpacked source distribution. Item 26 tracks publication automation. |
| 9 | Ignore generated state and development caches | Complete. Git ignore checks cover local graph state, macOS metadata, and coverage, lint, and test caches. |
| 10 | Documentation index and factual corrections | Complete. The README links to a current index. Corrected runtime requirements, locking, command entry points, MCP scope, and validation links, and marked historical reports. Checked Markdown link targets. Physical reorganization remains in item 18. |
| 11 | Separate CLI parsing, rendering, and dispatch | Open. |
| 12 | Stable error taxonomy and JSON error contract | Open. |
| 13 | Grouped help, examples, and alias migration | Open. |
| 14 | Query workspaces directly through the MCP query layer | Complete in `4067e6e`. Five CLI queries matched their tool results at a pinned release after CURRENT advanced. The workspace query suite passed. |
| 15 | Doctor, version command, and snapshot listing | Complete. CLI tests cover version, healthy and corrupt CURRENT diagnosis, an unchanged pointer, and listing both immutable store snapshots and unpublished registry candidates. |
| 16 | Package all current schemas and expand research contracts | In progress. Moved graph and annotations into the packaged schema directory and documented migration from checkout-only paths. Distribution checks compare all packaged schema bytes. Per-kind research contracts remain. |
| 17 | Single packaged software seed and explicit test fixtures | Complete. The deleted seed matched the packaged resource byte for byte. The synthetic fixture kept its historical SHA-256. Research and workspace query tests load the canonical inputs. |
| 18 | Organize documentation by purpose | Open. Preserve referenced entry points while migrating links. |
| 19 | CLI, renderer, schema, and docs tests with coverage | In progress. The full suite recorded 78% branch-aware coverage and passes the 70% gate. CLI contracts now have dedicated tests. Renderer, schema, and docs coverage remains. |
| 20 | Lint, type, coverage, and pre-commit configuration | Complete. The configured Ruff rules, mypy, pre-commit hooks, and 70% coverage gate passed locally. mypy checks annotated code across all 37 modules. Enabling checks inside every unannotated function exposed 107 existing issues and remains incremental type work. |
| 21 | Consolidate validation evidence and index current runs | Open. Retain verifiable historical provenance. |
| 22 | Share storage and publication primitives | Open. |
| 23 | Share query logic across store, corpus, and workspace | Open. Preserve scope and evidence semantics. |
| 24 | Stage graph construction and test parser boundaries | Open. |
| 25 | Improve generated Obsidian pages and migration | Open. |
| 26 | Verify release artifacts before publication | Open. |
| 27 | Verify Linux and MCP isolation | Open. |
| 28 | Pin expected results for a real-paper corpus | Open. Check redistribution rights for any fixture committed to Git. |
| 29 | Add reproducible performance benchmarks | Open. |
| 30 | Single-source the version and evaluate the optional source layout | Complete. The CLI, package metadata, and standalone build use the same version. A wheel installed in a fresh environment and ran its lifecycle from a separate workspace. The optional source move would disrupt supported checkout-based commands without fixing a demonstrated packaging failure. |

The assessment also proposes contribution, security, citation, and change
history files, packaging the useful source distribution fixtures, documenting
all command contracts, and adding output and accessibility controls. Track
these alongside items 1, 8, 10, 12, and 13.

## Decisions requiring a different treatment

- Section 4.2 proposes deleting the ignored `qec_graph_codex_handoff/` tree.
  The directory can hold local copies and changes that Git cannot recover.
  Repository cleanup can document its historical role and keep it out of
  distributions without removing local data.
- Section 3.3 treats a planned Intel macOS build as an available download.
  The v0.4.0rc1 release asset list on 2026-11-09 contained only Apple Silicon
  and the two Linux architectures. The README describes the published assets.
- The split repair must protect CURRENT even if another writer is active.
  A preflight in the CLI alone would leave a race. Implement the check inside
  the store writer lock and preserve the previous immutable snapshot.
