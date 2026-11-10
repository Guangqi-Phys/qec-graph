# QEC Graph quick start

> **Status: Current (0.4.x).** The shortest path from installation to a first query.

> **English** · [中文](quickstart.zh-CN.md)

> [!TIP]
> For full configuration, exit codes or MCP details, continue with
> [Advanced usage](advanced-usage.md) or the [Workspace guide](workspace.md).

## On this page

- [Shortest path](#shortest-path)
- [What next](#what-next)

## Shortest path

| Step | Action | Expected result |
|---|---|---|
| 1 | Install via the [installation instructions](../../README.md#install) | `qec-graph --version` prints a version |
| 2 | Enter a working directory and create `inputs/` | The directory contains `inputs/` |
| 3 | Put a LaTeX source package there and run `qec-graph init` | The terminal reports a published or partial batch |
| 4 | Run `qec-graph sync` | Successful packages enter `archive/`; inbox copies are cleared |
| 5 | Run `qec-graph status` / `validate` | Indexed counts and integrity results are shown |

```sh
mkdir -p inputs
# Put downloaded TeX source packages in inputs/
qec-graph init --workspace .
qec-graph sync
qec-graph status
qec-graph validate
```

## What next

| Goal | Command / entry point |
|---|---|
| Search sources and records | `qec-graph query search HGP --workspace .` |
| Browse the human view | Open `human/` in Obsidian and start at `Index.md` |
| Connect a read-only MCP client | `qec-graph mcp config --workspace .` |
| Handle a failing package | `qec-graph inputs list`, then `qec-graph inputs quarantine <name>` |

Successful imports keep the original package in `archive/`; failed packages stay
in `inputs/` for retry. Open `human/` as an Obsidian vault and start at
`Index.md`. **Do not** use `human/notes/` as a search input.

[Advanced usage](advanced-usage.md) · [Data and search](data-and-search.md) · [Workspace guide](workspace.md)
