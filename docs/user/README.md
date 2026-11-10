# User guides

> **Status: Current (0.4.x).**

> [!TIP]
> If you have never run QEC Graph, use the [Chinese quick start](quickstart.zh-CN.md).
> If you already have a workspace, jump straight to the task table below.

## On this page

- [Choose by task](#choose-by-task)
- [Guide map](#guide-map)
- [Common flow](#common-flow)

## Choose by task

| I need to… | Go to |
|---|---|
| Install and import a first paper | [Quick start](quickstart.zh-CN.md) |
| Configure entry points or archive behavior | [Workspace guide](workspace.md) |
| Search sources, records, codes or performance points | [Data and search](data-and-search.md) |
| Look up a command, exit code or release check | [Advanced usage](advanced-usage.md) |
| Split a single LaTeX project without the workspace | [Single-paper splitter](splitter.md) |
| See what changed between releases | [Changelog](../../CHANGELOG.md) |

## Guide map

| Guide | Language | Focus |
|---|---|---|
| [Quick start](quickstart.zh-CN.md) | 中文 | Shortest path: install → `init` → `sync` → `status` → query |
| [Workspace guide](workspace.md) | 中文 | `qecgraph.toml`, entry points, provenance, Obsidian, review handoff |
| [Data and search](data-and-search.md) | English | `research.v1`, evidence, distance policy, CLI/MCP queries |
| [Advanced usage](advanced-usage.md) | English | Installers, command groups, JSON/exit codes, release checks |
| [Single-paper splitter](splitter.md) | 中文 | Source spans, fragment layout, custom environments, limits |

## Common flow

```mermaid
flowchart LR
    A[Put a source archive in inputs/] --> B[qec-graph init]
    B --> C[qec-graph sync]
    C --> D[qec-graph status]
    D --> E[qec-graph query search ...]
    D --> F[Open human/Index.md in Obsidian]
    D --> G[qec-graph mcp serve --machine ...]
```

For schema, publication and MCP guarantees behind these commands, see the
[system design](../design/DESIGN.md).
