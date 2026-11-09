# QEC Graph — Codebase Assessment and Remediation Plan

> **Status: Historical.** This assessment describes the pre-remediation layout at `8a8c858`/`a687005`.
> Some links point to modules that have since moved (for example `qecgraph/cli.py` is now
> `qecgraph/cli/`). Keep it for history; use [the documentation index](../../README.md) for current pages.


| | |
|---|---|
| **Review date** | 2026-11-09 |
| **Reviewed revision** | `8a8c858` (start of review), spot-checked through `a687005` |
| **Package version** | `0.4.0rc1` |
| **Scope** | the seven areas requested: task coverage, repository/doc layout, cleanliness, readability/maintainability, tests, error handling/flow completeness, and CLI/human-facing aesthetics |
| **Nature** | an independent, evidence-based review. It is not a release gate and changes no code |

> The repository was under active concurrent development throughout the review (HEAD advanced from `8a8c858` to `a687005` during the review). Line numbers refer to the reviewed snapshot and may drift. All claims below were checked against files or commands; unexecuted checks are labelled **not verified**.

---

## 0. Executive summary

QEC Graph is a **provenance-first LaTeX → QEC knowledge workspace**. Its core engineering is substantially better than the average research prototype: source bytes, Unicode coordinates, evidence states, review bindings, single-writer locks, atomic publication, archive hardening and MCP isolation are treated as first-class invariants. The two task briefs (`CODEX_TASK.md` P0–P5 and `docs/rfc-002/CODEX_UPDATE_TASK.md` U0–U6) are largely delivered, and the validation evidence is unusually honest about what was and was not executed.

It is **not yet a polished product**. Three problems dominate:

1. **Two architectures live side by side.** Store → corpus → workspace are three generations of storage, query, review and release logic, all still exposed in one 45-command CLI (42 visible in help). The new workspace model does not fully replace the old one.
2. **The documentation is split into two universes.** The current English user path (`README.md`, `ADVANCED_USAGE.md`, `DATA_AND_SEARCH.md`) coexists with a large, partly stale Chinese design corpus (`docs/01`–`14`, `docs/reference/`, the 1,574-line RFC) and three agent task briefs. Users cannot tell what is current without opening several files.
3. **Product hygiene is missing.** There is no `LICENSE`, no test CI, no changelog, no coverage gate, no linter/type-check gate, and the locally built wheel still packages a README that says version `0.3.0`.

Two concrete symptoms deserve emphasis because they break automation and trust:

- On a partial workspace, `qecgraph status` exits **2** and prints an error, while `qecgraph status --json` exits **0** and reports `"status": "ok"` for the same state. A monitoring script sees success; a human sees failure.
- Three commands (`deps`, `impact`, `context`) exist in the usage choices but are **absent from the help command list**, so they are effectively undiscoverable.

### Scorecard

| Dimension | Score | One-line verdict |
|---|---:|---|
| 1. Coverage of the two task briefs | **8.0 / 10** | P0–P5 delivered; U0–U6 mostly delivered, U3/U6 explicitly partial. |
| 2. Repository layout, docs, human-facing organisation | **4.0 / 10** | Rich content, poor information architecture; stale and duplicated docs. |
| 3. Cleanliness / legacy / duplication | **4.0 / 10** | 574 evidence files, a full legacy project copy, duplicate schemas and seeds, stale artifacts. |
| 4. Readability and maintainability | **5.5 / 10** | Good names and module docstrings, but a 441-line CLI `main`, no types, almost no comments, three parallel stacks. |
| 5. Tests: function and completeness | **6.5 / 10** | Strong targeted security/semantics tests; no CI, no coverage tool, no CLI contract tests, Lean path unexercised. |
| 6. Errors and workflow completeness | **5.0 / 10** | Precise domain errors in places, but raw `TypeError`/`Errno` leakage, no error taxonomy, colliding exit code 2, poisoned inputs with no exit. |
| 7. CLI and human-facing aesthetics | **4.0 / 10** | Flat 45-command surface (42 visible), 12/138 options documented, no `--version`, output mode depends on `--workspace`. |
| **Overall** | **5.4 / 10** | A strong research prototype with a weak product shell. |

### Top 12 actions, in order

1. Add `LICENSE` (MIT or Apache-2.0) and complete `pyproject.toml` metadata; rebuild release artifacts.
2. Add a real CI workflow (tests + lint + types + coverage + build) on every push/PR.
3. Remove the `--workspace`-dependent output switch; `--json` alone controls machine output; make `status` exit code and `--json` status agree.
4. Add `--version`, `--quiet`, `--debug` and a consistent exit-code/error-envelope contract; expose `help <topic>`.
5. Stop raw Python exceptions from reaching users (`review {}` currently prints a signature `TypeError`).
6. Guard `split` against silently repointing CURRENT of an annotated store.
7. Add `qec-graph inputs list|quarantine` (or equivalent) so a permanently failing package can leave the retry loop without deleting evidence.
8. Make `qec-graph search/show/context/deps/impact` work against `--workspace` directly; stop making `query-tool` the only CLI read path.
9. Merge the three query/storage/review stacks behind common interfaces, then split `cli.py`, `workspace.py` and `graph.build_graph`.
10. Single-source schemas and the software seed; delete the 130-byte root `$ref` stubs and the duplicate seed.
11. Restructure docs into user / design / operations / archive, with one index and explicit status labels.
12. Make the Obsidian vault human-readable: front matter, link aliases, readable filenames, tables instead of raw JSON dumps.

---

## 1. Scope, method, and what was actually run

### 1.1 Snapshots

The worktree changed during the review. The main analyses were performed at `8a8c858` (`fix(archive): bound ZIP directory entries...`). The tree was re-checked at `a687005`; the post-snapshot changes were confined to `registry.py`, `store.py`, `workspace.py`, `research_store.py`, `workspace_assets.py` and their tests, with no CLI or documentation changes, so the findings remain valid. This document does not claim to review every later commit.

### 1.2 Commands executed

| Check | Command | Result |
|---|---|---|
| Unit suite (review start) | `.venv/bin/python -m unittest discover -s tests` | 153 tests, OK, 11.3 s (a pristine `git archive` of `8a8c858` gave 152; one concurrent test edit explains the drift) |
| Unit suite (final HEAD) | same | 158 tests, OK, 10.2 s (`a687005`) |
| End-to-end reproduce | `.venv/bin/python tools/reproduce.py --out build/review-reproduce` | exit 0; split, ingest, three views, SQLite, schema checks, bounded HGP check |
| Workspace lifecycle | `init`, `sync`, `sync --dry-run`, `status`, `validate`, `rebuild`, `human build`, `mcp-config`, `query-tool` | behaviour recorded in §6 and §7 |
| Packaging inspection | `unzip`/`tar` of `build/rfc002-*/*.whl` and `*.tar.gz` | wheel/sdist metadata and README inspected |
| Link check | relative links in `docs/`, `README.md`, `START_HERE.md`, task briefs | 0 broken relative links |

### 1.3 Not verified

- **Lean builds** — `lake` is not available in this environment; P5 and U4/U5 Lean claims were reviewed from validation logs, not re-executed.
- **Docker / Linux** — no Docker daemon; macOS arm64 + Python 3.15.2 only.
- **Windows** — untested by the project and by this review.
- **Real-paper golden set** — the review did not download the arXiv source; workspace tests used the bundled synthetic paper.
- **Obsidian GUI** — vault files inspected, but not opened in Obsidian.
- **Coverage.py** — not installed; the test audit used a stdlib `trace` proxy (81.8% line coverage, no branch coverage).

---

## 2. Implementation status against the two task briefs

The repository contains two sequential specifications:

- **First brief:** `CODEX_TASK.md` + `docs/08_ROADMAP_ACCEPTANCE.md`, stages **P0–P5**.
- **Second brief:** `docs/rfc-002/CODEX_UPDATE_TASK.md` + `QEC_GRAPH_DESIGN_UPDATE.md`, stages **U0–U6**.

They are not alternatives: the RFC builds on the P0–P5 prototype. The code reflects that, and so does the assessment below.

### 2.1 First brief: P0–P5

| Stage | Status | Evidence in the codebase | Residual gap |
|---|---|---|---|
| **P0** — fixed prototype and reproduction loop | ✅ Delivered | `splitter.py` delegates to `store.ingest`; `qecgraph split`, `qec-graph split`, `qec-latex-split`, `split_project` share one pipeline; `tools/reproduce.py` runs the suite and demo | Reproduction is developer-oriented; no CI execution |
| **P1** — multi-document registry and claim identity | ✅ Delivered | `registry.py`, `corpus.py`, `migrations.py`; namespace-qualified source versions and entity revisions; cross-document queries | Two identity systems: legacy `record.v3` and new `research.v1` |
| **P2** — typed validation and review/apply transaction | ✅ Delivered | `validators/`, `review.py`, `status.py`; stale-review invalidation, asset/source revalidation, SCC audit | Review/apply is corpus-only; workspace has a separate proposal/decision flow |
| **P3** — incremental rebuild and watch | ✅ Delivered | `incremental.py`, `watch.py`, content-checked AST reuse, full semantic rebuild, writer lock, atomic pointer switch, recovery | No multi-writer/stress test; watch is polling-only |
| **P4** — read-only AI interface and MCP | ✅ Delivered | `ai_tools.py`, `mcp_server.py`, real stdio tests, fixed release, budgets and truncation, resource reads | Two tool catalogues (store/corpus vs workspace); CLI workspace queries missing |
| **P5** — Lean declarations, dependencies, verification export | ✅ Delivered, narrow scope | `lean.py`, `lean_integration.py`, pinned 4.19.0, actual builds and axiom audits in `validation/p5/`; core-only Bool example | Semantic mapping still `pending`; HGP distance not formalised; not re-run in this review |

**Assessment:** the first brief is essentially complete as scoped. The engineering around provenance, review invalidation, atomic publication and MCP is the strongest part of the repository.

### 2.2 Second brief: U0–U6

| Stage | Status | Evidence | Residual gap |
|---|---|---|---|
| **U0** — audit, compatibility, baseline | ✅ Delivered, now stale | `IMPLEMENTATION_AUDIT.md` | Pinned to the 0.3.0 baseline while the project is 0.4.0rc1; misleading as a top-level "current capability" document |
| **U1** — domain schema, typed relations, unknown/evidence, software catalog | ✅ Delivered | `research.py` (26 kinds, 41 relations), `validators/research.py`, `software.py`, seed adapter, field evidence | Published `research.v1.schema.json` validates only the envelope; per-kind rules live only in Python |
| **U2** — installable package, workspace, archive transaction, init/sync/rebuild, recovery | ✅ Delivered | `workspace.py`, `source_package.py`, receipts, content-addressed archive, single-writer lock, atomic release, partial-batch recovery | No input quarantine; Docker/Linux not executed; local wheel metadata stale |
| **U3** — two-pass extraction, rule/LLM proposals, review, selection, coverage | ⚠️ Partial | `extraction.py` two-pass code-mention rules; `semantic.py` local provider handoff; `review-list`; coverage tool | No LLM integration (by design), no curve digitisation, no cross-table experiment attribution; most domain fields still manual |
| **U4** — fixed-snapshot queries, read-only MCP, source context, human isolation | ✅ Delivered | `workspace_query.py`, `mcp_server.py`, `qec://source/...` resources, strict machine mount, macOS isolation report | Apple-only isolation proof; Docker profile parsed but not run; no CLI equivalent for workspace reads |
| **U5** — deterministic human renderer, stable links, notes protection, recovery | ✅ Delivered | `human.py`, per-page atomic replacement, tombstones, `human_stale` recovery, notes symlink tests | Aesthetics are weak; no Obsidian GUI test; no golden-page tests |
| **U6** — data migration, install/upgrade/cross-platform, real-paper regression | ⚠️ Partial | `workspace_migration.py`, 0.3.0 → 0.4.0 replay, one real paper (Subsystem Codes v1), wheel/sdist build | macOS only; no PyPI publication; sizeable portions of U6 (Linux, public index, broader golden corpus) remain |

**Assessment:** roughly **70–75% of the full RFC vision** is implemented, but a much higher share of the RFC's must-deliver core. The gaps are mostly the explicitly acknowledged ones (LLM, digitisation, broader real-paper corpus, non-macOS platforms), not hidden failures.

### 2.3 Domain invariants — the strongest part

The project consistently preserves distinctions that are easy to collapse:

- source block ≠ normalised claim (`graph.py`, `research.py`);
- `references` ≠ proof dependency; `\leanok` ≠ verified (`test_pipeline.py`, `docs/05_LEAN.md`);
- candidate/stale/unbound states are filtered by default and observable in audit views (`status.py`, `query.py`);
- upper bounds never satisfy lower-bound filters (`domain_query.py`, `test_qec_validation.py`);
- unknown values are `null`/`unknown` with reasons, not `false`;
- review binds the exact content hash and source revision; a changed input produces `stale`, not a silent pass (`review.py`, `status.py`);
- `human/notes/` is never read by generators or MCP (`human.py`, `test_human.py`);
- archives are rejected for traversal, links, special files, forged ZIP counts and oversized members (`source_package.py`).

This is the repository's core asset and should not be weakened during cleanup.

### 2.4 What is genuinely missing (as opposed to merely unimplemented-by-choice)

| Missing capability | Impact | Status in docs |
|---|---|---|
| Per-kind machine-readable `research.v1` schema | External consumers cannot validate records without Python | Not disclosed clearly; schema looks complete |
| Workspace-level CLI query surface | Users must use MCP or `query-tool` to read their own workspace | Partially disclosed in `DATA_AND_SEARCH.md` |
| Input quarantine / acknowledgement | A permanently bad package keeps every sync/status at exit 2 | Design mentions quarantine; no command |
| `split` safety on an existing annotated store | Silently repoints CURRENT to a source-only snapshot | Warned in `03_SPLITTER.md`, not enforced |
| `--version`, `doctor`, `inputs`, `snapshot list` | Basic operational tooling absent | Not documented |
| CI on push/PR | Regressions can land without tests | Only tag-triggered release workflow |
| License / changelog / contributing / security policy | Cannot be safely consumed or contributed to | Absent |

### 2.5 Release and claim consistency

A release candidate exists locally (`build/rfc002-release/qec_graph-0.4.0rc1-py3-none-any.whl`, built 15:18). Inspection shows:

- `METADATA` version is `0.4.0rc1`, but its embedded README says **"当前版本 0.3.0"** and is the old Chinese README;
- there is **no `License` field** and no `licenses/` directory in the wheel;
- the source `README.md` was rewritten in English at 18:08, after the artifact was built, so the artifact is stale;
- `docs/rfc-002/IMPLEMENTATION.md` claims the release README was updated in the same batch — it was not;
- `validation/rfc002/REPORT.md:9` reports "116 项测试通过". That figure matches commit `71c7904` (the release build), not the reviewed snapshot (152 tests) or the current HEAD (158). No archived test log or `results.json` accompanies the 0.4.0 acceptance report — the report points at gitignored `build/` output — while the historical 0.3.0 validation has 574 files. The evidence is inverted: the old release is over-documented and the current one under-documented.

This is a release-process defect, not a code defect, and it is exactly the kind of thing a CI release gate would catch.

A second release-completeness issue: the 0.4.0 acceptance report is backed by only **four small JSON files (under 10 KB)** under `validation/rfc002/`, while the 0.3.0 history keeps 574 files. The current report asserts real end-to-end, MCP, isolation and migration checks, but the raw outputs needed to re-check those assertions are not archived. Either archive them or explicitly mark the report as a summary backed by external artifacts.

### 2.6 Documentation reality check

- 30 markdown files under `docs/` excluding this report (4,760 lines, 383 KB) plus 5 root-level markdown files.
- **27 of 30 docs are Chinese-dominant**; the English user path is only README, ADVANCED_USAGE and DATA_AND_SEARCH.
- All 14 numbered docs (`01`–`14`) predate RFC-002: grep finds **zero mentions of `workspace`, `research.v1`, `human/` or `0.4.0rc1`** in them. The current product lives only in `docs/rfc-002/WORKSPACE.md` + `IMPLEMENTATION.md`.
- 200 relative links checked, **0 broken**; the problem is missing index/navigation, not broken links.
- 11 markdown files have zero outbound links, including `docs/03_SPLITTER.md`, `docs/11_INCREMENTAL.md` and `docs/rfc-002/README.md`.
- The English README has **no link to `START_HERE.md`, `docs/` or any index**; the only near-index is a Chinese page that routes readers to the superseded P0–P5 material.

---

## 3. Repository layout, documentation, and human-facing organisation

### 3.1 Current tree (trimmed)

```text
qec-graph/
├── AGENTS.md, CODEX_TASK.md, START_HERE.md, IMPLEMENTATION_AUDIT.md   # 4 process/agent docs at root
├── README.md                                                          # English user entry
├── pyproject.toml, MANIFEST.in, 4× requirements*.txt
├── install.sh, Dockerfile, compose.yaml, compose.mcp-isolated.yaml
├── qecgraph/                     # ~8,600 lines, 37 modules
├── schemas/                      # 7 files, 4 of them 130-byte $ref stubs
├── tests/                        # 24 files, ~3,600 lines
├── tools/                        # 11 scripts, ~1,230 lines
├── examples/                     # synthetic paper + JSON examples
├── knowledge_starter/            # nested legacy project with its own AGENTS.md
├── docs/
│   ├── 01…14_*.md                # old design/operations corpus
│   ├── ADVANCED_USAGE.md, DATA_AND_SEARCH.md, IMPLEMENTATION_LOG.md
│   ├── reference/                # previous prototype docs
│   ├── adr/                      # 3 ADRs
│   └── rfc-002/                  # task brief + 1,574-line design + duplicate seed
├── validation/                   # 574 tracked files, 7.8 MB, p0–p5 + release + rfc002
├── lean/                         # 11 tracked source files (+ ignored .lake build)
├── deploy/                       # deployment notes/files
├── build/, dist/, *.egg-info/    # ignored local artifacts
├── qec_graph_codex_handoff/      # ignored full old project copy
├── .qecgraph/, .codegraph/       # untracked runtime/code-index dirs, not in .gitignore
```

| Folder | Intended function | Fit / problem |
|---|---|---|
| `qecgraph/` | runtime library + CLI | Clear, but mixes three storage/query generations |
| `tests/` | regression suite | Good coverage of invariants; no CLI contract tests |
| `tools/` | reproducers and release checks | Useful but ad hoc; several require external Lean/wheel/binaries |
| `examples/` | small synthetic inputs | Good; not a substitute for a real-paper golden set |
| `schemas/` | public schema files | Duplicated/stubbed; graph/annotations not packaged |
| `knowledge_starter/` | legacy schema sample | Misfit at root; nested project with its own AGENTS.md |
| `docs/` | product + design documentation | Mixed current/historical; no index |
| `validation/` | executed evidence | Valuable but 74% of tracked files and 72% of tracked bytes |
| `lean/` | Lean project + export fixtures | Clear, but build outputs are local-only |
| `deploy/` | container/isolation notes | Small, not linked from the main docs |

### 3.2 Two documentation universes

There are effectively four layers of documentation with no single index:

1. **Current user path (English):** `README.md` → `ADVANCED_USAGE.md` → `DATA_AND_SEARCH.md` → `docs/rfc-002/WORKSPACE.md`.
2. **Old design/operations corpus (Chinese):** `docs/01`–`14`, written for the P0–P5 prototype.
3. **The RFC pack (Chinese):** task brief, 1,574-line design, `IMPLEMENTATION.md`, `WORKSPACE.md`, design-validation JSON.
4. **Historical/evidence:** `docs/reference/`, `docs/IMPLEMENTATION_LOG.md`, `validation/`, `knowledge_starter/`.

`START_HERE.md` tries to bridge them ("本页下方的 P0–P5 文档仍适用于原有三图、Lean 与旧 corpus"), but it is itself Chinese, ships agent-oriented instructions, and points at the stale `IMPLEMENTATION_AUDIT.md` as a way to "核对真实能力". A new user following the English README never sees it.

### 3.3 Specific stale or contradictory docs

| File:line | Claim | Reality |
|---|---|---|
| `AGENTS.md:8` | "当前代码是单工程原型" | The repo implements workspace, registry, MCP, human and Lean; the guidance is stale |
| `docs/01_ARCHITECTURE.md:127` | "原型没有跨进程写锁" | `transactions.writer_lock` uses `fcntl.flock`; used by store, registry, review, workspace |
| `docs/02_QEC_GRAPH_SPEC.md:11-26` | Baseline table presents multi-doc registry, review/apply, incremental, MCP, Lean as "后续目标" | All are implemented |
| `docs/02_QEC_GRAPH_SPEC.md:185` | "本规范不声称已经具备多文档注册表、审核事务、watch、MCP 或 Lean 导出" | All are implemented |
| `docs/03_SPLITTER.md:9` | Dependency fixed to `pylatexenc==2.10` only | `jsonschema==4.26.0` is also a runtime dependency |
| `docs/03_SPLITTER.md:15` | "包名为 qec-graph，版本为 0.2.0"; "安装后提供三个命令" | Package version 0.4.0rc1 (`0.2.0` is `PARSER_VERSION`); four entry-point scripts |
| `docs/03_SPLITTER.md:223` | "新增的 test_splitter.py 含 8 项集成测试" | 10 tests now |
| `docs/06_MAINTENANCE.md` | Daily flow is `ingest`/`show`/`deps` on a store | Product daily flow is `init`/`sync`/`status`/`validate` |
| `docs/07_CODEGRAPH_MAPPING.md:24` | "当前仅显式全量 ingest" | `incremental.py` and `watch.py` exist |
| `docs/07_CODEGRAPH_MAPPING.md:53-65` | Module map omits workspace/research/human modules | 37 modules now; map is P1-era |
| `docs/08_ROADMAP_ACCEPTANCE.md:7` | References `validation/results.json` | File does not exist |
| `docs/08_ROADMAP_ACCEPTANCE.md:110` | "当前本交付包没有 MCP 服务" | MCP is implemented and tested |
| `docs/12_AI_MCP.md:41` | "提供以上五个工具" | Correct for store/corpus; workspace MCP has a larger tool set — scope not stated |
| `docs/14_RELEASE.md:1` | "0.3.0 验收与复现" | Current version 0.4.0rc1; `tools/reproduce_workspace.py` is the current install check |
| `IMPLEMENTATION_AUDIT.md:7` | "已有实现（0.3.0）" | 0.4.0rc1 implementation is far ahead; 87-test baseline |
| `docs/rfc-002/README.md:5` | "不包含本次新增功能的已完成程序" | The features are implemented in the repo |
| `docs/rfc-002/README.md:9-15` | File table omits `IMPLEMENTATION.md` and `WORKSPACE.md`; no links | Both are the current status/usage docs |
| `docs/rfc-002/CODEX_UPDATE_TASK.md:13` | Synthetic fixture at `examples/...` | Actual path is `docs/rfc-002/examples/...` |
| `docs/reference/prototype_README.md:142` | `--catalog ../qec_knowledge_starter/records` | Path does not exist |
| `CODEX_TASK.md:59` | "最小安装只有 pylatexenc==2.10" | `jsonschema` is required at runtime |
| `README.md:14` | Downloads for Apple Silicon and Linux x86_64/arm64 | `install.sh:15` and the release workflow also build macOS x86_64 |
| `docs/rfc-002/DESIGN_VALIDATION.json` | `"implementation_tested": false`, `"user_current_repository_inspected": false` | Historical design-pack self-check; misleading beside real validation |
| `validation/rfc002/REPORT.md:9` | 116 tests | 116 at release commit `71c7904`; 152–158 now |

Relative links themselves are in good shape: a check of all markdown relative links found **0 broken targets**. Three docs are unreferenced: `docs/14_RELEASE.md`, `docs/reference/EXAMPLE_EXPECTATIONS.md`, `docs/reference/prototype_README.md`.

### 3.4 Command documentation coverage

Of the 45 distinct CLI command names, only **22** appear in the current user docs (`README`, `ADVANCED_USAGE`, `DATA_AND_SEARCH`, `WORKSPACE`). Undocumented in the user path include `human-build`, `software-*`, `research-import`, `review-list`, `lean-*`, `serve-mcp`, `watch`, `recover-store`, `validate-staged`, `audit-dependencies`, `apply`, `review-decide`, `check-css`, `check-experiment`, `migrate`, `migration-import`, `record-add`, `claim-link`, `show`.

Some are documented only in the old numbered corpus; some are not documented anywhere user-facing.

### 3.5 Language and audience

- `README.md`, `ADVANCED_USAGE.md`, `DATA_AND_SEARCH.md`: English, user-facing, good quality.
- `docs/01`–`14`, `START_HERE.md`, `CODEX_TASK.md`, RFC docs: Chinese, partly agent-facing.
- `AGENTS.md`: Chinese engineering rules for agents.
- Error messages: English.

For an open-source repo this is a deliberate choice, but it is not stated. A reader cannot tell whether Chinese docs are current or historical. **Recommendation:** make English the canonical user language, keep Chinese design/process docs under an explicit `archive/` or `zh/` path with a language banner, and add `README.zh-CN.md` for the Chinese quick start.

### 3.6 Proposed target documentation tree

```text
README.md                      # English, 5-minute quick start, screenshots/GIF
README.zh-CN.md                # Chinese quick start (optional, linked)
LICENSE
CHANGELOG.md
CONTRIBUTING.md
SECURITY.md
CITATION.cff
docs/
├── README.md                  # single index + status legend (Current / Design / Historical / Evidence)
├── user/
│   ├── install.md             # curl installer, wheel, from source, uninstall
│   ├── workspace.md           # init/sync/status/validate/rebuild, config, entrypoints
│   ├── query.md               # search/show/context/deps, codes, performance, CLI + MCP parity
│   ├── obsidian.md            # vault layout, notes, tombstones, recovery
│   ├── review.md              # proposals, decisions, apply, extraction handoff
│   ├── troubleshooting.md     # error catalogue, exit codes, doctor, quarantine
│   └── faq.md
├── design/
│   ├── architecture.md        # rewritten from 01
│   ├── data-model.md          # rewritten from 02 + 04
│   ├── extraction.md          # rewritten from 03
│   ├── lean.md                # rewritten from 05 + 13
│   ├── security.md            # threat model, archive/MCP/human isolation
│   └── adr/                   # 0001-… (keep)
├── operations/
│   ├── maintenance.md         # rewritten from 06
│   ├── release.md             # rewritten from 14, current version
│   ├── migration.md           # 09 + 11 + workspace-migrate
│   └── validation.md          # how to run and read evidence
├── archive/
│   ├── README.md              # what is historical and why
│   ├── tasks/                 # CODEX_TASK.md, START_HERE.md, RFC task brief
│   ├── rfc-002/               # design update, implementation log, design validation
│   ├── prototype/             # docs/reference/
│   └── validation/            # summaries + links to evidence artifacts
└── schemas/                   # generated/published copies or pointers, see §4.3
```

Migration mechanics:

1. Add `docs/README.md` and a one-line banner to every historical file: `> Historical. Current: [link].`
2. Move, don't delete, historical material in one commit; keep GitHub URLs working via stub pages if external links exist.
3. Rewrite the six current user docs by merging overlapping content; delete duplicate command examples.
4. Add a docs link-check (`lychee`) and a "commands in docs exist" test to CI.

### 3.7 Human-facing README

The current README (46 lines) is clean and task-oriented, but it under-sells the product: no screenshot of the Obsidian vault, no sample query output, no architecture diagram, no "what this is not" boundary, no version. Add:

- one-sentence "what it does" + one-sentence "what it does not do";
- a 20-second demo (`init` → `sync` → `status` → `search`) with real output;
- a vault screenshot;
- links to user docs, MCP setup, limitations, license, citation.

---

## 4. Repository cleanliness and duplication

### 4.1 Tracked evidence dominates the repository

| Area | Tracked files | Size | Assessment |
|---|---:|---:|---|
| `validation/` | **574** | **7.8 MB** | 13 separate `results.json`, duplicated p5/release Lean runs, 321 `.txt` logs |
| `knowledge_starter/` | 33 | 172 KB | Nested legacy project with its own `AGENTS.md`, `docs/`, schemas, tools |
| `docs/reference/` | 5 | 40 KB | Old prototype documentation |
| `docs/rfc-002/` | 9 | 196 KB | Includes a 118 KB design doc and a byte-identical seed |
| `qec_graph_codex_handoff/` | untracked | full old copy | Ignored, but still on disk; confusing to anyone browsing |

`validation/` is valuable evidence, but it is not source code and should not be the second-largest tree in the repo. It accounts for **574 of 773 tracked files (74%)** and about **72% of tracked bytes**. The content is highly redundant:

- 574 files collapse to **174 unique non-empty contents** plus one empty blob;
- **171 files are zero-byte**, and 2.58 MB (37%) is exact duplicate content;
- `validation/p5` has 240 files but only 61 unique contents; `validation/release` has 301 files and 120 unique;
- `validation/release/fixed` alone is 224 files / 2.14 MB, with 88 files duplicated outside `fixed`;
- the same Lean `export.json` (156 KB) appears in at least four run directories; `results.json` is copied per stage.

The full local checkout is about **4.0 GB**: `build/` 2.2 GB (175,431 files), `.codegraph/` 11 MB, `dist/` 20 MB, `qec_graph_codex_handoff/` 1.5 MB. Only `build/`, `dist/` and the handoff copy are gitignored, so they do not affect the published repo, but they make local review, backup and "is my tree clean?" checks noisy.

**Recommendation:** keep per-stage **summaries** (`REPORT.md` + small JSON manifest) in `docs/archive/validation/`; move raw logs/artifacts to a separate `qec-graph-evidence` repository or GitHub Release assets; add a checksum manifest and a retention rule. At minimum, deduplicate exact contents and drop zero-byte logs. If raw evidence must stay in-tree, put it under `validation/` with a `README.md`, a stage/commit/command/result table, and Git LFS for large files.

### 4.2 Legacy trees at the root

- **`qec_graph_codex_handoff/`** is a full pre-RFC copy of the project (including `qecgraph/`, `tests/`, `docs/`, `validation/`). It is gitignored, so it is invisible to GitHub but present locally and in archives. Delete it or move it outside the repo.
- **`knowledge_starter/`** is a complete nested project. Its `AGENTS.md` competes with the root `AGENTS.md`; its `MANIFEST.sha256` suggests it is a separate deliverable. It is still used by `tools/reproduce.py` and tests. Move it to `legacy/knowledge_starter/` (or `tests/fixtures/legacy/`) and add a top-level `legacy/README.md`.
- **`docs/reference/`** has good historical banners, but sits inside the current docs tree. Move to `docs/archive/prototype/`.
- **`IMPLEMENTATION_AUDIT.md`**, `CODEX_TASK.md`, `START_HERE.md` are process artifacts, not product docs. Move to `docs/archive/tasks/`; keep `AGENTS.md` at root because agents expect it.
- **`.qecgraph/` and `.codegraph/`** are untracked and not in `.gitignore`. Add them, and consider refusing to create a workspace lock in the repository root (the current `.qecgraph/.writer.lock` is a stray from a local run).

### 4.3 Schema duplication

There are **15** schema-like JSON files in the tracked source tree, in three locations (plus copies inside the ignored handoff directory):

- root `schemas/` — `graph`, `annotations` (real), plus `record.v2`, `record.v3`, `proposal.v1`, `review.v1`, `lean-export.v1` as **130-byte `$ref` stubs** pointing into the package;
- `qecgraph/validators/schemas/` — the real `record.v2`, `record.v3`, `proposal.v1`, `review.v1`, `lean-export.v1`, `research.v1`;
- `knowledge_starter/schemas/` — the legacy `record.schema.json` and `matrix.schema.json`.

Consequences:

- The wheel contains only the package schemas; `graph.schema.json` and `annotations.schema.json` are **not shipped**, even though the docs call them current contracts.
- The root stubs are ambiguous: are they contracts or pointers? Tools that read `schemas/record.v3.schema.json` get a `$ref` with a relative path that only works in a source checkout.
- `research.v1.schema.json` is only 1,580 bytes and validates the envelope, not the 26 record kinds. The legacy `record.v3` schema is 29,893 bytes and far stricter than the new primary contract.

**Recommendation:** choose one canonical location. Prefer `qecgraph/validators/schemas/` (packaged, used by runtime), add `graph.schema.json`/`annotations.schema.json` there, include all in `[tool.setuptools.package-data]`, and generate root `schemas/` copies (with a header + hash) only if a stable URL is required. Add a CI test that every root copy equals the packaged file. Publish a full `research.v1` schema or state explicitly that the Python validator is normative and the JSON Schema is envelope-only.

### 4.4 Duplicate seed and misplaced fixtures

`docs/rfc-002/software_catalog.seed.json` is **byte-identical** to `qecgraph/catalog/software_catalog.seed.json` (SHA-256 `64e930e7…`). Tests load the docs copy (`tests/test_research.py:39`, `tests/test_workspace_query.py:124`) rather than the packaged seed. The synthetic fixture lives in `docs/rfc-002/examples/performance_context.synthetic.json` and is used by tests.

**Recommendation:** delete the docs copy; load the packaged seed via `software.bundled_seed()`; move the synthetic fixture to `tests/fixtures/performance_context.synthetic.json`; update docs to link to the fixture.

### 4.5 Packaging and project hygiene

| Item | Status | Recommendation |
|---|---|---|
| `LICENSE` | **Missing** | Add MIT (compatible with the MIT CodeGraph reference; add NOTICE if any code is copied) or Apache-2.0 |
| `pyproject.toml` license/authors/urls/classifiers | Missing | Add PEP 639 `license`, `license-files`, authors, URLs, keywords, classifiers |
| `CHANGELOG.md` | Missing | Add Keep a Changelog format; link from `pyproject` |
| `CONTRIBUTING.md` | Missing | Add dev setup, test/lint commands, commit conventions, evidence policy |
| `SECURITY.md` | Missing | Add threat model (untrusted archives, MCP scope, human isolation) and reporting path |
| `CITATION.cff` | Missing | Research software should have a citation file |
| CI test workflow | **Missing** | Only `.github/workflows/standalone-release.yml`, triggered on tags |
| Coverage / lint / type check | Missing | Add `coverage.py`, `ruff`, `mypy` (or `pyright`) + configs |
| `requirements*.txt` (4 files) | Redundant | Use `pyproject` dependency groups + a generated lock file |
| Root `schemas/` stubs | Duplicated | See §4.3 |
| `README.md:14` platform claim | Omits macOS x86_64 although `install.sh` and the release workflow build it | Fix README or drop the target |
| Stale wheel/sdist | Present | Rebuild from a clean tag; verify README/version/license |
| `packaged README` | Says 0.3.0 | Fix release gate |
| `.gitignore` | Missing `.qecgraph/`, `.codegraph/`, `htmlcov/`, `.coverage`, `.ruff_cache/`, `.mypy_cache/` | Add |
| `MANIFEST.in` | Prunes tests/docs/examples | Include tests (and current user docs) in sdist; prune only large historical evidence |

### 4.6 Disposition table

| Path | Verdict | Action |
|---|---|---|
| `qec_graph_codex_handoff/` | Delete | Remove from disk; add to `.gitignore` (already ignored) |
| `knowledge_starter/` | Keep, relocate | `legacy/knowledge_starter/` + README; update tests/tools/docs |
| `docs/reference/` | Keep, archive | `docs/archive/prototype/` |
| `docs/01`–`14` | Keep, rewrite/archive | User/ops docs rewritten; old numbered files become `docs/archive/design-v0.3/` with banners |
| `docs/rfc-002/` | Archive mostly | Move task brief/design/validation to `docs/archive/rfc-002/`; keep `WORKSPACE.md` as the base of `docs/user/workspace.md`; delete duplicate seed |
| `IMPLEMENTATION_AUDIT.md` | Archive | `docs/archive/rfc-002/`; update START_HERE or remove START_HERE |
| `CODEX_TASK.md`, `START_HERE.md` | Archive | `docs/archive/tasks/`; root README is the entry |
| `validation/p0`–`p5`, `handoff`, `release` | Consolidate | Summaries + manifests in `docs/archive/validation/`; raw logs out of tree |
| `validation/rfc002` | Keep summary | Keep `REPORT.md` and small JSON; link artifacts |
| `schemas/` root stubs | Replace | One canonical package location; generated copies only if needed |
| `docs/IMPLEMENTATION_LOG.md` | Archive | Historical log, link from archive index |
| `.qecgraph/`, `.codegraph/` | Clean/ignore | Add to `.gitignore`; do not commit |

---

## 5. Readability and maintainability

### 5.1 Metrics

| Metric | Value |
|---|---|
| Python source | 8,596 lines in 37 modules |
| Test code | 3,611 lines in 24 files, 158 tests (final HEAD) |
| CLI subcommands | 45 registered, 42 visible in the command list |
| Longest function | `cli.main` — **441 lines** (`qecgraph/cli.py:199`) |
| Next longest | `graph.build_graph` — 316 (`graph.py:68`), `store._ingest_locked` — 176, `workspace._run` — 145, `parser._scan_structure` — 129 |
| Function/class docstring coverage | 31 / 389 = **8%** (module docstrings are good) |
| Comment tokens | 76 across 8.5k lines |
| Fully type-annotated functions | 12 / 364 = **3%** (no type checker configured) |
| Logging | none; all output is `print`/JSON in the CLI |
| Lint/format config | none |
| Test CI | none |

Module docstrings are good: they state the invariant, not just the function. Naming is mostly precise (`unbound_review`, `reviewed_cycles`, `reserved_claim`). The recent commit history uses conventional prefixes and small diffs — a positive maintainability signal.

### 5.2 Three parallel stacks

The repository carries three generations of the same concepts:

```text
Generation 1 (store)      Generation 2 (corpus)        Generation 3 (workspace)
store.py                  registry.py                  workspace.py
  CURRENT.json              registry state               machine/CURRENT.json
  snapshots/<id>            immutable states             archive + receipts + machine release
query.py                  corpus.py                    workspace_query.py
  search/show/deps/...      project + execute            WorkspaceSession (MCP tools)
review.py                 review.py                    semantic.py + research_store.py
  proposals/apply           proposals/apply              drafts + publish + extract-review
ai_tools.py               ai_tools.py                  workspace_query.py
  store/corpus MCP          store/corpus MCP             workspace MCP + resources
```

Concrete duplication:

| Concern | Copies | Evidence |
|---|---|---|
| Read-only query session | `query.py`, `corpus.execute`, `ai_tools.ReadOnlySession`, `workspace_query.WorkspaceSession` | Four search/show/context implementations |
| Search | SQLite FTS5 path, substring path, in-memory canonical scan | `query.search`, `workspace_query._search` |
| Storage pointer + lock + atomic write | `store.py`, `registry.py`, `workspace.py` | Each has its own CURRENT/state/lock conventions |
| Review/publish | `review.py` (proposal/apply), `semantic.py` (draft/review), `research_store.publish_records` | Three audit models |
| Migration | `migrations.py` (legacy records), `workspace_migration.py` (corpus → workspace) | Two migration entry points with different reports |
| MCP tool catalogues | `ai_tools._tool_descriptors`, `workspace_query._tool_descriptors` | Different tool names (`qecgraph_*` vs `qec_*`) |

This is the main maintainability risk. It is also a product risk: users see inconsistent query names and command semantics depending on which generation they touch.

**Direction:** define narrow interfaces and make the newer generation compose the older ones, then deprecate.

```python
# qecgraph/query/base.py
class QuerySession(Protocol):
    scope: dict
    def search(self, query: str, *, kind: str | None, limit: int) -> dict: ...
    def show(self, identifier: str) -> dict: ...
    def context(self, identifier: str, *, depth: int, max_nodes: int) -> dict: ...
    def deps(self, identifier: str, *, depth: int, reverse: bool) -> dict: ...

# Adapters: StoreSession, CorpusSession, WorkspaceSession
```

`WorkspaceSession` should compose a `ReadOnlySession` for graph nodes and add research records; it should not reimplement node search/context.

### 5.3 Monolithic functions and modules

- `cli.main` (441 lines) builds the entire parser, dispatches 45 commands, handles progress, subprocess human rendering, JSON output and exceptions in one function. It is the single biggest readability problem and the source of several UX bugs (§6).
- `graph.build_graph` (316 lines) mixes parsing, identity, relation inference, annotations, catalog import and view projection. It needs a staged pipeline (`build_nodes → infer_relations → attach_annotations → project_views`).
- `workspace._run` (145 lines) mixes inbox scanning, archive, extraction, research proposals, publication, claim cleanup and operational status. Extract phases into named functions/classes.
- `parser.py` (993 lines) is large but cohesive; keep it, add parser unit tests.
- Private cross-module access: `human.py` and `semantic.py` use `WorkspaceSession._materials`, `_visible_by_id` and `_source`; they also reach into `_registry`. Introduce public read methods.

### 5.4 No typing, no logging, no tooling

- 3% of functions are fully annotated; `from __future__ import annotations` is used but no checker enforces it.
- No `logging`; the CLI has no `--verbose`/`--debug`, and MCP request failures print a single generic line (`mcp_server.py:155`).
- No linter/formatter; style is consistent by discipline only.
- No `src/` layout; PyPA notes flat layout can let the source tree shadow the installed package during tests ([PyPA discussion](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)). Moving to `src/qecgraph/` is a reasonable later refactor; it is not urgent relative to the CLI/architecture work.

**Recommendation:** add `ruff` (start with `E,F,W,I`, then `B`, `UP`, `SIM`), `mypy` with a gradual allowlist, and `logging` with `--verbose`/`--debug`, `QECGRAPH_LOG_LEVEL`, and request IDs in MCP errors.

### 5.5 Target module map

```text
qecgraph/
├── cli/                 # parser groups, command handlers, output renderers, errors
│   ├── __init__.py      # main() only (~80 lines)
│   ├── parser.py        # grouped subparsers, aliases, help
│   ├── commands/        # workspace, query, review, lean, software, maintain
│   ├── render.py        # human/table/status/progress
│   └── errors.py        # QecError hierarchy, exit codes, envelope
├── domain/              # records, research, software, research validators
├── storage/             # snapshots, registry, workspace, transactions, assets
├── query/               # protocol + store/corpus/workspace adapters
├── ingest/              # parser, source_package, extraction
├── lean/                # lean build/export/integration
└── human/               # renderer
```

This is a direction, not a big-bang requirement. The highest-value extractions are `cli/errors.py`, `cli/render.py`, `cli/parser.py`, and a shared `storage` core.

---

## 6. Tests: function, depth, and completeness

### 6.1 Inventory and run

- **158 tests** at the final HEAD (`a687005`), 10.2 s, 0 failures, 0 skips (156 at `ff5f7e6`; one runtime symlink skip can occur on platforms without symlink support). A pristine `git archive` of the reviewed snapshot gave 152; the release commit `71c7904` had 116.
- 24 test files, 765 `assert*` calls; median 5 assertions per test; no zero-assertion tests.
- `tools/reproduce.py` genuinely executes the suite plus split/ingest/query/schema/HGP checks; `reproduce_incremental.py` and `reproduce_mcp.py` also execute real subprocess checks.
- **The CLI process boundary is mostly untested.** Only about eight command paths are exercised via subprocess (`split`, `watch`, `ingest`, `validate`, `query-tool`, `serve-mcp`, `mcp-config`, `mcp serve`). Commands such as `human-build`, `asset-add`, `extract-*`, `workspace-migrate`, `software-*`, `research-import`, `review-list`, `lean-*`, `recover-store`, `validate-staged`, `audit-dependencies`, `apply`, `review-decide`, `check-css`, `check-experiment`, `codes`, `migrate` and `register` have no CLI-level test.
- **No coverage tool is installed** (`coverage` and `pytest` are absent); the coverage figures in §6.3 are a stdlib `trace` proxy, not branch coverage.
- **No archived current test log.** `validation/rfc002/REPORT.md` asserts 116 tests but points to gitignored `build/` output; there is no checked-in `results.json` or unit-test log for 0.4.0.

### 6.2 Test file map and verdicts

| Test file | Module(s) | # | Verdict | Main gap |
|---|---|---:|---|---|
| `test_pipeline.py` | parser, store, graph, query (E2E) | 21 | strong | parser only indirect; no parser unit/fuzz tests |
| `test_source_package.py` | source_package | 9 | strong | input-byte/depth/encrypted-ZIP branches untested |
| `test_workspace.py` | workspace, cli | 16 | strong | uses `_claim`/`_archive`; CLI tested in-process only |
| `test_splitter.py` | splitter, parser, cli | 10 | strong | one symlink skip; no split-on-existing-store guard test |
| `test_workspace_query.py` | workspace_query, mcp_server | 10 | strong | imports helpers from `test_mcp`; no CLI path |
| `test_ai_tools.py` | ai_tools, query | 8 | strong | — |
| `test_corpus.py` | corpus, registry | 8 | strong | calls private `_publish`; no concurrent writer |
| `test_incremental.py` | store incremental | 7 | strong | does not test `incremental.py` cache API directly |
| `test_apply.py` | review.apply | 6 | adequate | white-box revision rewrite; crash injection mocked |
| `test_review.py` | review | 5 | strong | — |
| `test_status.py` | status | 5 | strong | — |
| `test_mcp.py` | mcp_server | 5 | strong | no concurrent clients/cancel |
| `test_workspace_migration.py` | workspace_migration | **1** | **shallow** | only empty-record happy path |
| `test_human.py` | human | 3 | adequate | no golden markdown/link fixtures |
| `test_lean_export.py` / `test_lean_integration.py` | lean | 3 + 3 | adequate | checked-in artifacts only; no live build |
| `test_semantic.py` | semantic | 3 | adequate | provider-validation branches untested |
| `test_migrations.py` / `test_registry.py` / `test_validators.py` / `test_research.py` | various | 3–6 | adequate | some assertRaises-only; research validators largely unexecuted |
| `test_publication.py` | store, transactions | 4 | strong | no simultaneous writers/SIGKILL |
| `test_watch.py` | watch | 4 | strong | run loop only via subprocess |

**No dedicated tests:** `cli.py` (no `test_cli.py`), `parser.py` (only through integration), `extraction.py` (only through workspace sync), `incremental.py` internals, `source_coordinates.py` (indirect, 100% proxy).

### 6.3 Coverage proxy

A stdlib `trace` run (not coverage.py; in-process only; no branch coverage) gives **81.8%** of 7,470 executable lines. Lowest modules:

| Module | Proxy | Why it matters |
|---|---:|---|
| `lean.py` | **24.2%** | Build/export/axiom paths unexecuted without a live Lean toolchain |
| `validators/research.py` | **49.3%** | Check-weight/depth/recipe/CI validation branches untested |
| `cli.py` | 61.5%* | 33+ subparsers; most command paths not invoked in tests |
| `watch.py` | 64.3%* | Polling loop mostly subprocess-only |
| `software.py` | 73.6% | Refresh/error paths mocked |
| `workspace_migration.py` | 77.6% | Only happy path |
| `semantic.py` | 78.9% | Provider validation branches |

\* understated because subprocess-executed lines are not traced.

### 6.4 What is genuinely well tested

- **Archive hardening**: traversal/Windows paths, symlinks, case collisions, ZIP64, forged counts, CRC, split gzip members, pre-decode size limits.
- **Provenance semantics**: byte-exact Unicode/CRLF spans, duplicate labels → ambiguity, `proof_of` vs candidate, `\leanok` not verification, stale review binding, sidecar-only code entities.
- **Workspace lifecycle**: partial batches, interrupted init retry, entrypoint reselection, damaged snapshot detection, same-version conflict, extraction reuse, lock/crash recovery.
- **MCP/AI contract**: lifecycle, version negotiation, strict JSON framing, byte limits, rate limits, session pinning, manifest tamper, unbound WAL, budgets, CLI/Python parity.
- **Review/apply integrity**: hash/revision binding, stale proposals, cross-corpus decisions, changed assets, atomic batch.
- **QEC math**: real `[[13,1,3]]` matrices, exhaustive distance, GF(2) rank caveat, upper bounds never satisfying lower bounds.

### 6.5 Concrete test plan

Add these files and gates:

**`tests/test_cli.py`** — use `subprocess.run([sys.executable, "-m", "qecgraph", ...])` in a temp workspace.

| Case | Assertion |
|---|---|
| `--version` | exit 0, matches `importlib.metadata.version("qec-graph")` |
| `--help` for every command | exit 0, contains description + example |
| bare `qecgraph` | concise help, exit 64 (or documented code) |
| unknown command | suggestion + exit 64, no traceback |
| `review {}` | human error with missing keys, exit 1/64, **no** Python `TypeError` |
| bad TOML | message includes path and line |
| corrupt `CURRENT` | message names the file and suggests `doctor` |
| `status --workspace .` vs `status` from root | identical output mode and fields |
| `sync` with a bad archive | exit 2, failed package retained, `inputs quarantine` works |
| `split` on annotated store | refusal unless `--force` |
| `NO_COLOR=1` | no ANSI escapes |
| `--json` on all JSON commands | parses; error envelope schema validates |

**`tests/test_human_render.py`** — golden markdown:
- front matter and `aliases` present;
- links use readable labels, not 64-hex filenames;
- blank lines between blocks;
- no unescaped raw JSON in the main body;
- notes canary unchanged;
- tombstone page retained after entity removal.

**`tests/test_schemas.py`**:
- every `examples/*.json` validates against the published schema;
- root `schemas/` copies hash-match packaged schemas;
- `research.v1` validates all 26 kinds with per-kind required fields;
- legacy `record.v3` examples still validate.

**`tests/test_docs.py`**:
- extract backticked `qec-graph ...` commands from user docs and assert the subcommand exists;
- check relative links (or run `lychee` in CI);
- assert the README embedded in the wheel equals `README.md` (release job).

**Extend existing tests**:
- `test_source_package.py`: `input_bytes`, `depth`, encrypted ZIP, unsupported compression, non-UTF8 standalone;
- `test_workspace_migration.py`: records with untyped distance, negative idle, ambiguous software, missing depth;
- `test_workspace.py`: quarantine lifecycle, repeated failure, split guard, `--workspace` output parity;
- `test_publication.py`: two real processes racing, SIGKILL between pointer write and claim cleanup;
- `test_qec_validation.py`: CLI `check-css`/`check-experiment`;
- `test_research.py`: all `validators/research.py` branches (invalid histograms, depth units, recipe fields, CI).

**Coverage gate:** add `coverage.py` config with `branch = true`, `fail_under = 70` initially, raise to 80 after the CLI tests; report per-module and do not count `tests/`.

**CI matrix:** Ubuntu + macOS, Python 3.11/3.13; run `unittest`, `reproduce.py`, `ruff check`, `mypy`, `coverage`, `python -m build`, `twine check`; run the standalone release workflow only on tags.

---

## 7. Error handling and workflow completeness

### 7.1 Real transcripts (evidence)

| Invocation | Actual behavior | Problem |
|---|---|---|
| `qecgraph --version` | prints full usage, exit 2 | No version flag; `--version` treated as missing command |
| `qecgraph` | full 609-byte usage, exit 2 | Should print concise help with examples; exit code should match policy |
| `qecgraph review empty.json --corpus . --actor-id me` | `{"error": "create_proposal() missing 1 required positional argument: 'changes'"}` | Leaks a Python signature; should validate the JSON contract |
| `qecgraph human-build --release deadbeef` | `{"status": "superseded", ...}` exit 2 | A nonexistent release is not "superseded"; no hint |
| bad `qecgraph.toml` | `status: ERROR: Invalid value (at line 1, column 11)` | No file path, no context, raw TOML parser text |
| corrupt `machine/CURRENT.json` | `validate: ERROR: Not a corpus registry pointer` | Internal jargon; no path or remediation |
| `qecgraph research-import bad.json` | `{"error": "Research import expects a list of records"}` | Bare JSON, no field path or command context |
| `qecgraph check-css --hx nope.json` | `{"error": "[Errno 2] No such file or directory: 'nope.json'"}` | Raw OS error as the user-facing message |
| `qecgraph status` with a bad archive | `[................] status: ERROR: 1/2 packages indexed; b3b879951f86: Unsafe archive path: '._.'` | Correct detection, but no next action; bad input stays in the retry loop |
| `qecgraph status --json` on the same workspace | exit **0**, `"status": "ok"` | The machine mode contradicts the human mode; monitoring is broken |
| `qecgraph review list --corpus machine` | parses as `review` (create), fails "--actor-id required" | Same text means two different commands depending on `--corpus` |
| `qecgraph check-experiment {}` | `{"error": "'record'"}` | A bare `KeyError` string |
| `qecgraph asset-add <directory>` | `{"error": "[Errno 21] Is a directory: 3"}` | Raw errno and an opaque number |
| `qecgraph review-decide deadbeef ...` | ENOENT on `proposals/<sha256>.json` | Internal path leaks; no "proposal not found" plus hint |
| `qecgraph search --json ...` | `error: unrecognized arguments: --json`, exit 2 | `--json` is not a global mode |
| `qecgraph deps --help` | Works, but `deps`/`impact`/`context` are missing from the top-level help list | Three commands are effectively hidden |
| `query-tool` with invalid filter | generic `QUERY_ERROR: Machine release could not be read` | Misleading; the input was invalid, the release was fine |
| `Ctrl-C` | uncaught `KeyboardInterrupt` (traceback unless progress path) | Should print `Aborted.` and exit 130 |

### 7.2 Error design problems

1. **No error taxonomy.** Almost everything raises `ValueError`; the CLI catches `(OSError, ValueError, KeyError, TypeError, sqlite3.Error)` (`cli.py:628`) and prints the first line. This masks programming errors as user errors.
2. **No stable error envelope.** There are three incompatible shapes: argparse usage text with exit 2; `{"error": "<string>"}` on stderr with exit 1 (`cli.py:628-632`); and `query-tool`'s `{"ok": false, "error": {"code", "message", "details", "scope"}}` on stdout (`ai_tools.py:227-233`). None carries `hint`, `command`, `release` or a schema version.
3. **Exit code collision.** `2` means both "partial batch/unresolved" and argparse usage error. `docs/rfc-002/QEC_GRAPH_DESIGN_UPDATE.md:1218` acknowledges that automation should not rely on exit codes — that is a design smell, not a solution.
4. **Status contradicts itself.** `status` and `status --json` disagree on both exit code and status string (see §7.1). The cause is that the summary path derives `code=2` while `Workspace.status()` always returns `"status": "ok"`, and `--json` bypasses the summary (`cli.py:388-423`, `workspace.py:501-507`).
5. **Generic catch in workspace query.** `workspace_query.invoke` catches `(OSError, ValueError, TypeError, KeyError)` and returns `QUERY_ERROR: Machine release could not be read` (`workspace_query.py:532-534`), hiding invalid-argument errors.
6. **Raw OS/TOML errors.** Missing files, invalid TOML and corrupt pointers are reported as implementation strings.
7. **No `--debug`.** There is no way to see a traceback or request ID when reporting a bug.
8. **No remediation.** Errors rarely say what to run next.
9. **Help hides commands.** `deps`, `impact` and `context` are added in a loop without `help=` (`cli.py:374-380`); argparse lists them in the usage choices but not in the command list.

### 7.3 Proposed error contract

```python
# qecgraph/cli/errors.py
EXIT_OK = 0
EXIT_FATAL = 1
EXIT_PARTIAL = 2          # keep the documented meaning
EXIT_NOT_FOUND = 4
EXIT_CONFLICT = 5
EXIT_USAGE = 64           # sysexits.h EX_USAGE
EXIT_INTERRUPTED = 130

class QecError(Exception):
    code = "QEC_ERROR"
    exit_code = EXIT_FATAL
    def __init__(self, message, *, hint=None, details=None):
        super().__init__(message)
        self.hint = hint
        self.details = details or {}

class UsageError(QecError):     code, exit_code = "USAGE", EXIT_USAGE
class NotFoundError(QecError):  code, exit_code = "NOT_FOUND", EXIT_NOT_FOUND
class ConflictError(QecError):  code, exit_code = "CONFLICT", EXIT_CONFLICT
class PartialBatch(QecError):   code, exit_code = "PARTIAL_BATCH", EXIT_PARTIAL
```

```python
# cli.py — at the boundary
except QecError as exc:
    payload = {"error": {"code": exc.code, "message": str(exc),
                         "hint": exc.hint, "details": exc.details,
                         "command": args.command}}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False), file=sys.stdout)
    else:
        print(f"error: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"  hint: {exc.hint}", file=sys.stderr)
    return exc.exit_code
except KeyboardInterrupt:
    print("Aborted.", file=sys.stderr)
    return EXIT_INTERRUPTED
except Exception:
    if args.debug:
        raise
    print("error: internal failure (rerun with --debug)", file=sys.stderr)
    return EXIT_FATAL
```

Argparse override:

```python
class QecArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message, hint=f"Run '{self.prog} --help' for usage.")
```

Then map `FileNotFoundError` → `NotFoundError("input not found: <path>", hint="check the path or run `qec-graph status`")`, `tomllib.TOMLDecodeError` → `ConfigError(f"invalid config {path}: {msg}")`, corrupt pointer → `StoreError` with the path and `qec-graph doctor` hint.

**Error message rubric** (NN/g: visible, human-readable, constructive, preserve user effort):

- say what failed, where, and what to do next;
- use the user's terms, not internal class names;
- include the exact path/ID and the release;
- never blame the user;
- keep the original input untouched;
- offer a command or a doc link.

Before/after:

```text
# before
{"error": "[Errno 2] No such file or directory: 'nope.json'"}

# after
error: input not found: nope.json
  hint: pass a matrix file produced by `qec-graph asset-add` or check the path.
```

```text
# before
[................] status: ERROR: 1/2 packages indexed; b3b879951f86: Unsafe archive path: '._.'

# after
1 of 2 packages indexed.
  failed  paper.tar.gz (b3b87995…): archive contains macOS metadata entries ('._.')
  hint:    repack with `COPYFILE_DISABLE=1 tar -czf paper.tar.gz ...`, then
           `qec-graph inputs quarantine paper.tar.gz` to move the bad file aside.
```

### 7.4 Workflow completeness gaps

| Gap | Evidence | User impact | Fix |
|---|---|---|---|
| **Poisoned input forever** | A bad package is restored to `inputs/` on failure and retried on every `sync`; `status` exits 2 until it is manually moved | CI/monitoring never goes green; user cannot "dismiss" a bad file without shell surgery | `qec-graph inputs list`, `inputs quarantine NAME` (move to `inputs/.quarantine/`, keep receipt), `inputs restore NAME`; status shows `quarantined` |
| **`split` clobbers CURRENT** | Running `split` on an annotated store silently repoints `CURRENT.json` to a source-only snapshot (verified) | Annotated/derived data disappears from default queries | Refuse if CURRENT has annotations/catalog; require `--force`; print old/new snapshot |
| **Output mode depends on `--workspace`** | `status` from cwd prints a one-line summary; `status --workspace .` prints full JSON (`cli.py:388`) | Scripts and humans get different formats for the same command | `--json` is the only switch; TTY only controls styling |
| **Human and JSON status disagree** | Partial workspace: `status` exits 2 with an error; `status --json` exits 0 and says `"status": "ok"` | Monitoring and humans see opposite results | One status derivation shared by both renderers; exit code from the same result |
| **Hidden commands** | `deps`, `impact`, `context` are absent from the top-level command list (`cli.py:374-380`) | Users cannot discover three core queries | Give every parser a `help=` string; add a test that `--help` lists every registered command |
| **No workspace query CLI** | `search --workspace .` is rejected by argparse; only `query-tool` or MCP works | The primary product cannot be queried from its own CLI | Add `--workspace/--machine/--release` to `search/show/context/deps/impact`; reuse `WorkspaceSession` |
| **No `--version`/`doctor`/`inputs`/`snapshot list`** | Confirmed | Basic operations require reading internals | Add all four |
| **Alias semantics differ** | `review list --corpus` is the legacy review; `review list` without `--corpus` is the workspace proposal list (`cli.py:207`) | Same command means different things | Make `review list` require an explicit scope, or split into `query`/`workspace` namespaces |
| **Stale release artifacts** | Wheel README says 0.3.0; no license | Users get wrong docs/metadata | Clean rebuild + release gate |
| **No `--quiet`, `--verbose`, `--debug`, `--color`** | Confirmed | Poor scripting/debugging/accessibility | Add |
| **No shell completion** | Confirmed | Discoverability | Optional, later |

### 7.5 Suggested `doctor` output

```text
$ qec-graph doctor
QEC Graph 0.4.0rc1
  workspace   /Users/me/qec            ok
  config      qecgraph.toml             ok (source hashes: 1)
  pointer     machine/CURRENT.json     ok (release dfbed7e)
  archive     1 blob, 1 receipt        ok
  inbox       0 pending, 0 quarantined ok
  human       current, 9 pages         ok
  notes       isolation                ok (not read)
  tools       python 3.15.2, sqlite 3.x ok
next: qec-graph search HGP
```

---

## 8. CLI design and human-facing aesthetics

### 8.1 Current surface

- **45 registered subcommands**, only **42 visible** in the command list; `deps`, `impact`, `context` are hidden. No grouping, no ordering by frequency, no `help` command.
- **12 of 138 static `add_argument` calls carry `help=`; 0 of 37 `add_parser` calls have `description=` or `epilog=`; 22 `default=` sites are never shown in help.** Examples: `--workspace`, `--corpus`, `--registry-revision`, `--hx`, `--hz`, `--limit`, `--n-min` are all bare.
- **No examples** in help; no docs URL; no `--version`; no `--quiet`/`--color`; no `help <topic>`.
- **Duplicated help strings**: the three `software-*` commands all say "Manage the bounded software directory"; the four workspace commands share `f'{action.capitalize()} a managed QEC workspace'`, producing "Status a managed...".
- **Top-level usage wraps** over ten lines; the usage choice line is **524 characters** and every unknown-subcommand error repeats a 506-character choice list.
- **`--json` is not a global mode**: only workspace commands and `validate` accept it; `search --json` fails; non-TTY `init`/`rebuild` print pretty JSON without the flag; `validate --json --store` accepts and ignores it.
- **Entry-point help is wrong**: `qec-latex-split --help` prints `usage: qecgraph split`; `qecgraph-mcp --help` prints `usage: qecgraph serve-mcp` (the program name is hard-coded at `cli.py:209`). The four `qecgraph` spellings otherwise produce byte-identical help, which is good.

Help quality, sampled (1 = bare usage, 5 = description + examples + defaults):

| Command group | Examples | Quality |
|---|---|---|
| `ingest`, `split` | descriptions explain the shared pipeline | 3/5 |
| `init`, `sync`, `rebuild`, `validate` | terse; no examples/defaults | 2/5 |
| `status`, `show`, `codes`, `check-experiment`, `asset-add`, `human-build`, `software-*` | almost entirely bare flags | 1/5 |
| `deps`, `impact`, `context` | hidden from the command list | 1/5 |
| `query-tool`, `mcp-config`, `serve-mcp`, `lean-*`, `review-*` | functional but undescribed | 2/5 |

- **Naming inconsistency**: `serve-mcp` vs `mcp serve`; `human-build` vs `human build`; `qecgraph` vs `qec-graph`; `review-list` vs `review list`; store/corpus/workspace are all "scopes" but use different flags (`--store`, `--corpus`, `--workspace`, `--machine`).
- **Aliases are implemented by mutating `argv`** (`cli.py:201-207`), not by argparse aliases; help never shows the nested form, and `--help` displays `serve-mcp` even when the user typed `mcp serve`.
- **Output**:
  - success is `[################] sync: OK (1/2 packages indexed)` — a 16-character bar with no percentage, meaningless in non-TTY logs;
  - failure writes `[................] status: ERROR: ...` to stderr and nothing to stdout;
  - `init`/`rebuild` print full JSON in non-TTY but a progress line in a TTY, while `sync`/`status`/`validate` print the concise line in both — inconsistent;
  - no summary of workspace path, release, pending inputs, vault state or next action.
- **Color/Unicode**: good `NO_COLOR` handling and encoding fallback; no `FORCE_COLOR`, no `--color`, no color-blind alternative for status (symbols are present, which helps).

What already works:

- all four `qecgraph` spellings share one main and one help text;
- `mcp serve` actually starts and exits 0 on EOF;
- `query-tool` already has the right structured `{ok, data | error: {code, message, details, scope}}` envelope — the rest of the CLI should adopt it;
- `NO_COLOR` is honored, `TERM=dumb` disables live progress, non-UTF-8 stderr falls back to ASCII, and status symbols are paired with words rather than color alone;
- cross-scope errors are precise ("`--snapshot` belongs to store queries; use `--registry-revision` for a corpus");
- argparse sends errors to stderr and no traceback appeared on tested paths.

### 8.2 Proposed information architecture

Two-level noun-verb, with flat aliases for compatibility:
```text
qec-graph workspace init | sync | rebuild | status | validate | migrate
qec-graph query     search | show | deps | impact | context | codes | performance | software
qec-graph review    list | show | decide | apply | import
qec-graph lean      build | import | status
qec-graph mcp       serve | config
qec-graph software  import-seed | coverage | refresh
qec-graph maintain  watch | recover | validate-staged | audit-dependencies
qec-graph split | ingest | doctor | version | inputs
```

- Keep every old name as a **hidden alias** for one minor release, with a deprecation warning on stderr: `warning: 'serve-mcp' is deprecated; use 'mcp serve'`.
- Use argparse `aliases=` for flat aliases and nested subparsers for `mcp`/`human`/`software`/`review`.
- Add `help` topics: `qec-graph help workspace`, `qec-graph help errors`, `qec-graph help json`.
- Add `--version`, global `--json`, `--quiet`, `--debug`, `--color {auto,always,never}`.

### 8.3 Help design

Lead with examples and common commands (clig.dev: concise help by default, examples first, consistent flags, support path). Example:

```text
qec-graph 0.4.0rc1 — provenance-preserving QEC knowledge workspace

Usage: qec-graph <command> [options]
       qec-graph help <command>

Common commands
  init       create a workspace (idempotent)
  sync       import new packages from inputs/
  status     show release, package, and vault state
  validate   check hashes, spans, references, and SQLite
  search     search sources and research records
  mcp serve  start the read-only MCP server

Manage
  workspace  init · sync · rebuild · status · validate
  query      search · show · deps · impact · context
  review     list · show · decide · apply
  lean       build · import · status
  software   import-seed · coverage · refresh
  maintain   watch · recover · audit · validate-staged

Examples
  qec-graph init --workspace ~/qec
  qec-graph sync --dry-run
  qec-graph search HGP --workspace ~/qec
  qec-graph mcp-config --workspace ~/qec

Docs: https://github.com/Guangqi-Phys/qec-graph/tree/main/docs
Issues: https://github.com/Guangqi-Phys/qec-graph/issues
Exit codes: 0 ok · 2 partial · 4 not found · 5 conflict · 64 usage · 130 interrupted
```

Subcommand help should include 1–3 examples, defaults, the precise output envelope, and a "see also" link.

### 8.4 Proposed status/sync output

```text
$ qec-graph status
QEC Graph  /Users/me/qec
Release    dfbed7e · 2026-11-09 18:42
Sources    1 indexed · 0 pending · 0 failed · 0 quarantined
Vault      current · 9 pages (2 records, 3 sources)
Next       qec-graph search HGP
```

```text
$ qec-graph sync
Syncing 2 packages…
  ✓ paper.tar.gz        1.2 MB   indexed
  ✗ broken.zip          4 KB     unsupported archive (kept for retry)
Published dfbed7e · 1 indexed · 1 failed
Run `qec-graph status` for details, or `qec-graph inputs quarantine broken.zip`.
```

Rules:

- TTY: color, symbols, spinner, elapsed time; non-TTY: plain lines, no bars, no ANSI.
- Summary always includes: workspace path, release, counts, vault status, next action.
- Errors: summary + one actionable line per failure; full details via `status --json`.
- `--quiet`: only exit code (or one line).
- `--json`: stable envelope with `status`, `run_id`, `release_id`, `counts`, `inputs`, `human`, `warnings`, `next`.

### 8.5 Obsidian vault aesthetics

Current generated pages are functional but unfriendly:

- links render as `[[generated/records/theorem--41dc81e3...64 hex]]`, so the reader sees a hash;
- body is a LaTeX fence immediately followed by a raw JSON fence, with no blank line;
- no front matter beyond `source_release`, no tags/aliases, no backlink context;
- category index lists long hash links; archived entities repeat "Archived entity";
- no "status legend", no MOC, no source page outline.

Proposed page:

````markdown
---
title: "Commutation of the block construction"
aliases: ["thm:hgp-css"]
tags: [qec/theorem, qec/status/extracted, qec/release/0bbc8478]
kind: theorem
source: "sections/hgp.tex:9–20"
release: "0bbc847806b29c1785dde9e8a769da0db1d407ef5cfcd0053e57bce84db22aa5"
---

# Commutation of the block construction

| Field | Value |
|---|---|
| Kind | theorem |
| Review | extracted |
| Verification | not_verified |
| Source | `sections/hgp.tex:9–20` |
| Revision | `6b10f7ab…` |

## Statement

```latex
\begin{thm}[Commutation of the block construction]
...
\end{thm}
```

## Relations

- Uses → [[generated/records/definition--c8c92893…|Binary CSS presentation]] (declared)
- Proof → [[generated/records/proof--…|Proof of Theorem 2.1]]

## Evidence

Field evidence is bound to the source span above; see the raw record.

<details>
<summary>Raw JSON</summary>
...
</details>
````

Also:

- readable stable filename: `theorem--thm-hgp-css--41dc81e3.md` (slug + 8–12 hex; collision check; keep tombstones for old paths);
- front matter tags for Obsidian graph filtering;
- `human/README.md` and `human/generated/Status.md` explaining generated vs notes and the status legend;
- category index grouped by kind with counts and one-line descriptions;
- a "recent changes" page for the current release.

### 8.6 CLI compatibility and migration

- Keep all existing command names working through 0.4.x; add nested forms as the documented path.
- Emit deprecation warnings only when stderr is a TTY or `QECGRAPH_DEPRECATIONS=1`.
- Document the exit-code change (usage errors move from 2 to 64) in `CHANGELOG.md` and the migration guide; this is the only user-visible breaking change in the proposal.
- Version the JSON envelopes (`envelope_version: 1`) and keep field names stable.

---

## 9. Prioritized remediation plan

### P0 — this week (release blockers and quick wins)

| # | Task | Files | Acceptance |
|---|---|---|---|
| 1 | Add `LICENSE` (MIT) and full `pyproject` metadata | `LICENSE`, `pyproject.toml` | `twine check` passes; wheel METADATA has `License-Expression` and license file |
| 2 | Add CI: tests, lint, types, coverage, build | `.github/workflows/ci.yml` | PR fails on test/lint/build failure |
| 3 | Fix output mode and status semantics: `--json` only, TTY only styling, one status derivation | `cli.py:388-423`, `workspace.py:501-507` | `status` and `status --workspace` identical; `status` and `status --json` agree on exit code and status; test |
| 4 | Add `--version`, `help <topic>`, concise no-arg help; list all 45 commands; exit 64 for usage | `cli.py` | tests for all three |
| 5 | Replace raw exceptions in `review`/`claim-link`/`check-experiment` with contract validation | `cli.py:566`, `review.py` | friendly error; no `TypeError` |
| 6 | Guard `split` against annotated CURRENT | `splitter.py`, `store.py` | refusal + `--force`; test |
| 7 | Add `inputs list|quarantine|restore` | `workspace.py`, `cli.py` | bad package leaves retry loop; bytes preserved; status shows quarantined |
| 8 | Rebuild wheel/sdist from clean tag; verify README/version/license | build scripts | wheel README equals source; metadata correct |
| 9 | Add `.qecgraph/`, `.codegraph/`, caches to `.gitignore` | `.gitignore` | `git status` clean in a fresh workspace |
| 10 | Add docs index + banners for stale docs; fix 6 factual contradictions | `docs/README.md`, banners | link check; no "0.3.0" in current docs |

### P1 — next 2–3 weeks

| # | Task | Files | Acceptance |
|---|---|---|---|
| 11 | Extract `cli/errors.py`, `cli/render.py`, `cli/parser.py`; `main` < 120 lines | `qecgraph/cli/` | behavior unchanged; `test_cli.py` |
| 12 | Introduce `QecError` taxonomy + JSON error envelope + exit table | `cli/errors.py` | all commands use it; docs updated |
| 13 | Grouped help with examples and deprecation aliases | `cli/parser.py` | all commands have examples; old names warn |
| 14 | Add `--workspace` to query commands; reuse `WorkspaceSession` | `cli.py`, `workspace_query.py` | `search/show/context/deps` work on workspace; parity test with MCP |
| 15 | Add `doctor`, `version`, `snapshot list` | `cli/commands/maintain.py` | smoke tests |
| 16 | Single-source schemas; add graph/annotations to package; full `research.v1` | `qecgraph/validators/schemas`, `schemas/` | hash-match test; examples validate |
| 17 | Move duplicate seed/fixture out of docs | `tests/fixtures`, `software.py` | tests load packaged seed; docs link fixture |
| 18 | Docs restructure to user/design/operations/archive | `docs/` | index, links, language policy |
| 19 | Add CLI/human/schema/docs tests and coverage gate | `tests/` | `test_cli.py` etc.; coverage ≥ 70% |
| 20 | Add `ruff`, `mypy`, `pre-commit`, `coverage` config | `pyproject.toml`, `.pre-commit-config.yaml` | CI gates green |
| 21 | Dedupe/prune `validation/`; add `validation/README.md` and archive current 0.4 test log/results | `validation/` | ≤ 100 unique files; stage/commit/command/result table; current acceptance backed by checked-in evidence |

### P2 — 1–2 months

| # | Task | Files | Acceptance |
|---|---|---|---|
| 22 | Consolidate storage pointer/lock/atomic code behind a common core | `storage/` | three engines share tests; no behavior change |
| 23 | Consolidate query behind `QuerySession` adapters | `query/` | one search/context implementation; parity tests |
| 24 | Split `build_graph` into stages; add parser unit tests | `graph.py`, `parser.py` | functions < 100 lines; coverage up |
| 25 | Human renderer v2: front matter, aliases, readable names, tables, tags | `human.py` | golden tests; screenshots |
| 26 | Release automation: tag → build → verify → GitHub Release → PyPI (manual gate) | `.github/workflows/` | reproducible clean build; README check |
| 27 | Linux/Docker CI verification; run the isolation profile | `compose.mcp-isolated.yaml`, CI | Linux install + MCP smoke |
| 28 | Golden corpus: 5–10 real papers with expected fields | `tests/golden/` | stable, licensed, documented |
| 29 | Performance benchmarks (no unverified claims) | `tools/bench.py` | reproducible report |
| 30 | `src/` layout (optional) and single-source version | `pyproject.toml`, tree | clean editable + wheel test |

### Definition of done for the cleanup

- `pip install .`, `qec-graph --version`, `init`, `sync`, `status`, `validate`, `search`, `mcp serve` all work from a clean venv.
- Every command has help, an example, a documented exit code, and a JSON mode.
- No user-facing error is a raw Python/OS/TOML string.
- Every published schema is packaged and tested; no duplicate seed/fixture.
- CI runs the suite, lint, types, coverage, and build on Linux and macOS.
- The wheel's README/version/license match the source tag.
- A new reader can go from README → docs index → workspace guide without encountering a stale claim.

---

## 10. What to keep

The cleanup should preserve, not "simplify away":

- the source-coordinate contract (UTF-8 bytes, Unicode half-open codepoints, 1-based lines);
- the evidence-state distinctions (`candidate`, `declared`, `reviewed`, `stale`, `unbound_review`, `unresolved`);
- immutable snapshots, content hashes, receipts and the single-writer/atomic publication protocol;
- the archive threat model and the strict machine/human isolation;
- the honest validation reporting (executed vs not executed, limits, non-claims);
- the ADRs and the CodeGraph attribution record;
- the `knowledge_starter` fixture as **legacy evidence**, not as the current schema.

---

## Appendix A — Verification log

| Command | Result |
|---|---|
| `git rev-parse --short HEAD` | `8a8c858` at start; `a687005` at end |
| `.venv/bin/python -m unittest discover -s tests` | 153 OK at start; 158 OK at end (`a687005`); ~11 s; pristine snapshot 152; release commit 116 |
| `.venv/bin/python tools/reproduce.py --out build/review-reproduce` | exit 0 |
| `qecgraph --help` / `--version` / no args | 45 registered, 42 visible; no version; exit 2 with full usage |
| `qecgraph status` on partial workspace | exit 2, error on stderr, empty stdout |
| `qecgraph status --json` on the same workspace | exit 0, `"status": "ok"` — contradictory |
| `qecgraph status` (cwd) vs `status --workspace .` | concise vs full JSON — inconsistent |
| `qecgraph review list --corpus machine` | parsed as `review`, fails `--actor-id` |
| `qecgraph review {} --corpus … --actor-id me` | Python `TypeError` leaked |
| `qecgraph human-build --release deadbeef` | `superseded`, exit 2 |
| `qecgraph split` after `ingest --annotations` | CURRENT repointed to source-only snapshot, no warning |
| bad tar containing `._.` | rejected as `unsafe_archive`; restored to inbox; every sync exits 2 |
| wheel `build/rfc002-release/...whl` | METADATA README says 0.3.0; no license |
| relative markdown links | 200 checked, 0 broken |
| schema files | 15; 4 root stubs; graph/annotations absent from wheel |
| `validation/` | 574 files, 174 unique non-empty contents, 171 zero-byte, 2.58 MB exact duplicates |

## Appendix B — External references

- [Command Line Interface Guidelines (clig.dev)](https://clig.dev/) — human-first design, concise help, examples, exit codes, stderr/stdout, progress, subcommand consistency.
- [Diátaxis](https://diataxis.fr/start-here/) — separate tutorials, how-to, reference and explanation; most documentation problems are boundary problems.
- [PyPA: src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) — source shadowing and packaging benefits.
- [PyPA: Writing your pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) — PEP 639 license/license-files, authors, URLs, classifiers.
- [Nielsen Norman Group: Error-Message Guidelines](https://www.nngroup.com/articles/error-message-guidelines/) — visibility, human language, constructive advice, no blame.
- [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) — changelog structure and deprecation policy.
- [Semantic Versioning 2.0.0](https://semver.org/) — public API and version semantics.
- [Coverage.py](https://coverage.readthedocs.io/en/latest/) — line/branch coverage and CI reporting.
- [Ruff](https://docs.astral.sh/ruff/) — lint/format configuration.
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) — docstrings and naming.
- Repository-local evidence: `validation/rfc002/REPORT.md`, `docs/rfc-002/IMPLEMENTATION.md`, `docs/adr/0001-codegraph-reference.md`.

## Appendix C — Key files for the remediation

| Purpose | File |
|---|---|
| CLI monolith / parser / output | [`qecgraph/cli.py`](../qecgraph/cli.py) |
| Workspace pipeline | [`qecgraph/workspace.py`](../qecgraph/workspace.py) |
| Store snapshot pipeline | [`qecgraph/store.py`](../qecgraph/store.py) |
| Registry/corpus | [`qecgraph/registry.py`](../qecgraph/registry.py), [`qecgraph/corpus.py`](../qecgraph/corpus.py) |
| Research contract | [`qecgraph/research.py`](../qecgraph/research.py), [`qecgraph/validators/research.py`](../qecgraph/validators/research.py) |
| Query layers | [`qecgraph/query.py`](../qecgraph/query.py), [`qecgraph/workspace_query.py`](../qecgraph/workspace_query.py), [`qecgraph/ai_tools.py`](../qecgraph/ai_tools.py) |
| Human renderer | [`qecgraph/human.py`](../qecgraph/human.py) |
| Archive hardening | [`qecgraph/source_package.py`](../qecgraph/source_package.py) |
| Packaging | [`pyproject.toml`](../pyproject.toml), [`MANIFEST.in`](../MANIFEST.in) |
| Docs entry | [`README.md`](../README.md), [`docs/ADVANCED_USAGE.md`](ADVANCED_USAGE.md), [`docs/DATA_AND_SEARCH.md`](DATA_AND_SEARCH.md) |
| Validation evidence | [`validation/rfc002/REPORT.md`](../validation/rfc002/REPORT.md) |

---

## Appendix D — Starter patches

These are intentionally small, reviewable starting points; they are not a complete implementation.

### D.1 Complete `pyproject.toml` metadata

```toml
[build-system]
requires = ["setuptools>=77"]        # PEP 639 requires >= 77
build-backend = "setuptools.build_meta"

[project]
name = "qec-graph"
dynamic = ["version"]                # single source: qecgraph.__version__ via [tool.setuptools.dynamic]
description = "Provenance-preserving LaTeX blocks and typed QEC knowledge graphs"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
license-files = ["LICEN[CS]E*"]
authors = [{name = "Guangqi Phys"}]
keywords = ["quantum error correction", "latex", "knowledge graph", "provenance", "lean"]
classifiers = [
  "Development Status :: 4 - Beta",
  "Intended Audience :: Science/Research",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Scientific/Engineering :: Physics",
]
dependencies = ["pylatexenc==2.10", "jsonschema==4.26.0"]

[project.urls]
Homepage = "https://github.com/Guangqi-Phys/qec-graph"
Documentation = "https://github.com/Guangqi-Phys/qec-graph/tree/main/docs"
Repository = "https://github.com/Guangqi-Phys/qec-graph"
Issues = "https://github.com/Guangqi-Phys/qec-graph/issues"
Changelog = "https://github.com/Guangqi-Phys/qec-graph/blob/main/CHANGELOG.md"

[project.optional-dependencies]
dev = ["coverage[toml]>=7.6", "ruff>=0.9", "mypy>=1.14", "build>=1.2", "twine>=6"]

[tool.setuptools.dynamic]
version = {attr = "qecgraph.__version__"}

[tool.coverage.run]
branch = true
source = ["qecgraph"]

[tool.coverage.report]
fail_under = 70
show_missing = true
skip_covered = true

[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I"]       # add B, UP, SIM incrementally

[tool.mypy]
python_version = "3.11"
files = ["qecgraph"]
check_untyped_defs = true
warn_unused_ignores = true
```

> If you prefer not to bump setuptools, keep the legacy `license = {text = "MIT"}` form; PEP 639 is preferable for new releases.

### D.2 Minimal CI workflow

```yaml
name: CI
on:
  push:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.11", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: python -m pip install -e . coverage ruff mypy build twine
      - run: python -m unittest discover -s tests -v
      - run: python -m coverage run -m unittest discover -s tests
      - run: python -m coverage report --fail-under=70
      - run: ruff check .
      - run: mypy qecgraph/validators qecgraph/research.py   # expand as annotations land
      - run: python tools/reproduce.py --out build/ci-reproduce
      - run: python -m build
      - run: python -m twine check dist/*
```

Add a separate job that asserts the built wheel's README and version match the source:

```yaml
      - run: |
          python - <<'PY'
          import zipfile, pathlib
          wheel = next(pathlib.Path("dist").glob("*.whl"))
          meta = zipfile.ZipFile(wheel).read(
              next(n for n in zipfile.ZipFile(wheel).namelist() if n.endswith("METADATA"))
          ).decode()
          readme = pathlib.Path("README.md").read_text()
          assert readme.strip() in meta, "wheel README is stale"
          assert "0.3.0" not in meta, "wheel metadata still mentions 0.3.0"
          PY
```

### D.3 `.gitignore` additions

```gitignore
/.qecgraph/
/.codegraph/
/htmlcov/
.coverage
.coverage.*
.ruff_cache/
.mypy_cache/
```

### D.4 CLI contract test skeleton

```python
# tests/test_cli.py
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

def run(*args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, "-m", "qecgraph", *args],
        cwd=cwd, env={**os.environ, **(env or {})},
        capture_output=True, text=True, timeout=120,
    )

class CliContractTests(unittest.TestCase):
    def test_version(self):
        from importlib.metadata import version
        result = run("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn(version("qec-graph"), result.stdout)

    def test_help_lists_every_registered_command(self):
        from qecgraph.cli import build_parser  # extract this from main()
        registered = set(build_parser()._subparsers._group_actions[0].choices)
        result = run("--help")
        self.assertEqual(result.returncode, 0)
        for name in registered:
            self.assertIn(name, result.stdout)

    def test_status_human_and_json_agree(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "inputs").mkdir()
            Path(root, "inputs", "paper.tex").write_text(
                r"\documentclass{article}\begin{document}Hi\end{document}")
            self.assertEqual(run("init", "--workspace", root).returncode, 0)
            human = run("status", "--workspace", root)
            machine = run("status", "--workspace", root, "--json")
            self.assertEqual(human.returncode, machine.returncode)
            self.assertEqual(json.loads(machine.stdout)["status"], "ok")

    def test_review_validates_input_contract(self):
        with tempfile.TemporaryDirectory() as root:
            bad = Path(root, "empty.json")
            bad.write_text("{}")
            result = run("review", str(bad), "--corpus", root, "--actor-id", "me")
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("TypeError", result.stderr)
            self.assertIn("changes", result.stderr)

    def test_usage_error_is_64(self):
        self.assertEqual(run("does-not-exist").returncode, 64)
```

### D.5 `docs/README.md` outline

```markdown
# QEC Graph documentation

**Status legend:** Current · Design · Historical · Evidence. Only *Current* pages describe 0.4.x behaviour.

| Start here | Audience | Status |
|---|---|---|
| Install — `user/install.md` | new users | Current |
| Workspace — `user/workspace.md` | daily users | Current |
| Query and MCP — `user/query.md` | users + agents | Current |
| Obsidian vault — `user/obsidian.md` | readers | Current |
| Troubleshooting — `user/troubleshooting.md` | everyone | Current |
| Architecture — `design/architecture.md` | contributors | Design |
| Data model — `design/data-model.md` | contributors | Design |
| Release process — `operations/release.md` | maintainers | Current |
| Historical validation — `archive/validation/README.md` | auditors | Evidence |

Rules: no page may claim a capability without a test or an evidence link; historical pages start with a banner; every CLI command in a page is checked by `tests/test_docs.py`.
```

### D.6 Status renderer outline

```python
# qecgraph/cli/render.py
def render_status(result, *, color=False):
    mark = "✓" if result["status"] == "ok" else "!"
    release = result["release_id"][:8]
    materials = result["materials"]
    ready = sum(m.get("processing_completed") for m in materials)
    failed = [m for m in materials if not m.get("processing_completed")]
    lines = [
        f"Workspace  {result['workspace_id']}",
        f"Release    {release}",
        f"Sources    {ready}/{len(materials)} indexed · "
        f"{result.get('pending_inputs', 0)} pending · {len(failed)} failed",
    ]
    if failed:
        first = failed[0]
        lines.append(f"Failed     {first.get('input', first['archive_sha256'][:12])}: "
                     f"{first.get('reason', first['status'])}")
    if result.get("human"):
        lines.append(f"Vault      {result['human']['status']} · {result['human'].get('generated_pages', 0)} pages")
    lines.append(f"Next       qec-graph search <term>")
    return "\n".join(lines)
```

`status` should return this text without `--json`, and the JSON envelope `{status, materials, pending_inputs, pending_claims, human, next}` with `--json` — both derived from the same result and the same exit code.
