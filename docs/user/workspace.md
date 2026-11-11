# Workspace guide

> **Status: Current (0.6.x).** Workspace configuration, Obsidian and provider handoff.

> **English** · [中文](workspace.zh-CN.md)

`0.6.2` is the published release; this guide follows main, including Unreleased changes. The existing `qecgraph`,
`qec-latex-split` and `qecgraph-mcp` commands and the SourceGraph, LemmaGraph and
DataGraph views remain available; Lean is a deferred experimental capability,
see [the system design](../design/DESIGN.md#10-lean-deferred-not-supported).
This guide describes the supported workflow; [the system design](../design/DESIGN.md)
defines the contract. The [validation index](../../validation/README.md) lists the
current executable checks; historical run artifacts remain in Git history.

> [!WARNING]
> Human notes are never search inputs. The new thoughts-only layout deletes
> the managed old `human/` tree without a backup; see the migration below.

## On this page

- [Create and operate a workspace](#create-and-operate-a-workspace)
- [Research queries and review](#research-queries-and-review)
- [Obsidian and machine isolation](#obsidian-and-machine-isolation)
- [Import an existing corpus](#import-an-existing-corpus)

## Create and operate a workspace

Install the actual wheel in a Python 3.11+ POSIX environment. No API key is required.

```bash
python -m pip install /path/to/qec_graph-0.6.2-py3-none-any.whl
mkdir -p ~/qec
cd ~/qec
qec-graph init
# Add downloaded source packages to inputs/ before syncing.
qec-graph sync --dry-run
qec-graph sync
qec-graph status
qec-graph rebuild
qec-graph validate
```

### AI configuration

`init` writes an `[ai]` table and provider blocks for OpenAI, Anthropic,
OpenRouter and Claude Code. OpenRouter is selected by default with model
`deepseek/deepseek-v4.1-flash-1017`; `api_key` is empty for the user to fill in,
or set `OPENROUTER_API_KEY`. An available provider can help with multi-root
normalization, eligible local parser failures and semantic proposal extraction.
A key placed in `qecgraph.toml` is protected by mode `0600` but should not be committed.

```toml
[ai]
enabled = true
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash-1017"
max_parallel_packages = 2
structure_fallback = true
extract_proposals = true

[ai.providers.openrouter]
kind = "openai_compatible"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
api_key = ""
```

`qec-graph ai status` reports the selected provider without contacting it;
`qec-graph ai test` makes one schema-bound connectivity probe. `qec-graph init`
never calls either command automatically.

`structure_fallback` defaults to `true` and also requires a ready provider and
`allow_source_upload`. A fallback request contains only the selected entry's
numbered body. The body must have unique standalone delimiters and no external
TeX body inputs. Failed or declined plans leave the archive and inbox copy
available for retry. Status reports show the recovery state. A successful
recovery records `recovered_proposed` on the snapshot. Upgrade machine
readers before pointing them at a release that uses this status. The updated
CLI and MCP continue to read previously published snapshots.

`extract_proposals` defaults to `true`: once credentials are available, `sync`
generates theorem, assumption, data and research-thought proposals. Set it to
`false` to skip this extraction, or set `[ai].enabled = false` to disable AI.
Existing explicit provider, model and flag values are retained; new defaults
apply to generated configurations and omitted selection/flag fields. See the
[thought extraction workflow](data-and-search.md#extract-and-read-research-thoughts)
for the skill, review boundaries and upgrade behavior.
`max_parallel_packages` bounds this optional extraction.
Publication and input consumption remain serial.

The Claude Code provider uses bare mode with tools, MCP and session persistence
disabled. Set `ANTHROPIC_API_KEY` and remove custom CLI arguments when upgrading
a workspace that used the local subscription login.

Failed AI extraction remains pending after the structural release commits. A
later `sync` retries the failed skills from the archive. Rebuild verifies and
reuses committed normalization maps even with AI disabled. For an older release,
rebuild can bind a historical map when the saved plan and archive reproduce the
exact projection. An unconfirmed fallback still needs an explicit entry point or
a new plan.

Daily use is `qec-graph sync`, `qec-graph status` and `qec-graph validate`.
The terminal updates one progress line and ends with success or an error. `sync`
clears copies in `inputs/` only after successful archive and publication;
failed files stay for retry. Add `--json` for the detailed report. Except
`init`, commands prefer an explicit `--workspace`, then the current directory
and its parents, then `QECGRAPH_WORKSPACE`. `init` uses only the current
directory unless `--workspace` names another one.

A second `init` does not overwrite configuration and never extracts; `sync`
performs the import. `--keep-inputs` preserves successful files and `--no-human`
skips the human renderer. `rebuild` checks the complete
archive inventory and receipts, including packages that previously failed to
parse or had an unresolved entry point. When both the archive and the expanded
tree verify, a snapshot is reused only if it matches the current processor,
runtime and configuration. `rebuild --include-inputs` first syncs, then rebuilds
from the archive.

Sources are registered by default; there is no publication or quality gate.
Successful packages are consumed only after hash verification, machine
publication and registration. A partial batch exits 2; failed files stay in the
inbox or in a recoverable claim. Unknown semantics do not prevent keeping the
source, but they never satisfy exact filters as known parameters. Do not use a
repository workspace as a backup of user data.

If a package has multiple entry points, use `status --json` to inspect
`source_tree_hash` and candidates. Fill `[sources]` only when upstream identity
is actually evidenced. For example:

```toml
[entrypoints]
"实际来源树的 SHA-256" = "paper/main.tex"

[sources."实际来源树的 SHA-256"]
work_id = "arxiv:quant-ph/0610153"
upstream_version = "v1"
title = "Subsystem Codes"
```

A package name, paper title or `archive_sha256` does not replace an upstream
version. Keep and flag a conflict when the same declared version has different
source trees. The project parses source only; it does not execute TeX, package
scripts, software installation or Lean builds. TAR extended metadata (such as
PAX and GNU long names) is limited to 256 KiB per entry, 4 MiB per package and
32 consecutive extensions. An over-limit package is archived and reported as
`limit_exceeded`; the original submission is retained.

## Research queries and review

```bash
qec-graph review list
qec-graph software import-seed
qec-graph software coverage
qec-graph software refresh --project-id software:stim  # 显式联网，仅公开元数据
qec-graph mcp config --workspace ~/qec
qec-graph mcp serve --workspace ~/qec
```

`mcp-config` generates a client configuration pinned to one release. See
[MCP setup](../../README.md#mcp) for Codex, Claude Code and OpenCode examples.
Source queries use registered occurrence IDs and half-open Unicode codepoint ranges;
MCP resource URIs are fixed identifiers and cannot be rewritten as file paths.
The CLI can call the same query layer with
`query-tool TOOL --workspace ~/qec --arguments request.json`. Performance queries
return the exact experiment and curve revision, open conditions and actual
coordinates; they never rank across experiments. Research records use
the single current `qecgraph.research` format. `asset-add` registers non-human
assets; only assets bound to visible records can be read by bytes.

`extract-request SOURCE_ID` exports bounded excerpts with exact locators. You may
give that file to a provider of your choice and return `research` records as
`{"provider":{"model_id":"…","processor_version":"…","prompt_sha256":"…"},"records":[…]}`.
`extract-submit REQUEST_ID response.json` validates and stages the response;
`extract-review PROPOSAL_ID --reviewer NAME --decision approve --rationale "…"`
publishes that exact draft and records the review scope. Rejected or stale
drafts do not appear in default results. This review applies only to new
semantic assertions; raw materials are discoverable without approval. There is
no built-in external model call or curve digitisation; missing data appears as
pending extraction or unresolved.

## Obsidian and machine isolation

Open `~/qec/human` in Obsidian and browse the year/month folders. Each paper has
one `Surname_First_Two_thoughts.md` containing the nine ThoughtsGraph questions,
AI answers and source quotations. The first content is Obsidian YAML:

```yaml
---
tags:
  - surface-codes
  - erasure-decoding
link: "https://example.org/paper"
title: "Surface codes under erasure"
author:
  - "Ada Lovelace"
---
```

This is a format example; actual properties come from the registered source and
quoted AI metadata. Tags are the paper's main topics, authors retain source order,
and the first author's surname plus the first two title words form the filename
(e.g. `Ruiz_Entropy_threshold_thoughts.md` for Diego Ruiz). The YAML `author` list
keeps full names. The original arXiv package name determines `YYYY/MM/` first:
`arXiv-2611.12971v2.tar.gz` goes into `2026/11/`, regardless of the manuscript date
or download time. Version suffixes do not change that initial submission month.
Non-arXiv names fall back to the source date; missing or conflicting months use
`unknown`. Sync/rebuild snapshots receipt filenames into the machine release;
run `qec-graph sync` once to backfill an older workspace, then `human build` uses
only that fixed release. Full-name note paths are removed as new paths publish.
Missing author/title use `UnknownAuthor`/`Untitled_Paper`; filename collisions
receive a short work-ID hash. Multiple versions of one work share one note;
answers retain their own source versions. [Full contract](../design/DESIGN.md#9-human-view)

`qec-graph human build` renders the current fixed machine release without calling
AI. `sync` performs configured AI extraction; existing completed batches are not
automatically re-extracted after a skill upgrade. Missing answers stay explicit.
There are no generated indexes, entity pages, source previews, tombstones or
`notes/` directory. Personal notes belong outside `human/`.

**Migration from the v0.6.2 layout:** the first render with this Unreleased
implementation detects the old renderer history and deletes the whole old
`human/`, including its old `notes/`, without reading contents or creating a
backup. It then publishes only the paper notes. An unregistered external vault
is refused. Later builds delete obsolete managed notes when filenames change.
State and recovery journals live in `.qecgraph/`; each note is written atomically.
A partial failure reports `human_stale`; rerun `qec-graph human build` to finish,
without rolling back the machine release.

Grant the machine release directory to agents and MCP only; do not grant the
whole workspace. On Linux, use `compose.mcp-isolated.yaml` from the repository.
From a Python environment with QEC Graph installed, run
`python tools/reproduce_linux_isolation.py --out build/linux-isolation.json` to
re-check the read-only mount, network isolation and a real MCP query in a
temporary workspace. On macOS, use the measured isolation launcher:

```bash
python tools/mcp_isolated_macos.py --python /path/to/installed-venv/bin/python --machine ~/qec/machine
```

The container configuration uses `compose.mcp-isolated.yaml`; set
`QEC_MACHINE_DIR`, `QEC_MCP_UID` and `QEC_MCP_GID` and mount only the machine
directory read-only. The Linux profile was verified with an alternate local
Ubuntu base; the [validation index](../../validation/README.md) lists the current
isolation check commands. That is not a claim of a generic Docker Hub build. Do not treat MCP roots or a
plain `--workspace` argument as operating-system isolation.

## Import an existing corpus

```bash
qec-graph validate-corpus --corpus /path/to/legacy-corpus
qec-graph workspace migrate --corpus /path/to/legacy-corpus --workspace /path/to/new-workspace
qec-graph rebuild --workspace /path/to/new-workspace
```

The target must be a separate new directory. Migration preserves old revisions,
source snapshots, assets and review bindings, and reports records missing exact
bound types, noise, counting definitions or experiment context. The old corpus
remains usable; keep using it if migration is unsuitable. It never fabricates
download packages the old corpus did not contain. Upgrading the program and
moving data are separate operations; public PyPI publication has not been
performed.
