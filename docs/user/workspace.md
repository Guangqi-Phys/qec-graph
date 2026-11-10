# Workspace guide

> **Status: Current (0.4.x).** Workspace configuration, Obsidian and provider handoff.

> **English** · [中文](workspace.zh-CN.md)

`0.4.0rc1` is a locally installable release candidate. The existing `qecgraph`,
`qec-latex-split` and `qecgraph-mcp` commands and the SourceGraph, LemmaGraph and
DataGraph views remain available; Lean is a deferred experimental capability,
see [the system design](../design/DESIGN.md#10-lean-deferred-not-supported).
This guide describes the supported workflow; [the system design](../design/DESIGN.md)
defines the contract, and the [workspace acceptance report](../../validation/workspace-0.4.0rc1/report.md)
lists what was actually tested and what remains open.

> [!WARNING]
> `human/notes/` is private. Generators, queries and MCP never read it; do not
> use it as a search input.

## On this page

- [Create and operate a workspace](#create-and-operate-a-workspace)
- [Research queries and review](#research-queries-and-review)
- [Obsidian and machine isolation](#obsidian-and-machine-isolation)
- [Migrate from a legacy corpus](#migrate-from-a-legacy-corpus)

## Create and operate a workspace

Install the actual wheel in a Python 3.11+ POSIX environment. No API key is required.

```bash
python -m pip install /path/to/qec_graph-0.4.0rc1-py3-none-any.whl
mkdir -p ~/qec/inputs
cd ~/qec
# 把下载完成的 TeX 源包放进 inputs（下载时先用临时名）。
qec-graph init
qec-graph status
qec-graph sync --dry-run
qec-graph sync
qec-graph rebuild
qec-graph validate
```

Daily use is `qec-graph sync`, `qec-graph status` and `qec-graph validate`.
The terminal updates one progress line and ends with success or an error. `sync`
clears copies in `inputs/` only after successful archive and publication;
failed files stay for retry. Add `--json` for the detailed report. Commands
prefer an explicit `--workspace`, then the current directory and its parents,
then `QECGRAPH_WORKSPACE`.

A second `init` does not overwrite configuration. `--no-ingest` only initialises;
when running `sync` with other flags, `--keep-inputs` preserves successful
files and `--no-human` skips the human renderer. `rebuild` checks the complete
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

`mcp-config` generates a client configuration pinned to one release. Source
queries use registered occurrence IDs and half-open Unicode codepoint ranges;
MCP resource URIs are fixed identifiers and cannot be rewritten as file paths.
The CLI can call the same query layer with
`query-tool TOOL --workspace ~/qec --arguments request.json`. Performance queries
return the exact experiment and curve revision, open conditions and actual
coordinates; they never rank across experiments. Research records use
`qecgraph.research.v1` alongside historical v3. `asset-add` registers non-human
assets; only assets bound to visible records can be read by bytes.

`extract-request SOURCE_ID` exports bounded excerpts with exact locators. You may
give that file to a provider of your choice and return `research.v1` records as
`{"provider":{"model_id":"…","processor_version":"…","prompt_sha256":"…"},"records":[…]}`.
`extract-submit REQUEST_ID response.json` validates and stages the response;
`extract-review PROPOSAL_ID --reviewer NAME --decision approve --rationale "…"`
publishes that exact draft and records the review scope. Rejected or stale
drafts do not appear in default results. This review applies only to new
semantic assertions; raw materials are discoverable without approval. There is
no built-in external model call or curve digitisation; missing data appears as
pending extraction or unresolved.

## Obsidian and machine isolation

Open `~/qec/human` as an Obsidian vault and start at `Index.md`.
`human/generated` is rebuildable; put personal content in `human/notes`. The
generator does not read notes; old entity pages may remain as tombstones.
Multi-page updates replace each file atomically; a mid-way failure reports
`human_stale`, and `qec-graph human build` can recover without rolling back the
machine release.

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
directory read-only. The configuration parses, but Docker runtime verification
is still pending. Do not treat MCP roots or a plain `--workspace` argument as
operating-system isolation.

## Migrate from a legacy corpus

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
