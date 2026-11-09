# Codebase audit remediation

This ledger tracks section 9 of the 2026-11-09 codebase assessment, including
the related proposals in sections 3–8. The work started from `cfdb783`.
Each entry is complete only when its acceptance evidence has been checked.

| Item | Change | Status and evidence |
| --- | --- | --- |
| 1 | License and package metadata | Complete. Wheel and source distribution include the MIT license and PEP 639 metadata. Both passed strict Twine and source-content checks. |
| 2 | CI on pull requests and pushes | Configured for Linux and macOS with lint, mypy, coverage, end-to-end replay, distribution verification, and installed workspace and isolation checks. Local checks passed, including the full suite on Python 3.11 and 3.13. Both jobs in the [third hosted run](https://github.com/Guangqi-Phys/qec-graph/actions/runs/42653380815) stopped before the first step with an account billing lock. |
| 3 | Consistent status and explicit JSON output | Complete for workspace maintenance. Explicit and implicit workspace selection produce the same text. The CLI contract tests check exit code 2 in text and JSON, and release verification requests JSON explicitly. |
| 4 | Version, help, and usage exit code | Complete. CLI tests cover version, concise no-argument help, command help, and usage exit 64. The changelog documents the exit-code migration. |
| 5 | Validate review, claim-link, and experiment inputs | Complete. CLI tests reject missing or malformed fields before writing. Review and QEC validation suites pass. |
| 6 | Protect annotated stores from source-only split | Complete. The store checks the bound CURRENT manifest while holding the writer lock. The regression covers refusal, explicit replacement, and validation of the previous snapshot. |
| 7 | List, quarantine, and restore inbox packages | Complete. The lifecycle test verifies preserved bytes and receipt, a clear daily status, and restoration that refuses to overwrite a replacement. Explicit rebuild still checks every archived package. |
| 8 | Build and check fresh release artifacts | Complete for the source changes. A clean export of `ffdbb5e` passed strict Twine, exact metadata checks, wheel installation and workspace verification, and all 165 tests from the unpacked source distribution. Item 26 tracks publication automation. |
| 9 | Ignore generated state and development caches | Complete. Git ignore checks cover local graph state, macOS metadata, and coverage, lint, and test caches. |
| 10 | Documentation index and factual corrections | Complete. The README links to a current index. Corrected runtime requirements, locking, command entry points, MCP scope, and validation links, and marked historical reports. Checked Markdown link targets. Physical reorganization remains in item 18. |
| 11 | Separate CLI parsing, rendering, and dispatch | Complete. `main()` delegates parsing, rendering, and command workflows. All 50 registered names are covered by the dispatch paths, and both module entry points and console scripts are preserved. The extraction matched 114 help and usage transcripts and passed the full test suite. |
| 12 | Stable error taxonomy and JSON error contract | Complete. The CLI uses versioned JSON errors on request, including fixed-scope query errors; MCP keeps its protocol. Tests cover missing paths and selectors, ambiguity, held writer locks, corrupt configuration and pointers, usage, stream isolation, and unexpected failures with `--debug`. Partial operations keep their actionable command reports. |
| 13 | Grouped help, examples, and alias migration | Complete. Grouped names share options, examples, and handlers with flat names. Legacy names get a controlled stderr notice, and everyday shortcuts stay visible and silent. Direct code, performance, and software queries share the fixed-release MCP contract. `review show` verifies exact proposal identity. `review import` queues a source-bound draft through the existing validator. Importing pre-approved decisions would bypass the existing reviewer and source bindings, so that interpretation was excluded. Subprocess tests cover both review paths and query parity. |
| 14 | Query workspaces directly through the MCP query layer | Complete in `4067e6e`. Five CLI queries matched their tool results at a pinned release after CURRENT advanced. The workspace query suite passed. |
| 15 | Doctor, version command, and snapshot listing | Complete. CLI tests cover version, healthy and corrupt CURRENT diagnosis, an unchanged pointer, and listing both immutable store snapshots and unpublished registry candidates. |
| 16 | Package all current schemas and expand research contracts | Complete. Graph and annotation schemas have one packaged copy. Research schema covers supported kinds, required fields, revision references, evidence metadata, domain values, matrix recipes, and managed assets. Runtime checks exact numeric representation, cross-field consistency, and provenance. The synthetic and software fixtures and 87 records from a fixed real release passed. |
| 17 | Single packaged software seed and explicit test fixtures | Complete. The deleted seed matched the packaged resource byte for byte. The synthetic fixture kept its historical SHA-256. Research and workspace query tests load the canonical inputs. |
| 18 | Organize documentation by purpose | Complete. The index separates user, design, operations, and archive pages, with a language and status guide. Design, maintenance, and prototype pages moved with forwarding links. The user guides retain their URLs and the hash-bound RFC inputs keep their original bytes and paths. |
| 19 | CLI, renderer, schema, and docs tests with coverage | Complete. The 211-test suite passed on macOS and Linux at 80.32% branch-aware coverage. Checks include both CLI streams, inline docs commands and links, archive rejection, all 26 research schema kinds, numeric evidence validation, and renderer migration and recovery. [Fifth batch evidence](../validation/audit-0.4.0rc1/fifth-batch.json) |
| 20 | Lint, type, coverage, and pre-commit configuration | Complete. Ruff, mypy, and pre-commit passed locally. Raised the coverage gate to 80% after testing it on both CI runtime versions. Enabling checks inside every unannotated function exposed 107 existing issues, so mypy remains gradual. |
| 21 | Consolidate validation evidence and index current runs | Complete. The migration reduced the tracked evidence tree to 57 files at `3f4f13a`, including current runs, stage summaries, and fixtures with byte-bound tests. All 574 historical paths restored from the documented Git commit matched the SHA-256 inventory, including duplicates and empty logs. |
| 22 | Share storage and publication primitives | Complete. Store, corpus, and workspace share the writer lock, pointer codec, and atomic replacement. Tests verify unchanged CURRENT after failed replacement in all three engines, lock contention between two ingest processes, and exact claim recovery after a real SIGKILL following publication. |
| 23 | Share query logic across store, corpus, and workspace | Complete. Store and corpus CLI and MCP calls use the same graph query session. Workspace context composes that session and applies the budget after adding fixed-release metadata. SQLite FTS ranking and the research overlay retain their own policies. Fixed-release parity, 22 stdio replay checks, and malformed Unicode recovery passed. |
| 24 | Stage graph construction and test parser boundaries | Complete. The graph builder names its identity, relations, resources, catalogue, annotations, proof, and projection stages. Four graphs and views matched the previous implementation byte for byte. Workspace ingestion separates inbox archiving, validated publication under its writer lock, and claim finalization. The parser tests increased branch-aware coverage from 79.60% to 83.85%, and six real source packages replayed successfully. |
| 25 | Improve generated Obsidian pages and migration | Complete. Pages include aliases, tags, source and evidence tables, eligible relations, grouped indexes, and status and change pages. Tests cover deterministic rendering, path migration, archived and restored links, collisions, unrelated files, and note isolation. The disposable Obsidian vault passed eight reading-view and link checks. [Verification and screenshot](../validation/README.md) |
| 26 | Verify release artifacts before publication | Implemented and verified locally. Tag builds gate GitHub Release on installer, installed CLI, wheel, and source archive checks and retain their reports. The manual PyPI workflow verifies already published distribution hashes and requires repository environment and Trusted Publisher setup. GitHub billing blocks hosted verification. |
| 27 | Verify Linux and MCP isolation | Complete locally. The production Compose profile passed 12 checks on Linux arm64 with Python 3.13.18. The macOS arm64 wheel passed all six OS permission checks and a pinned stdio query. Both profiles verified machine reads, denied writes and network access, and isolated private notes. The default Docker Hub base lookup timed out, so Linux used an alternate local Ubuntu base. CI includes both replays. |
| 28 | Pin expected results for a real-paper corpus | Complete. Six versioned arXiv source archives passed the pinned checksum, workspace import, provenance, and graph checks. The manifest records source and license URLs. The replay uses local archive copies. It tests the explicit entrypoint for the paper whose supplement can compile independently. |
| 29 | Add reproducible performance benchmarks | Complete. The benchmark records paired full and incremental ingestion, then optionally measures fresh sync, validation, pinned session creation, search, and context for six arXiv archives. The checked-in baseline includes raw samples, runtime versions, fixture identity, and exact query settings. |
| 30 | Single-source the version and evaluate the optional source layout | Complete. The CLI, package metadata, and standalone build use the same version. A wheel installed in a fresh environment and ran its lifecycle from a separate workspace. The optional source move would disrupt supported checkout-based commands without fixing a demonstrated packaging failure. |

The contribution and security guides and citation metadata are indexed and
included in source distributions. The changelog records command and output
migrations. Command contracts and accessibility controls are tracked in
items 12, 13, and 19.

The latest hosted attempt ended before either runner started a step. Hosted
CI and publication checks are deferred while the account is locked.
[GitHub Actions run](https://github.com/Guangqi-Phys/qec-graph/actions/runs/42657448620)

Follow-up CLI checks cover command spelling hints, configuration line and
column numbers, and the scope of `review list`. An explicit actor identifies
the legacy proposal form when its filename matches a read-only action.

The fifth batch checked the remaining local failure cases and recorded the
[verification results](../validation/audit-0.4.0rc1/fifth-batch.json):

- Items 5, 12, and 15: Reject malformed record imports, report corrupt review
  drafts and renderer status files with their paths, and have `doctor` test
  whether the active SQLite runtime can create an FTS5 index.
- Item 22: Reuse migrated assets after checking their hashes and sizes. Reject
  linked and special writer locks before ingest can change the workspace.
- Items 14 and 23: Honor exact record and metric revisions, keep integer
  coordinates exact, page results within the response limit, and preserve the
  fixed MCP release and its coverage if the operational status is damaged.

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
- The proposed deprecation of every flat name conflicts with the requested
  daily commands (`sync`, `status`, and `validate`). Keep those shortcuts
  and the direct evidence queries, and deprecate only redundant spellings.
- The proposed multi-line default workspace output conflicts with the requested
  one-line progress and outcome. Keep the compact default, add quiet and color
  controls, and expose detailed inspection through `--json` and `doctor`.
- An existing vault-level README may be a personal file. Publish the vault
  status guide and change summary under the owned `human/generated/` directory
  and link them from the generated index.
- Keep the four-part README requested for daily use. The observed demo,
  Obsidian screenshot, architecture diagram, release procedure, and citation
  are in the linked guides.
- Several example files are command inputs whose authoritative validation
  happens at runtime. Schema tests check the published schema examples and
  the persisted proposal produced from its example input.
- Keep `knowledge_starter/` at its published path for existing reproducers
  and checksum-bound legacy evidence. The documentation marks it as legacy.
- Use the dependency group in `pyproject.toml` for development. The older
  requirements files preserve install entry points and recorded environments
  used by historical validation reports.
- The full Ruff style set currently reports 2,577 long lines and 56 import
  ordering issues. Keep the correctness rules gated and separate broad
  formatting changes from the behavioral audit fixes.
