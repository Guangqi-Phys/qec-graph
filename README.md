# QEC Graph

QEC Graph turns LaTeX papers into a searchable quantum error correction (QEC)
workspace. It archives the original sources and links statements, code records,
experiments, and evidence to their source spans. Read the results in Obsidian or
query a fixed workspace release over read-only MCP.

## Install

The current version is **0.4.0rc1**. Use Python 3.11 or newer, a local POSIX
filesystem, and SQLite with FTS5 enabled. The release candidate was tested on
macOS arm64. Run these commands from a checkout of this repository.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

If you have the release wheel, you can install it in the same way with
`python -m pip install /path/to/qec_graph-0.4.0rc1-py3-none-any.whl`.
Local ingestion and queries run without an API key.

## Install from GitHub Release on macOS

Sign in with `gh auth login` using a GitHub account that can read this private
repository, then run:

```sh
installer=$(gh release download v0.4.0rc1 --repo Guangqi-Phys/qec-graph --pattern install.sh --output -) && printf '%s\n' "$installer" | sh
```

The installer selects the Apple Silicon or Intel build, checks its SHA-256,
and installs `qec-graph` into `~/.local/bin`. Open a new terminal if the
installer adds that directory to your PATH. The release builds are tested on
macOS 15 and carry their own Python runtime.

## Single-file executable

Build on the target operating system and architecture. On Apple Silicon macOS,
use Python 3.13 and PyInstaller to bundle the runtime and dependencies.

```sh
python3.13 -m venv build/standalone-venv
build/standalone-venv/bin/python -m pip install . 'PyInstaller==6.22.3'
PYINSTALLER_CONFIG_DIR="$PWD/build/standalone-cache" \
  build/standalone-venv/bin/python -m PyInstaller --noconfirm \
  --distpath dist/standalone --workpath build/standalone tools/qec-graph.spec
```

Install the executable once in a user directory on `PATH`. For example, if
`~/.local/bin` is on your `PATH`, run:

```sh
mkdir -p "$HOME/.local/bin"
install -m 755 dist/standalone/qec-graph "$HOME/.local/bin/qec-graph"
```

From each directory you want to manage, initialize it once with
`qec-graph init --workspace .`. Then put source packages in `inputs/` and run
`qec-graph sync`, `qec-graph status`, or `qec-graph validate` from that directory.
The executable carries its own Python runtime. Explicit Lean builds require the
project's Lean toolchain.

## Start a workspace

Try the bundled paper from the repository root.

```sh
mkdir -p build
workspace="$(mktemp -d "$PWD/build/qec-workspace.XXXXXX")"
mkdir -p "$workspace/inputs"
COPYFILE_DISABLE=1 tar -czf "$workspace/inputs/qec-demo.tar.gz" -C examples/paper .

qec-graph init --workspace "$workspace"
qec-graph status --workspace "$workspace"
qec-graph validate --workspace "$workspace"
```

For your own collection, create an `inputs/` directory under your chosen
workspace and place completed LaTeX source packages there before running
`init`.

## Daily use

Run these commands from the workspace or any of its subdirectories.

```sh
qec-graph sync
qec-graph status
qec-graph validate
```

These commands update one terminal progress line and finish with a short result.
After successful import, `sync` clears the inbox copy and keeps the original in
`archive/`. Failed packages remain available for retry. Add `--json` for the
detailed report. From outside the workspace, set `QECGRAPH_WORKSPACE` to its
path or pass `--workspace` explicitly. The examples below reuse the `workspace`
variable from the quick start.

`init` registers submitted sources regardless of publication or review status.
It preserves the original package in `archive/` and removes the inbox copy only
after verification and publication succeed. Failed packages remain available
for retry. `status` shows their processing state.

```sh
# After adding another source package to inputs/
qec-graph sync --dry-run --workspace "$workspace"
qec-graph sync --workspace "$workspace"

# Check the entire archive and rebuild the derived workspace
qec-graph rebuild --workspace "$workspace"
```

Use `--keep-inputs` to retain successfully processed inbox copies. To ingest
pending inputs before rebuilding, use `rebuild --include-inputs`. For source
identity overrides and packages with multiple LaTeX entry points, see the
[workspace guide](docs/rfc-002/WORKSPACE.md).

## Search, connect MCP, and read in Obsidian

Search the demo from the terminal using the same query interface as MCP.

```sh
printf '%s\n' '{"query":"HGP","limit":5}' > "$workspace/search.json"
qec-graph query-tool qecgraph_search --workspace "$workspace" \
  --arguments "$workspace/search.json"
qec-graph mcp-config --workspace "$workspace"
```

`mcp-config` prints a client configuration pinned to the current release.
Use the generated configuration in your MCP client. For an isolated client,
give its process read access to `machine/` only. The workspace guide covers
the tested macOS launcher and the container configuration. [Isolation setup](docs/rfc-002/WORKSPACE.md#obsidian-和机器访问隔离)

Open the workspace’s `human/` directory as a vault in Obsidian and start at
`Index.md`. Keep personal notes in `human/notes/`. QEC Graph regenerates its
pages separately. You can rebuild them after a rendering failure.

```sh
qec-graph human build --workspace "$workspace"
```

The workspace guide also covers the software catalog, managed assets, and
reviewing structured extraction proposals. [Workspace guide](docs/rfc-002/WORKSPACE.md)

## Single papers and existing corpora

The standalone splitter and store commands remain available. These examples run
from the repository root and write to new or previously managed output
directories.

```sh
qec-latex-split examples/paper/main.tex --project-id qec-demo --out build/split
qec-graph ingest examples/paper/main.tex --project-id qec-demo --out build/graph \
  --annotations examples/annotations.example.json
qec-graph validate --store build/graph
qec-graph context thm:hgp-length --store build/graph
```

`qecgraph` is an alias for `qec-graph`, and `python -m qecgraph` uses the same
CLI. To move an existing corpus into the workspace format, use
`qec-graph workspace-migrate --corpus /path/to/corpus --workspace /path/to/new-workspace`.
The migration copies source snapshots, record revisions, and review bindings to
a new directory. [Splitter reference](docs/03_SPLITTER.md) · [Corpus reference](docs/09_CORPUS.md) · [Migration guide](docs/rfc-002/WORKSPACE.md#从旧库迁移)

## Verification and scope

The parser extracts supported TeX structure and preserves source coordinates.
Validation checks provenance and record bindings. Mathematical computation,
Lean builds, and semantic review have separate evidence and status. Performance
queries return the experiment and curve revisions, along with any missing
conditions. General figure digitization and automatic extraction of complex
experiments are outside this release candidate’s scope.

Run the Python regression suite and bundled end-to-end examples from the
repository root.

```sh
python tools/reproduce.py --out build/reproduce
```

See the release report for installed-package, migration, real-source, MCP,
and macOS isolation results. [Release verification](validation/rfc002/REPORT.md)
· [Lean build and audit](docs/13_LEAN_EXECUTION.md)
· [Architecture and attribution](docs/adr/0001-codegraph-reference.md)
