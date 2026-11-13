# Advanced usage

> **Status: Current (0.6.x).** Install, workspace, query and release instructions.

> **English** · [中文](advanced-usage.zh-CN.md)

For the install command, daily workflow, and MCP setup, start with the [README](../../README.md).

## On this page

- [Installation options](#installation-options)
- [Try the bundled paper](#try-the-bundled-paper)
- [Maintain a workspace](#maintain-a-workspace)
- [Exit codes and script output](#exit-codes-and-script-output)
- [Manage the Obsidian vault and research records](#manage-the-obsidian-vault-and-research-records)
- [Query a workspace from the CLI](#query-a-workspace-from-the-cli)
- [Reproduce the checks](#reproduce-the-checks)
- [Progress presentation](#progress-presentation)

> [!TIP]
> Run commands from the workspace root unless a section says otherwise.
> `--workspace PATH` overrides the current directory; `--json` is the
> machine-readable mode for scripts.

## Installation options

The installer selects an executable for your operating system and CPU from
GitHub's latest stable release, or the newest published prerelease when no
stable release exists. It verifies the executable's SHA-256 and version before replacing
`~/.local/bin/qec-graph`. Open a new terminal if it added that directory to
your `PATH`. Linux builds are tested on Ubuntu 22.04 (glibc 2.35) by the release workflow.
[Release assets](https://github.com/Guangqi-Phys/qec-graph/releases/latest)

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
> The experimental Lean commands and fixtures have been removed. See
> [the design note](../design/DESIGN.md#10-lean-integration-removed).

## Try the bundled paper

Run this from a checkout with `qec-graph` on `PATH`. The example creates a new
workspace under `build/` for each run.

```sh
mkdir -p build
workspace="$(mktemp -d "$PWD/build/qec-workspace.XXXXXX")"
mkdir -p "$workspace/inputs"
COPYFILE_DISABLE=1 tar -czf "$workspace/inputs/qec-demo.tar.gz" -C examples/paper .

qec-graph init --workspace "$workspace"
qec-graph sync --workspace "$workspace"
qec-graph status --workspace "$workspace"
qec-graph validate --workspace "$workspace"
qec-graph query search HGP --workspace "$workspace" --limit 2
```

Example outcome lines for the bundled paper (elapsed times vary):

```text
✓ sync: OK  00:02 | 1/1 packages indexed
✓ status: OK  00:00 | 1/1 packages indexed
✓ validate: OK  00:01
```

The first two search results were the equations `eq:hgp-checks` and
`eq:hgp-commutation`. Their `source` spans locate them in the LaTeX. The
response also identifies the fixed release and reports that more matches
are available. [How to read and reproduce a query](data-and-search.md#read-and-reproduce-a-query-result)

Set `[ai].max_parallel_packages` to a small value (for example `2`) to let `sync` prepare multiple packages concurrently. Only AI calls overlap; registry publication and input consumption remain serial.

## Maintain a workspace

Except for `init`, commands find the workspace from the current directory or
its parents. Pass `--workspace /path/to/workspace` to select one explicitly.
`init` uses only the current directory unless `--workspace` is explicit. For the
daily commands `sync`, `status`, and `validate`, `QECGRAPH_WORKSPACE` can serve
as a fallback when the current directory is outside an initialized workspace.

Workspace maintenance commands keep one final outcome line. All business
commands share a live activity panel on stderr when it is a terminal, including
when stdout is redirected. Help and version commands return immediately. Pass
`--json` for the full report in scripts, including when using `--workspace`
or redirecting output. A partial status exits with code 2 in either mode.
Invalid command syntax exits with code 64. Run `qec-graph help <command>`
for command options or `qec-graph --version` for the installed version.

The panel uses a restrained amber accent, a named current phase, and total/phase
elapsed time. A compact matrix fits four microscopic dot rows inside one text
row, up to 12 characters wide. Measured work fills the dots; a subtle amber
shimmer changes brightness without advancing the count. Known totals show an exact completed/total count
and a one-decimal percentage. Each matrix measures its named
phase (packages, bytes, files, notes, or vectors); it is not an estimate of the
whole command's running time. A new phase starts its own count. Unknown work,
including AI/network waits and the isolated human renderer, has no percentage
or invented ETA. Only major-stage results remain in terminal scrollback: package
archiving, source extraction, AI source checks when needed, AI content extraction,
publication and note rendering. Each result keeps its outcome, real counts and
elapsed time. Small steps and their matrices disappear when done; failures and
interruption remain summarized at the major-stage level.

A separate breathing light sits directly beside **AI**. Its small bullet stays
fixed and vertically aligned with the text; only brightness changes. It indicates an active
local request/wait, not knowledge of the provider's internal reasoning or token
progress. Each paper shows its completed task count and current task from
Theorems, Assumptions, Data and Research thoughts. Finished and queued task rows
are hidden. The batch counts successful or reused tasks across all scheduled
papers, including those still queued: two completed tasks in one paper and one
in another show **3/8, 37.5%** immediately. Failed tasks do not increment the count;
finishing a paper does not reset the batch. These counts measure extraction, with
publication reported separately. Tasks run sequentially within each paper;
different papers may run concurrently. Provider/model, attempt, timeout, retry
backoff, reported token counts, validation and cache reuse appear while active.
Use `--verbose` to keep detailed diagnostics. Completed extraction still produces
proposed content, not scientific verification.

| Display option | Behavior |
| --- | --- |
| `--progress auto` | Live panel on terminal stderr; silent redirected stderr (default) |
| `--progress plain` | Append-only major stages and counts, with no animation or ANSI codes |
| `--progress off` | Hide activity, retaining reports and errors |
| `--verbose` | Diagnostic activity log without animation |
| `--quiet` | Hide progress and successful human reports; explicit JSON and errors remain |
| `--color never` / `NO_COLOR=1` | Keep the terminal layout without color |

```sh
qec-graph sync --json --progress plain
qec-graph validate --progress off
qec-graph help progress
```

Narrow terminals shorten labels before dropping the count. Non-Unicode
terminals use ASCII; `TERM=dumb` disables automatic animation. MCP uses plain
service activity rather than an animated panel; its stdout remains JSON-RPC.
The design draws on [Rich progress](https://rich.readthedocs.io/en/latest/progress.html)
and the [Command Line Interface Guidelines](https://clig.dev/#robustness).
The renderer adds no runtime dependency and preserves existing JSON reports.

| Task | Command from the workspace root |
| --- | --- |
| Create the workspace and AI configuration without extracting | `qec-graph init` |
| Inspect the selected AI provider without network access | `qec-graph ai status` |
| Test the configured AI endpoint with one probe | `qec-graph ai test` |
| List AI proposals waiting for review | `qec-graph ai proposals --json` |
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
entry point and record an explicit upstream version. [Workspace configuration](workspace.md#create-and-operate-a-workspace)

Quarantine preserves the file, archive blob, and any receipt. Status identifies
the archived content by its hash and lists quarantined inputs separately.
`sync` reads the inbox, while an explicit `rebuild` still checks the entire archive.

Use `qec-graph doctor --json` to diagnose configuration, CURRENT, and inbox
problems without making changes. It reports workspace metadata and counts.
Use `validate` to verify archive and snapshot hashes.
`qec-graph snapshot list` shows the current workspace release and locally stored
registry states, including candidates that may never have been published.

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

Open the workspace's `human/` directory in Obsidian and browse
`YYYY/MM/Surname_First_Two_thoughts.md`. Each paper has one note containing
nine ThoughtsGraph questions, AI answers and quotations. YAML starts with `tags`,
`link`, `title`, `author`; tags describe the main topics. Filenames use only the
first author's surname; the original arXiv package's `YYMM` sets the folder
(e.g. `2611.12971v2.tar.gz` → `2026/11/`). Run `qec-graph human build`
to regenerate notes from the current machine release without calling AI.

The v0.6.3 layout replaces the v0.6.2 entity-page vault. The first
migration deletes the entire managed old `human/`, including `notes/`, without a
backup. There are no indexes, tombstones or other generated human files. Keep
personal notes elsewhere. Publication/recovery state stays in `.qecgraph/`.
[Layout, missing metadata and migration](workspace.md#obsidian-and-machine-isolation)

Use `qec-graph software import-seed` to load the bundled software catalog and `qec-graph software coverage` to inspect it. [Research queries](workspace.md#research-queries-and-review)

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

## Progress presentation

Activity events live in `core/progress.py`, independent of terminal output. A
context-local subscriber in `cli/progress.py` renders an amber activity panel on
stderr; each AI worker receives its own copied context and nested task identity.
Known phase totals use compact Braille micro-dot cells (four dot rows in one
text row, at most 12 characters wide), completed units and one decimal
of percentage, capped below 100% until every unit finishes. Unknown totals use animation and elapsed
time, never a synthetic percentage or ETA. Separate stages have separate counters;
publication, network waits and the isolated human renderer stay indeterminate.
Only explicitly retained major-stage outcomes are appended above the live region,
with counts and elapsed time. Helpers update transient detail without renaming or
resetting a major stage. Finished/queued subtasks and final matrices are hidden;
failures and interruption remain in the stage summary. Typed step events identify
the currently running AI task. The AI batch denominator covers four tasks per
scheduled paper, including queued packages; successful or reused tasks advance it
once, failures never do. Locked updates keep concurrent counts monotonic, and
completed package contributions survive removal from the live panel.
Each provider request has a separate breathing light next to `AI`, independent
of the dot matrix; a fixed middle bullet keeps its vertical position while
luminance breathes. The light signals local liveness, not model-internal progress.
Provider/model, timeout, attempts, backoff, reported token counts and response
validation remain inspectable. Overflow activity cycles within the viewport;
history retains only major results. Detailed diagnostics are opt-in via `--verbose`.
The CLI starts activity before dispatch for every business command. Reports
clear only the live region before output; completion, errors and interruption
retain final records and stop the refresh worker. Help/version are immediate, and MCP uses plain service
activity. Non-TTY stderr is quiet by default; `--progress plain` provides an
append-only major-stage log. `--progress off` and `--quiet` suppress activity,
including with `--json`. Terminal width, Unicode support and color settings
change presentation only; stdout payloads and exit codes retain their contracts.

Visual reference: [CodeGraph v1.6.2, `shimmer-worker.ts`](https://github.com/colbymchenry/codegraph/blob/6560052a6f856855d3f71eee838fd66ccfa4285d/src/ui/shimmer-worker.ts),
commit `6560052a6f856855d3f71eee838fd66ccfa4285d`,
[MIT, copyright 2026 Colby Mchenry](https://github.com/colbymchenry/codegraph/blob/6560052a6f856855d3f71eee838fd66ccfa4285d/LICENSE).
The installed v1.6.2 glyph and shimmer modules informed the compact density,
amber range (`#a06409`–`#fbbf24`), muted rails and green completion marks. QEC
Graph implements its own Braille fill, brightness animation and persistent
history in Python; the referenced implementation is not vendored.
