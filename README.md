# QEC Graph

QEC Graph turns LaTeX papers into a searchable quantum error correction (QEC)
workspace. It archives the original sources, links records to the relevant
passages, and makes the results available in Obsidian and over read-only MCP.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/Guangqi-Phys/qec-graph/main/install.sh | sh
```

Run the same command to update. The standalone executable bundles Python.
Downloads are available for Apple Silicon and Linux x86_64 and arm64.
[GitHub Releases](https://github.com/Guangqi-Phys/qec-graph/releases)

## Usage

Run these commands in the folder you want to use as your workspace.

```sh
mkdir -p inputs
# Put downloaded LaTeX source packages in inputs/.
qec-graph init --workspace .

# After adding more packages
qec-graph sync
qec-graph status
qec-graph validate
```

Successful imports keep the original package in `archive/` and clear its inbox
copy. Open `human/` as an Obsidian vault and start at `Index.md`.
[Advanced usage](docs/user/advanced-usage.md)

## MCP

From the initialized workspace root, register the read-only server with Codex.

```sh
codex mcp add qecgraph -- "$(command -v qec-graph)" mcp serve --machine "$PWD/machine"
```

Open a new Codex session after registering. For other MCP clients, run
`qec-graph mcp config --workspace .` to print a configuration pinned to the
current snapshot. [Data and search guide](docs/user/data-and-search.md)

[Documentation index](docs/README.md)
