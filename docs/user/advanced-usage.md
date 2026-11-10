# Advanced usage

> **Status: Current (0.4.x).** Install, workspace, query and release instructions.


For the install command, daily workflow, and MCP setup, start with the [README](../../README.md).

## On this page

- [Installation options](#installation-options)
- [Try the bundled paper](#try-the-bundled-paper)
- [Maintain a workspace](#maintain-a-workspace)
- [Exit codes and script output](#exit-codes-and-script-output)
- [Manage the Obsidian vault and research records](#manage-the-obsidian-vault-and-research-records)
- [Query a workspace from the CLI](#query-a-workspace-from-the-cli)
- [Work with individual papers and older corpora](#work-with-individual-papers-and-older-corpora)
- [Reproduce the checks](#reproduce-the-checks)

> [!TIP]
> Run commands from the workspace root unless a section says otherwise.
> `--workspace PATH` overrides the current directory; `--json` is the
> machine-readable mode for scripts.

## Installation options

The installer selects an executable for your operating system and CPU from
GitHub's latest stable release, or the newest published prerelease when no
stable release exists. It verifies the executable's SHA-256 and version before replacing
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
`PATH`.

> [!NOTE]
> Lean is deferred in 0.4.x. The experimental `lean` command group and Lean
> fixtures are not part of the supported workflow; see
> [the design note](../design/DESIGN.md#10-lean-deferred-not-supported).

## Try the bundled paper

Run this from a checkout with `qec-graph` on `PATH`. The example creates a new
workspace under `build/` for each run.

```sh
mkdir -p build
workspace="$(mktemp -d "$PWD/build/qec-workspace.XXXXXX")"
mkdir -p "$workspace/inputs"
COPYFILE_DISABLE=1 tar -czf "$workspace/inputs/qec-demo.tar.gz" -C examples/paper .

qec-graph init --no-ingest --workspace "$workspace"
qec-graph sync --workspace "$workspace"
qec-graph status --workspace "$workspace"
qec-graph validate --workspace "$workspace"
qec-graph query search HGP --workspace "$workspace" --limit 2
```

The bundled paper produced these outcome lines in a redirected terminal.

```text
[################] init: OK (0/0 packages indexed)
[################] sync: OK (1/1 packages indexed)
[################] status: OK (1/1 packages indexed)
[################] validate: OK
```

The first two search results were the equations `eq:hgp-checks` and
`eq:hgp-commutation`. Their `source` spans locate them in the LaTeX. The
response also identifies the fixed release and reports that more matches
are available. [How to read and reproduce a query](data-and-search.md#read-and-reproduce-a-query-result)

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
entry point and record an explicit upstream version. [Workspace configuration](workspace.md#建库和日常操作)

Quarantine preserves the file, archive blob, and any receipt. Status identifies
the archived content by its hash and lists quarantined inputs separately.
`sync` reads the inbox, while an explicit `rebuild` still checks the entire archive.

Use `qec-graph doctor --json` to diagnose configuration, CURRENT, and inbox
problems without making changes. It reports workspace metadata and counts.
Use `validate` to verify archive and snapshot hashes.
`qec-graph snapshot list` shows the current workspace release and locally stored
registry states, including candidates that may never have been published.
Use `--store` or `--corpus` to list snapshots or states for those scopes.

## Exit codes and script output

Pass `--json` before or after a command to request a detailed workspace
report and versioned CLI errors. Successful JSON reports keep their command
specific fields. Partial workspace operations still return their full report,
including counts and individual failures, and exit with code 2.
`status --json` includes inventory counts and the Obsidian view status for the
selected release. The view is `unknown` if no matching observation is available.
View freshness is reported separately from the package status and exit code.
Use `qec-graph version --json` to read the installed version as JSON.

| Exit code | Meaning |
| --- | --- |
| `0` | Completed successfully |
| `1` | Input, storage, validation, or internal error |
| `2` | A partial operation or a validation report with failures |
| `4` | A required file or an exact query target could not be found |
| `5` | A writer holds the lock or an inbox move would overwrite a file |
| `64` | Invalid command syntax |
| `130` | Interrupted |

For example, `qec-graph --json check-css --hx missing.json --hz hz.json`
reports `envelope_version: 1` and `ok: false`. Its `error` contains `code`,
`message`, `hint`, `details`, `command`, and `scope`. Optional fields can
be `null`. These errors go to stdout so scripts can parse the same stream
on success and failure. `mcp serve` reserves stdout for MCP frames; startup
errors go to stderr. Without `--json`, `query-tool` retains the response from
the read tool. With `--json`, query errors also include the command, hint, and
envelope version; the fixed release or snapshot scope remains attached.
Use `--verbose` to log workspace phases on stderr or `--debug` to see a
traceback for an unexpected CLI failure.
For a damaged workspace configuration or CURRENT pointer, the error gives
its path. Run `qec-graph doctor` for a read-only inspection.

Pass `--verbose` to `mcp serve` or set `QECGRAPH_LOG_LEVEL=DEBUG` in the MCP
server environment to log request frame sizes on stderr. Internal error
diagnostics include a numeric request ID or a short hash of a string ID.
Request text, tool arguments, and source passages stay out of those diagnostics.

Related commands also have grouped names. For example, `workspace sync`,
`query search`, and `mcp serve` use the same options and handlers as `sync`,
`search`, and `serve-mcp`. The `lean` group is experimental/deferred and is
not part of the supported workflow. Use
`qec-graph help mcp serve` for options and an example on a grouped command.
`qec-graph help errors` and `qec-graph help json` describe script output.
The original `review <file>` still works; use `review propose <file>` for the grouped
form. If a review file is named like an action, pass `./filename` to make
the intent clear.

`qec-graph help aliases` lists older names and their replacements. Older
names remain supported and emit a notice on an interactive stderr, or when
`QECGRAPH_DEPRECATIONS=1`. Set `QECGRAPH_DEPRECATIONS=0` to turn notices off.
Common shortcuts such as `sync`, `status`, `validate`, and `search` do not
emit notices.

`--quiet` hides progress and successful reports while keeping failures and
explicit `--json` reports. Use `--color never` to disable color in the summary
or `--color always` to force it. In the default `auto` mode, a nonempty
`NO_COLOR` disables color, and `FORCE_COLOR=1` enables it even in redirected
output. Animation requires an interactive terminal.

## Manage the Obsidian vault and research records

Open the workspace's `human/` directory as an Obsidian vault. Start at
`Index.md`, and keep personal notes in `human/notes/`. Run
`qec-graph human build` to regenerate the vault's derived pages from the
current machine snapshot. [Vault layout and MCP isolation](workspace.md#obsidian-和机器访问隔离)

The category indexes link to readable titles. A record page shows its source,
review and verification status, eligible relations, and an expandable data
section. Open **Release status and legend** from the vault index to see the
fixed release's coverage and what each evidence status means.
**Recent changes** compares that release with the previous rendered release.
The first render establishes a baseline; rerendering the same release keeps
the comparison intact.
[See a generated theorem in Obsidian](../../validation/audit-0.4.0rc1/obsidian-theorem.png)

On the first render after upgrading, old generated page paths become links
to their replacements. Removed entities retain an archived page for existing
links. Personal notes remain in place. If you need to run an older renderer,
restore its generated pages and `.qecgraph/human-*.json` histories from the
same vault backup; the machine database does not require a downgrade.

Use `qec-graph review list` to find proposal IDs and `qec-graph review show PROPOSAL_ID`
to read a provider draft and its recorded decision. Use `qec-graph software import-seed`
to load the bundled software catalog and `qec-graph software coverage` to
inspect its coverage. The workspace guide covers explicit asset registration,
software metadata refresh, and extracting proposals. Use
`qec-graph review import REQUEST_ID response.json` to validate and queue a
provider response as a draft. The reviewer records a decision separately
with `qec-graph extract-review`.
[Research and review workflow](workspace.md#研究查询和审核)

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
[Splitter reference](splitter.md) · [Corpus reference](../operations/corpus.md)

To copy an existing corpus into a new workspace, use
`qec-graph workspace-migrate --corpus /path/to/corpus --workspace /path/to/new-workspace`.
The migration preserves source snapshots, record revisions, and review bindings.
[Migration guide](workspace.md#从旧库迁移)

## Reproduce the checks

For maintainers, a version tag builds standalone executables and checks the
Python wheel and source distribution before publishing GitHub Release assets.
The workflow runs the installer regression on each target and retains the
installed executable and wheel check reports as workflow artifacts.
The separate PyPI workflow accepts an already published tag and checks its
distribution hashes before upload. To enable it, configure the repository's
`pypi` environment with reviewers and register the same environment and
`pypi-publish.yml` with PyPI Trusted Publishing.
[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)

From the repository root, with the Python environment installed, run
`python tools/reproduce.py --out build/reproduce` to run the regression suite
and bundled end-to-end examples. The release report covers installed-package,
migration, real-source, MCP, and macOS isolation checks.
[Release verification](../../validation/README.md)
