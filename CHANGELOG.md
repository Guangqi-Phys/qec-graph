# Changelog

## Unreleased

- Thoughts filenames now use the first author's surname. Folder year/month
  prefers the arXiv package identifier (`2611.12971v2.tar.gz` → `2026/11/`)
  over manuscript dates. Sync/rebuild snapshots original receipt filenames,
  including on empty sync for older workspaces; rendering remains pinned to
  machine data. Rebuilding removes old full-name/date paths without backups.
- Replaced the human entity-page vault with one ThoughtsGraph note per paper at
  `human/YYYY/MM/Surname_First_Two_thoughts.md`, with the nine questions,
  source-bound AI answers and leading Obsidian `tags`, `link`, `title`, `author`.
  Topic tags and bibliography use source metadata; unknown dates stay unknown.
- The first migration deletes the old managed `human/` tree, including old
  `notes/`, without reading private contents or making backups. Indexes, entity
  pages, manifests and tombstones are no longer generated there. Renderer state
  stays in `.qecgraph/`; interrupted publication and obsolete-note cleanup retry
  safely. Keep personal notes outside `human/`.
- Advanced `extract_thoughts` to skill v3 with Chinese editorial answers and
  optional quoted paper metadata. Offline regressions cover metadata validation,
  proposal-only rendering, filename collisions, migration and recovery.
- Default AI configuration now enables semantic proposal extraction and selects
  OpenRouter with `deepseek/deepseek-v4.1-flash-1017`. API keys remain empty for
  users to supply inline or through the environment. Omitted selection/flag
  fields use these defaults; existing explicit settings are preserved. Init
  remains offline, and local imports still work without an API key.
- Refined `extract_thoughts` as skill v2 with concrete category boundaries,
  evidence-reading steps, condition/attribution rules and a validated JSON
  example. Output fields remain compatible; completed extraction batches keep
  their existing versioned proposals. Documented AI configuration, manual relation
  curation and lack of automatic re-extraction on skill upgrades.
- Added offline fake-provider regressions for the worked example, prompt cache
  separation and rejection of generated or stitched quotations before caching.

## 0.6.2 — 2026-11-11

- Integrated the searchable-knowledge design and retained `Human.md` as the
  original requirements. Added version-bound document outlines, continuous
  section/file reads and source/field coverage, including unparsed source text.
- Added selectable legacy (13 tools), research (7 tools), and generic
  search/fetch (2 tools) MCP profiles on the same pinned machine release.
- Added nine source-quoted research thought categories, typed links, generated
  human pages and the optional `extract_thoughts` v1 AI proposal skill.
- Added optional offline vector projections, BM25/cosine hybrid retrieval,
  explicit OpenAI-compatible embedding configuration, integrity checks and
  reusable model-bound chunk caches. Local vectors are a lexical baseline.
- Added purpose-aware context, typed tracing, evidence-bound code/check-weight
  and idle/loss filters, experiment-condition groups and explicit missing data.
- Added reproducible direct-reading/search/context measurements. Offline and
  registered-source checks do not establish model quality, Lean verification
  or production-scale capacity.
- Expanded the English and Chinese guides with the four graph views,
  ThoughtsGraph categories, evidence rules and query examples.
- Upgrade readers and writers together before sharing releases that contain
  `research_thought` records or retrieval index bindings. Existing CLI names
  and the default legacy MCP profile remain available. Vector indexing stays
  opt-in; enabling `[ai].extract_proposals` now includes thought proposals.

## 0.6.1 — 2026-11-11

- Fixed parsing of percent-encoded URLs in LaTeX links, including the
  `arXiv-2411.10343v2` bibliography failure, while preserving original bytes
  and source coordinates.
- Added parser-first AI structure recovery for eligible failures. Recovery
  plans must cover the original source exactly, remain `proposed`, and pass
  schema, source-mapping and publication checks. Saved plans support offline
  rebuilds.
- Added source-linked reading views for CLI search, workspace MCP queries and
  human previews, with conservative removal of formatting and citations.
- Ordinary packages now use deterministic extraction. AI structure fallback
  defaults to enabled, while semantic proposal extraction requires explicit
  `[ai].extract_proposals = true`. Upgrade readers before sharing snapshots
  that use the new `recovered_proposed` extraction status.
- Hardened normalization mappings, publication recovery, concurrent package
  processing, proposal reviews, citation verification, query evidence and
  provider response/cache validation.
- Fixed standalone packaging of AI skill instructions, prompts and schemas.
  Added offline regressions and installed CLI/workspace acceptance checks.

## 0.6.0 — 2026-11-10

- Release checks now account for prepare-only `init`: the workspace reproduction
  runs `init` followed by `sync`, and an unset AI model is treated as disabled
  rather than an extraction error.
- Rewrote the four AI skills with explicit triggers, inputs, procedures,
  evidence rules, failure policy and checklists; the full `SKILL.md` body is
  now sent to the model.
- Added optional AI provider configuration for OpenAI, Anthropic, OpenRouter
  and Claude Code, with `qecgraph ai status/test/config/proposals`.
- Added explicit, proposal-content-bound AI review decisions under
  `machine/ai/reviews`; they do not automatically become research records.
- `sync` can prefetch AI normalization/extraction for multiple packages with
  `[ai].max_parallel_packages`; publishing and input consumption stay serial.
- `sync` now normalizes ambiguous multi-root TeX packages through a
  source-mapped plan and emits schema-validated theorem, assumption and data
  proposals under `machine/ai/proposals`; the original package stays
  authoritative and AI output is never auto-verified.
- `qec-graph init` now initializes only the current directory unless
  `--workspace` is explicit. It accepts an empty directory or one containing
  only `inputs/`, creates `inputs/` and an AI-ready `qecgraph.toml`, and never
  extracts packages; extraction belongs to `sync`.

## 0.5.1 — 2026-11-10

- Removed the `legacy/knowledge_starter` sample and all dependent matrix tests,
  catalog/qec_kb reproduction steps, MANIFEST entries and documentation.
- Pruned historical validation run artifacts. `validation/` now contains only
  the current check index; old release evidence remains in Git history.
- Moved the Lean fixed-build and zero-axiom fixtures to `tests/fixtures/lean/`.
- Aligned all current documentation with the post-cleanup implementation and
  the 0.5.x status markers.

## 0.5.0 — 2026-11-10

- Removed the `migrate` and `migration-import` commands, `qecgraph.migrations`,
  `Registry.import_migration`, their tests and documentation. No legacy record
  adapter is part of the runtime or CLI. Corpus-to-workspace migration remains a
  separate workspace command.
- The format discriminator field is now `schema` (formerly `schema_version`);
  values are unversioned identifiers such as `qecgraph.research`.
- **Breaking (development stage):** all schema identifiers are unversioned
  (`qecgraph.research`, `qecgraph.record`, `qecgraph.graph`, `qecgraph.annotations`,
  `qecgraph.proposal`, `qecgraph.review`, `qecgraph.lean-export`, filesystem
  formats and tool reports). No `.v1`/`.v2`/`.v3` suffix is written or accepted.
- **Breaking:** the old `record.v2` reader, schema and migration branch are removed;
  only the current record format is read. Old human-view histories and page
  migration are no longer supported.
- Research kinds and fields now use standard QEC terms: `quantum_code`,
  `check_matrix`, `syndrome_measurement_circuit`, `noise_model_instance`,
  `performance_curve`, `performance_data_point`, `distance_estimate`,
  `classical_code`, `metric`, `decoder`, `hardware_model`, `code_type`, and
  `n`/`k`/`r`.
- Distance query rows now expose the claim and evidence `review_status`; proposed
  research records stay visible but are never presented as verified.
- Workspace migration reserves the destination name with an atomic `mkdir` before
  copying, so a directory that appears during the copy cannot be silently replaced.
- Registry and store pointer/state reads now reject symlinked or multiply-linked
  authority files instead of following them; writes already did.
- Successful workspace claims are removed after their commit receipt, and empty
  `.processing` directories are cleaned under the writer lock. Failed or retained
  claims stay for recovery.
- Claim `subject_id` values now resolve against the registry: a dangling subject is a
  validation error and a wrong subject kind is a warning instead of disappearing from
  distance queries without a report.
- Corpus proposal/review bindings now cover the changed records and their
  explicit reference closure rather than every record. An unrelated record
  revision no longer makes a proposal stale; a changed referenced dependency
  still does.
- `\lean` and `\uses` outside a mathematical block are preserved as `describes` /
  `references` with a diagnostic instead of producing an invalid typed endpoint that
  aborts extraction. A `\def`/`\let` now marks its name as defined for a later
  statically decidable `\ifdefined`, and a failed structural scan is an error so
  `--strict` keeps the snapshot in staging.
- The human renderer refuses to replace a pre-existing `human/Index.md` that is not a
  generated page, and a failure to write the derived operational status no longer
  reports a published release as failed.
- Distance hard filters now default to computed/certificate evidence. Source-reported
  evidence requires `--evidence-policy source_reported` and an exact metric revision;
  corpus queries expose the same switch. Lean build evidence is not part of the default
  policy.
- Candidate publication and `validate` now re-check stored research records, so a
  replaced source projection cannot leave dangling field locators in a published
  release. Damaged research revisions are reported as validation issues instead of
  escaping as an internal error.
- Read projections load the deferred Lean integration only when a state actually
  contains Lean projects or Lean evidence; ordinary database, query and MCP paths no
  longer import it.
- Command-usage conflicts (for example `--store` together with `--release`) exit with
  code 64 and a `USAGE` envelope instead of code 1.
- The `qecgraph` package is grouped into `core/`, `source/`, `domain/`,
  `render/`, `mcp/` and `lean/` implementation packages. `store.py`,
  `workspace.py` and `corpus.py` remain cohesive service modules for a later
  split. Only `qecgraph.splitter` and `qecgraph.mcp_server` remain as thin
  compatibility shims for documented module entry points. This intentionally
  changes new snapshot tool identities; existing snapshots remain valid.
- Removed the repository-root `schemas/` compatibility folder. It contained no
  schema files, only a redirect README; canonical schemas remain packaged under
  `qecgraph/validators/schemas/` and all references now use that path.
- CI is reduced to one Linux/Python 3.11 `Lint and test` job: ruff, mypy,
  advisory pyright and the unit-test layer. Markdown-structure,
  integration/contract tests, coverage gates, distribution, installed-wheel,
  Docker and platform-isolation steps are no longer run on every push; those
  remain local/manual checks.
- Tests are organized by scope under `tests/unit/`, `tests/integration/` and
  `tests/contracts/`, with functional subdirectories inside each layer.
  `unittest discover -s tests` still runs the complete suite; per-layer
  commands are documented in `tests/README.md`.
- Current documentation is now bilingual: every current page under `docs/`, the
  root README, contributor/security policies and the validation index has an
  English and a Simplified Chinese counterpart with matching headings, tables
  and executable examples. Validation evidence is grouped by function instead
  of `p0`–`p5` stage numbers, and a scheduled Lychee workflow checks external
  links. Module import boundaries are now pinned by `tests/contracts/tooling/test_architecture.py`, and
  every repository tool is smoke-tested by `tests/contracts/tooling/test_tools.py`. Runtime code
  and extraction tool identity are deliberately unchanged in this release.
- Documentation pages now use a common status + `## On this page` structure,
  GitHub alerts, task-oriented tables and Mermaid diagrams. The root README
  links the main reading paths directly. A local `markdownlint-cli2` check
  covers heading/list/link-fragment structure; CI keeps only ruff, mypy,
  advisory pyright and unit tests.
- Lean is explicitly **deferred** in 0.5.x. The experimental code and
  validation fixtures remain only for regression; the CLI group is marked
  experimental, and the database, query and MCP paths do not invoke Lean.
  Superseded Lean design pages were removed from the documentation tree.
- Documentation now has one authoritative design (`docs/design/DESIGN.md`),
  user guides under `docs/user/`, and operations under `docs/operations/`.
  Redirect-only and historical archive pages were removed; superseded material
  remains in Git history.
- The historical schema sample moved to `legacy/knowledge_starter/`; the
  obsolete root `requirements-*.txt` files were removed.
- Workspace maintenance prints a one-line report by default. Scripts that
  parse its output should pass `--json`, including scripts that select a
  workspace with `--workspace`.
- Argument and command usage errors exit with code 64. A partial operation
  continues to exit with code 2.
- CLI errors returned with `--json` now have a versioned envelope on stdout
  (`mcp serve` startup errors stay on stderr). A missing required file exits
  with code 4. Successful JSON reports and partial workspace reports keep
  their existing fields.
- A writer lock held by another process exits with code 5. Damaged workspace
  configuration and CURRENT files report the path to inspect.
- An exact query target that is missing exits with code 4. Ambiguous labels
  report candidate IDs. With `--json`, fixed-scope query errors use the CLI
  envelope and keep the read tool's scope and error code.
- `qec-graph --version` and `qec-graph help <command>` report the installed
  version and available command options.
- Related commands have grouped names and examples. `qec-graph help aliases`
  lists supported older spellings and their replacements. Daily shortcuts
  remain supported without a notice.
- `--quiet` hides successful reports and progress; `--color` controls the
  color in workspace summaries.
- Workspace queries support fixed releases. Splitting a store with annotations
  or a catalog requires explicit `--force` to replace CURRENT.
- Generated Obsidian pages use readable filenames. Existing generated links
  remain usable through forwarding or archive pages. See the advanced guide
  before rolling back to an older renderer.
