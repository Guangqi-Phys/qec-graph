# QEC Graph

> Provenance-preserving LaTeX → QEC knowledge workspace, with a CLI, a local
> read-only MCP server, and an Obsidian view.

> **English** · [中文](README.zh-CN.md)

QEC Graph archives original LaTeX source packages, extracts their structure with
exact source spans, links typed QEC research records and field-level evidence,
and publishes an immutable machine release. The same release serves the CLI, the
read-only MCP server and the generated Obsidian view; the human view is never an
authority or a search input. Personal notes belong outside `human/`.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/Guangqi-Phys/qec-graph/main/install.sh | sh
```

Run the same command to update. The standalone executable bundles Python.
Downloads are available for macOS and Linux on arm64 and x86_64.
[GitHub Releases](https://github.com/Guangqi-Phys/qec-graph/releases)

## Quick start

Run these commands in an empty folder, or one containing only `inputs/`. Other
entries make `init` stop before writing anything.

```sh
mkdir my-qec
cd my-qec
qec-graph init
# The command creates inputs/ and qecgraph.toml.
# AI: fill in your OpenRouter API key in qecgraph.toml or OPENROUTER_API_KEY, then:
qec-graph ai status
qec-graph ai test
# Put downloaded LaTeX source packages in inputs/, then run:
qec-graph sync
qec-graph status
qec-graph validate
```

`init` never extracts or calls AI. It only prepares the inbox and configuration;
`qec-graph sync` performs the import. The local parser handles ordinary
packages. With an API key configured, AI can help with eligible parser failures
and ambiguous multi-root packages. Semantic proposal extraction defaults to
enabled; set `extract_proposals = false` to skip those skills.

Successful imports keep the original package in `archive/` and clear its inbox
copy. Open `human/` in Obsidian and browse `YYYY/MM/*_thoughts.md`: one file
per paper with nine research questions, AI answers and topic tags. This layout
ships in v0.6.3; upgrading from the v0.6.2 layout deletes the
old `human/` contents without a backup. [Layout and migration](docs/user/workspace.md#obsidian-and-machine-isolation)
Use `qec-graph inputs quarantine <name>` for a package that keeps failing.

## AI extraction

AI is optional. The parser runs first on the selected original entry. For an
eligible structural failure, AI can propose a partition of the numbered body.
The program verifies the ranges and copies verbatim source into the usual
snapshot. These block classifications stay `proposed`. Use
`qec-graph search TERM --workspace . --view reading` for the derived reading
text. The raw query and source resources retain citations and bibliography.

`qecgraph.toml` is generated with these provider templates:

| Provider | Kind | Default credential |
|---|---|---|
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| OpenRouter | `openai_compatible` | `OPENROUTER_API_KEY` |
| Claude Code | `cli` | `ANTHROPIC_API_KEY` in bare mode |

The default provider is OpenRouter, with model
`deepseek/deepseek-v4.1-flash-1017` and proposal extraction enabled. The generated
`api_key` is empty: fill it in or set `OPENROUTER_API_KEY`. To use another
provider, change both the provider and its model ID.

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

Check the configuration without sending paper text, then import:

```sh
qec-graph ai status
qec-graph ai test
qec-graph sync
```

If `inputs/` has several TeX roots, the normalizer proposes a source-mapped
`main.tex`; the parser then extracts it. If AI is unavailable, a package with
several roots remains archived and asks for an entry point instead.

## How it works

### Four graph views

QEC Graph organizes the same sources and records through four connected views:

| View | What it helps you understand |
|---|---|
| SourceGraph | Where a passage appears, its document structure, context and exact source version |
| LemmaGraph | Definitions, assumptions, statements, proof text and the status of their dependencies |
| DataGraph | Which codes, matrices, circuits, noise models, decoders and experiment conditions belong to a result |
| ThoughtsGraph | The paper's problems, motivations, approaches, intuitions, assumptions, conclusions, open questions, surprises and side results |

ThoughtsGraph uses source-quoted `research_thought` records and typed links.
Author statements and editorial interpretations stay distinct; AI output remains
proposed. Generated data, catalog descriptions and human notes use English.
`sync` replaces legacy Chinese AI proposals with newly extracted English results.
All four views share identities and provenance. See
[graph roles and thought queries](docs/user/data-and-search.md#how-the-four-graphs-work-together).

### Publication pipeline

The pipeline is one writer; each stage leaves a named artifact for the next. Implementation docs live under `docs/user/`, `docs/design/` and `docs/operations/`.

| Node | Purpose | Implementation docs | Input | Output |
|---|---|---|---|---|
| `inputs/` | Receive candidate source packages | [Quick start](docs/user/quickstart.md), [Workspace guide](docs/user/workspace.md) | `.tex`, `.tar`, `.tar.gz`/`.tgz`, `.zip`, `.gz` | claimed inbox files and `.processing/<job>/job.json` |
| `archive/` | Preserve original bytes and a receipt | [System design](docs/design/DESIGN.md#7-workspace-transaction-and-publication-protocol), [Workspace guide](docs/user/workspace.md) | claimed package | `archive/blobs/sha256/<sha256>`, `archive/receipts/<job>.json` |
| `source tree` | Verify, unpack and select or normalize the entry point | [Workspace guide](docs/user/workspace.md), [Splitter](docs/user/splitter.md), [AI extraction](#ai-extraction) | archived blob | `sources/<tree-hash>/...`; optional derived `machine/derived/normalizations/.../main.tex` |
| `parser` | Extract sections, environments, labels, refs and spans | [Splitter](docs/user/splitter.md), [System design](docs/design/DESIGN.md#5-source-extraction) | verified `.tex` tree | store: `snapshots/<snapshot-id>/`; workspace: `machine/source_snapshots/<snapshot-id>/`; both contain `graph.json`, `manifest.json`, `report.json`, `graph.sqlite`, `nodes/<kind>/` |
| `research records` | Store typed QEC objects and field evidence | [Data and search](docs/user/data-and-search.md), [System design](docs/design/DESIGN.md#4-data-contracts) | source snapshot plus `research` JSON | `machine/research/<hash(id)>/<hash(revision)>.json` with `schema: qecgraph.research` |
| `review` | Bind proposals and decisions to exact content | [Review](docs/operations/review.md), [System design](docs/design/DESIGN.md#6-review-evidence-and-query-eligibility) | proposal JSON and explicit decision | `machine/proposals/<hash>.json`, `machine/reviews/<hash>.json`, `machine/states/<revision>.json` |
| `release` | Validate everything and publish one immutable release | [System design](docs/design/DESIGN.md#7-workspace-transaction-and-publication-protocol), [Maintenance](docs/operations/maintenance.md) | staged records and snapshots | `machine/CURRENT.json` with `format` and `revision`; `machine/states/<revision>.json` |
| `CLI` | Read a fixed workspace, store or corpus scope | [Advanced usage](docs/user/advanced-usage.md), [Data and search](docs/user/data-and-search.md) | `--workspace`, `--machine`, `--store` or `--corpus`; JSON arguments for `query-tool` | terminal text or versioned JSON |
| `MCP` | Serve read-only tools over local stdio | [MCP setup](#mcp), [Data and search](docs/user/data-and-search.md) | JSON-RPC 2.0 over stdio; one pinned release; legacy/research/compatible profile | JSON-RPC frames, text/structured content, `qec://source/...` resources |
| `human/` | Render an Obsidian view; never write back | [Workspace guide](docs/user/workspace.md), [System design](docs/design/DESIGN.md#9-human-view) | published machine release | `human/YYYY/MM/Surname_First_Two_thoughts.md`; renderer state in `.qecgraph/` |

One writer owns the pipeline. Readers pin one `CURRENT` release; a failed
validation leaves the previous release readable. Human notes are never knowledge inputs.

> [!NOTE]
> QEC Graph is not a TeX engine, a PDF/OCR pipeline, a large-code distance
> solver, or a Lean verifier. Lean is **deferred/experimental**; the database,
> query and MCP paths do not import or invoke it.

## At a glance

| Capability | What is implemented |
|---|---|
| Ingestion | TeX/gzip/tar/tar.gz/ZIP detection, safe unpacking, SHA-256 blobs and receipts, entry-point selection |
| Provenance | UTF-8 byte hashes, Unicode codepoint half-open spans, 1-based lines, stable IDs and revisions |
| Research model | `qecgraph.research` records, 27 kinds, 47 typed relations, field evidence, explicit unknown/conflict states |
| Review | Proposal/diff, explicit decide, hash-bound apply, stale review detection |
| Query | Exact filters, bounded context, dependency/impact traversal, code/performance/software queries |
| MCP | Legacy (13), research (7), or generic search/fetch (2) tools; source resources, budgets and one pinned release per session |
| Knowledge retrieval | Full source/section/outline reads, optional local or external embeddings, hybrid search, task contexts and coverage reports |
| AI assistance | Optional provider config, source-mapped normalization of multiple TeX roots, proposed theorem/assumption/data/thought extraction |
| Human view | One Obsidian thoughts note per paper, with topic tags, bibliographic properties and nine questions |
| Surfaces | Workspace is primary; single-paper store and multi-paper corpus remain available |

## Implemented surfaces

| Surface | Current implementation |
|---|---|
| Workspace transaction | claim → archive → unpack → entry point → extract → stage → validate → publish → consume, with a POSIX writer lock and crash recovery |
| Source extraction | `pylatexenc==2.10`, source-preserving spans, include/resource resolution, explicit diagnostics, content-checked incremental AST cache |
| Research records | `qecgraph.research` kinds such as `quantum_code`, `check_matrix`, `distance_estimate`, `performance_curve`, `experiment` and `software_usage` |
| Review and evidence | `proposal` / `review` envelopes, field-level evidence, reviewed dependency closure, stale and unbound states excluded by default |
| Read queries | `search`, `show`, `deps`, `impact`, `context`, `codes`, `performance`, `software`; SQLite/FTS5 with a deterministic fallback |
| MCP server | local stdio JSON-RPC `2025-06-18`, read-only tools, source resources, per-call budgets, no path or shell arguments |
| Human view | deterministic `human/YYYY/MM/*_thoughts.md` notes, per-file atomic writes, obsolete-note cleanup, `human_stale` recovery |
| AI layer | provider adapters, schema-bound client, versioned skills, source-mapped normalization and reviewable proposals |
| Distribution | wheel/sdist, standalone executables, research Compose profile and read-only MCP isolation profile |

## MCP

The MCP server is a local stdio process pinned to one machine release. It is
read-only: tools cannot pass filesystem paths, SQL, shell commands, a different
workspace or a different release. Source text is returned as data, never as
instructions.

### Start the server

From the workspace root:

```sh
qec-graph mcp config --workspace .
```

This prints a ready `mcpServers.qecgraph` object whose command and `--machine`
path point at the current pinned release. Use that object in a client config, or
start the server directly:

```sh
qec-graph mcp serve --machine "$PWD/machine"
```

For a strict deployment, mount only `machine/` and pass `--machine`. `--workspace`
is convenient locally but is not an operating-system isolation boundary.
`human/`, `inputs/` and personal notes must not be readable in a
strict deployment.

### Read tools

The default `legacy` profile retains the tools below. Use
`qec-graph mcp config --workspace . --profile research` for the seven research
tools, or `--profile compatible` for generic `search`/`fetch` with registered
public citation URLs. See [knowledge queries](docs/user/data-and-search.md#document-reading-profiles)
for full-source reading, vector configuration and task context examples.

| Tool group | Available tools |
|---|---|
| Graph reads | `qecgraph_search`, `qecgraph_show`, `qecgraph_context`, `qecgraph_deps`, `qecgraph_impact` |
| Workspace records and sources | `qec_workspace_status`, `qec_get_entity`, `qec_get_context`, `qec_get_source`, `qec_get_asset` |
| Structured QEC queries | `qec_find_codes`, `qec_find_performance`, `qec_find_software` |

All tools accept `max_chars` within the session budget. Search and the three
`qec_find_*` tools also accept `limit`/`offset`. Source text uses half-open
Unicode codepoint ranges; managed asset bytes use byte offsets. A result states
its scope, evidence status and whether it was truncated. No result means no match
in the pinned scope, not that a theorem or code does not exist.

### Connect a client

The examples below use a shell command; replace `/absolute/path/to/qec-graph`
and `/absolute/path/to/machine` with the installed executable and the workspace
machine directory. To pin a specific release, add `--release <release-id>`.

#### Codex

```sh
codex mcp add qecgraph -- "$(command -v qec-graph)" mcp serve --machine "$PWD/machine"
codex mcp list
```

Equivalent `~/.codex/config.toml` entry:

```toml
[mcp_servers.qecgraph]
command = "/absolute/path/to/qec-graph"
args = ["mcp", "serve", "--machine", "/absolute/path/to/machine"]
```

Open a new Codex session after adding the server. Codex starts the stdio process
and exposes the read tools to the agent.

#### Claude Code

```sh
claude mcp add --transport stdio qecgraph -- "$(command -v qec-graph)" mcp serve --machine "$PWD/machine"
claude mcp list
```

Equivalent project `.mcp.json`:

```json
{
  "mcpServers": {
    "qecgraph": {
      "type": "stdio",
      "command": "/absolute/path/to/qec-graph",
      "args": ["mcp", "serve", "--machine", "/absolute/path/to/machine"]
    }
  }
}
```

Claude Code starts the server per session; approve the project-scoped `.mcp.json`
when prompted.

#### OpenCode

```sh
opencode mcp add qecgraph -- qec-graph mcp serve --machine "$PWD/machine"
opencode mcp list
```

Equivalent `opencode.json` or `opencode.jsonc`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "qecgraph": {
        "type": "local",
        "command": ["/absolute/path/to/qec-graph", "mcp", "serve", "--machine", "/absolute/path/to/machine"]
      }
    }
  }
}
```

Use `disabled: true` to keep the server configured without connecting it.

### Pin and refresh

`qec-graph mcp config --workspace .` includes `--release` by default, so the
client gets exactly the release that was current when the config was generated.
After `qec-graph sync` publishes a new release, re-run the command and replace
the client entry. Existing sessions stay on their old release until restarted.
Use `qec-graph mcp config --machine /path/to/machine` for a machine-only mount.

## Documentation map

| I want to… | Read |
|---|---|
| Run the shortest example | [Quick start](docs/user/quickstart.md) |
| Configure a workspace, archive or Obsidian | [Workspace guide](docs/user/workspace.md) |
| Search records, codes or performance data points | [Data and search](docs/user/data-and-search.md) |
| Understand the four graphs and read research thoughts | [Graph roles and ThoughtsGraph](docs/user/data-and-search.md#how-the-four-graphs-work-together) |
| Look up commands, exit codes or release checks | [Advanced usage](docs/user/advanced-usage.md) |
| Understand identities, evidence and publication | [System design](docs/design/DESIGN.md) |
| Browse the documentation index | [docs/README.md](docs/README.md) |
| Operate a store or corpus | [Operations](docs/operations/README.md) |

## License

MIT. See [LICENSE](LICENSE) and [CONTRIBUTING](CONTRIBUTING.md) for development
and documentation rules.
