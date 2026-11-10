# QEC Graph quick start

> **Status: Current (0.6.x).** The shortest path from installation to a first query.

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
| 2 | Enter an empty directory and run `qec-graph init` | `inputs/` and `qecgraph.toml` are created; nothing is extracted |
| 3 | Optionally configure `[ai]` in `qecgraph.toml` and run `qec-graph ai test` | The provider reports a successful schema-bound probe |
| 4 | Put a LaTeX source package in `inputs/` and run `qec-graph sync` | Successful packages enter `archive/`; inbox copies are cleared |
| 5 | Run `qec-graph status` / `validate` | Indexed counts and integrity results are shown |

```sh
mkdir my-qec
cd my-qec
qec-graph init
# Optional: configure [ai] in qecgraph.toml before syncing.
qec-graph ai status
qec-graph ai test
# Add downloaded TeX source packages to inputs/, then:
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
