# Advanced usage

For the install command, daily workflow, and MCP setup, start with the [README](../README.md).

## Installation options

The installer selects an executable for your operating system and CPU from
GitHub's latest stable release, or the newest published prerelease when no
stable release exists. It verifies the executable's SHA-256 before replacing
`~/.local/bin/qec-graph`. Open a new terminal if it added that directory to
your `PATH`. The `v0.4.0rc1` Linux builds were tested on Ubuntu 22.04 (glibc 2.35).
[Release assets](https://github.com/Guangqi-Phys/qec-graph/releases/tag/v0.4.0rc1)

To install from a checkout, use Python 3.11 or newer, SQLite with FTS5, and a
local POSIX filesystem.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

For a local wheel, pass its path to `python -m pip install` instead. Local
ingestion and queries run without an API key.

To build a single-file executable, run this on the target operating system
and CPU. On Linux, install `binutils` and build on the oldest glibc-based
distribution you intend to support.

```sh
python3.13 -m venv build/standalone-venv
build/standalone-venv/bin/python -m pip install . 'PyInstaller==6.22.3'
PYINSTALLER_CONFIG_DIR="$PWD/build/standalone-cache" \
  build/standalone-venv/bin/python -m PyInstaller --noconfirm \
  --distpath dist/standalone --workpath build/standalone tools/qec-graph.spec
```

Run `dist/standalone/qec-graph` directly or install it in a user directory on
`PATH`. Explicit Lean builds require the project's Lean toolchain.
[Lean guide](05_LEAN.md)

## Try the bundled paper

Run this from a checkout with `qec-graph` on `PATH`. The example creates a new
workspace under `build/` for each run.

```sh
mkdir -p build
workspace="$(mktemp -d "$PWD/build/qec-workspace.XXXXXX")"
mkdir -p "$workspace/inputs"
COPYFILE_DISABLE=1 tar -czf "$workspace/inputs/qec-demo.tar.gz" -C examples/paper .

qec-graph init --workspace "$workspace"
qec-graph status --workspace "$workspace"
qec-graph validate --workspace "$workspace"
```

## Maintain a workspace

Commands find the workspace from the current directory or its parents. Pass
`--workspace /path/to/workspace` to select one explicitly. For the daily
commands `sync`, `status`, and `validate`, `QECGRAPH_WORKSPACE` can serve as a
fallback when the current directory is outside an initialized workspace.

Workspace maintenance commands print one outcome line by default. In a
terminal, longer operations also show their progress on that line. Pass
`--json` for the full report in scripts, including when using `--workspace`
or redirecting output. A partial status exits with code 2 in either mode.
Invalid command syntax exits with code 64. Run `qec-graph help <command>`
for command options or `qec-graph --version` for the installed version.

| Task | Command from the workspace root |
| --- | --- |
| Initialize the workspace and leave pending packages in the inbox | `qec-graph init --no-ingest` |
| Preview pending inputs | `qec-graph sync --dry-run` |
| Import and keep the inbox copies | `qec-graph sync --keep-inputs` |
| Inspect package and failure details | `qec-graph status --json` |
| List pending and quarantined files | `qec-graph inputs list` |
| Set aside a failed package | `qec-graph inputs quarantine broken.zip` |
| Return a package to the inbox | `qec-graph inputs restore broken.zip` |
| Recheck the entire archive and regenerate the derived workspace | `qec-graph rebuild` |
| Import the inbox first, then rebuild from the archive | `qec-graph rebuild --include-inputs` |
| Import or rebuild without generating Obsidian pages | `qec-graph sync --no-human` or `qec-graph rebuild --no-human` |

Successful imports clear the inbox copy after archiving, validation, and
publication. Failed packages remain available for retry, and a partial batch
returns exit code `2`. Use `status --json` to find an ambiguous source tree
and its entry-point candidates. The workspace guide shows how to pin the
entry point and record an explicit upstream version. [Workspace configuration](rfc-002/WORKSPACE.md#建库和日常操作)

Quarantine preserves the file, archive blob, and any receipt. Status identifies
the archived content by its hash and lists quarantined inputs separately.
`sync` reads the inbox, while an explicit `rebuild` still checks the entire archive.

Use `qec-graph doctor --json` to diagnose configuration, CURRENT, and inbox
problems without making changes. It reports workspace metadata and counts.
Use `validate` to verify archive and snapshot hashes.
`qec-graph snapshot list` shows the current workspace release and locally stored
registry states, including candidates that may never have been published.
Use `--store` or `--corpus` to list snapshots or states for those scopes.

## Manage the Obsidian vault and research records

Open the workspace's `human/` directory as an Obsidian vault. Start at
`Index.md`, and keep personal notes in `human/notes/`. Run
`qec-graph human build` to regenerate the vault's derived pages from the
current machine snapshot. [Vault layout and MCP isolation](rfc-002/WORKSPACE.md#obsidian-和机器访问隔离)

Use `qec-graph review list` to inspect proposals, `qec-graph software import-seed`
to load the bundled software catalog, and `qec-graph software coverage` to
inspect its coverage. The workspace guide covers explicit asset registration,
software metadata refresh, and submitting and reviewing extraction proposals.
[Research and review workflow](rfc-002/WORKSPACE.md#研究查询和审核)

## Query a workspace from the CLI

```sh
qec-graph search 'hypergraph product' --workspace "$workspace" --limit 10
qec-graph show "$identifier" --workspace "$workspace"
qec-graph context "$identifier" --workspace "$workspace" --depth 2
```

Use an exact result ID for `show` and `context`. `deps` and `impact` traverse
registered graph dependencies. Pass `--release` to pin the query to a particular
workspace release. These commands return the same JSON envelope and evidence
scope as the workspace MCP tools.

## Work with individual papers and older corpora

Run these examples from the repository root. The commands write to the paths
you specify under `build/`.

```sh
qec-graph split examples/paper/main.tex --project-id qec-demo --out build/split
qec-graph ingest examples/paper/main.tex --project-id qec-demo --out build/graph \
  --annotations examples/annotations.example.json
qec-graph validate --store build/graph
qec-graph context thm:hgp-length --store build/graph
```

A Python installation also provides `qec-latex-split`. The `qecgraph` and
`python -m qecgraph` entry points use the same main CLI as `qec-graph`.
[Splitter reference](03_SPLITTER.md) · [Corpus reference](09_CORPUS.md)

To copy an existing corpus into a new workspace, use
`qec-graph workspace-migrate --corpus /path/to/corpus --workspace /path/to/new-workspace`.
The migration preserves source snapshots, record revisions, and review bindings.
[Migration guide](rfc-002/WORKSPACE.md#从旧库迁移)

## Reproduce the checks

For maintainers, a version tag builds standalone executables and checks the
Python wheel and source distribution before publishing GitHub Release assets.
The separate PyPI workflow accepts an already published tag and checks its
distribution hashes before upload. To enable it, configure the repository's
`pypi` environment with reviewers and register the same environment and
`pypi-publish.yml` with PyPI Trusted Publishing.
[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)

From the repository root, with the Python environment installed, run
`python tools/reproduce.py --out build/reproduce` to run the regression suite
and bundled end-to-end examples. The release report covers installed-package,
migration, real-source, MCP, and macOS isolation checks.
[Release verification](../validation/rfc002/REPORT.md)
