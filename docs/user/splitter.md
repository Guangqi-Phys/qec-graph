# LaTeX splitter: implemented API and commands

> **Status: Current (0.4.x).** Source-only splitter reference and limitations.

> **English** · [中文](splitter.zh-CN.md)

The splitter uses the same `parser → graph → store` pipeline as the rest of the
package. It reads a LaTeX project and saves chapters, definitions, lemmas,
theorems, proofs, equations, tables, figures and body paragraphs as files with
provenance, returning the count and exact path for each kind.

The actual split result is the snapshot's `nodes/<kind>/*.tex` plus the matching
`.json` records. There is no second independent parser and no extra fragment
directory that loses provenance. Original files always remain in the same
snapshot's `sources/`.

## On this page

- [1. Install and command entry points](#1-install-and-command-entry-points)
- [2. Where are the output files?](#2-where-are-the-output-files)
- [3. Python API](#3-python-api)
- [4. Custom LaTeX environments](#4-custom-latex-environments)
- [5. Query the graph after splitting](#5-query-the-graph-after-splitting)
- [6. Exact meaning of a fragment](#6-exact-meaning-of-a-fragment)
- [7. Snapshots, repeat runs and exit codes](#7-snapshots-repeat-runs-and-exit-codes)
- [8. Verification of this implementation](#8-verification-of-this-implementation)

> [!NOTE]
> Fragments may nest or overlap and are not guaranteed to compile on their own.
> The original is always the bytes in `sources/`; do not reconstruct a file by
> concatenating fragments.

## 1. Install and command entry points

Python 3.11+ is required. Current runtime dependencies are
`pylatexenc==2.10` and `jsonschema==4.26.0`. Install from the project root:

```bash
python3 -m pip install -e .
```

The package is `qec-graph`; use `qec-graph --version` to see the installed
version. The Python install provides four entry points:

| Command | Purpose |
|---|---|
| `qecgraph` | Full command entry: split, ingest, search, show, deps, impact, context, validate |
| `qec-graph` | Alias for `qecgraph` |
| `qec-latex-split` | Splitter-only entry; same arguments as `qecgraph split` |
| `qecgraph-mcp` | Start the read-only MCP stdio server |

Run the bundled multi-file QEC example:

```bash
qecgraph split examples/paper/main.tex \
  --project-id qec-demo \
  --out work/qec-demo
```

The fully equivalent splitter entry is:

```bash
qec-latex-split examples/paper/main.tex \
  --project-id qec-demo \
  --out work/qec-demo
```

From an installed source checkout, the module entry points also work:

```bash
python3 -m qecgraph split examples/paper/main.tex \
  --project-id qec-demo \
  --out work/qec-demo

python3 -m qecgraph.splitter examples/paper/main.tex \
  --project-id qec-demo \
  --out work/qec-demo
```

`--project-id` is the stable namespace you choose for this paper project.
`--out` should be a new directory, an empty directory, or an existing store
created by this tool. The splitter refuses to write into an unrecognised
non-empty directory, so it never takes over files owned by another tool or a
human.

Optional arguments:

| Argument | Meaning |
|---|---|
| `--project-root DIR` | Restrict the project root; defaults to the entry file's directory |
| `--config FILE` | JSON parser configuration, such as custom environment mappings |
| `--strict` | Put a partial extraction in staging and do not update CURRENT; exit code is still 2 |
| `--force` | Allow publishing a source-only snapshot when the current snapshot has annotations or a catalog |

`split` is source-only and does not accept `--annotations` or `--catalog`. Use
the full `ingest` command when you need to merge human annotations or existing
data records.

## 2. Where are the output files?

The command returns JSON on stdout. Relative to the `snapshot` value in the
result, you can find:

| Path relative to the snapshot | Contents |
|---|---|
| `sources/` | UTF-8 LaTeX sources preserving original bytes and relative paths |
| `assets/` | Images, bibliographies and other resources explicitly referenced and resolved from the source |
| `nodes/definition/` | Definition `.tex` fragments and `.json` records |
| `nodes/lemma/` | Lemma fragments and records |
| `nodes/theorem/` | Theorem fragments and records |
| `nodes/proof/` | Proof fragments and records |
| `nodes/equation/` | Equation fragments and records |
| `nodes/table/`, `nodes/figure/` | Table and figure environment fragments and records |
| `nodes/section/`, `nodes/paragraph/`, etc. | Other recognised semantic blocks |
| `graph.json`, `graph.sqlite` | The same complete graph and its queryable projection |
| `sourcegraph.json`, `datagraph.json`, `lemmagraph.json` | Three views generated from the complete graph |
| `report.json` | Diagnostics, counts and relations awaiting review |
| `manifest.json` | Input fingerprint, output inventory and file hashes |

The key result fields are:

```text
snapshot                         准确的不可变快照目录
snapshot_id                      来源、配置和工具版本所确定的指纹
extraction_status                完整处理受支持语法，或 partial
fragment_count                   所有实际 .tex 片段的总数
fragments_by_kind.<kind>.count    某类片段的数量
fragments_by_kind.<kind>.directory
                                  该类片段目录的绝对路径
fragments_by_kind.<kind>.fragments[]
                                  每个片段的 ID、标签、标题和文件路径
sources[]                        原文件相对路径、SHA-256 和归档路径
paths                            各种图、数据库、报告和清单的准确路径
diagnostics                      未展开结构、缺失文件等处理信息
suggested_exit_code              API 使用者可采用的退出码
```

Each `fragments[]` item contains:

- `tex_file`, `record_file`: absolute paths that can be opened on this machine.
- `fragment_path`, `record_path`: portable paths relative to `snapshot`.
- `source`: original file path, original file hash, character range and line number.
- `content_sha256`: hash of the fragment content.

Do not guess file names. Fragment file names are determined by node IDs; use
the result JSON, a label query or the node record.

## 3. Python API

```python
from qecgraph import split_project

result = split_project(
    entry="examples/paper/main.tex",
    project_id="qec-demo",
    out="work/qec-demo",
)

print(result["snapshot"])
for kind, category in result["fragments_by_kind"].items():
    print(kind, category["count"], category["directory"])
    for fragment in category["fragments"]:
        print(fragment["labels"], fragment["tex_file"])

if result["extraction_status"] == "partial":
    # 已保存能可靠抽取的部分；检查诊断后再决定如何处理。
    print(result["diagnostics"])
```

The function signature is:

```python
split_project(
    entry,
    project_id,
    out,
    project_root=None,
    config_path=None,
    *,
    force=False,
) -> dict
```

The returned object can be passed directly to `json.dumps(...)`. The API raises
on fatal path, configuration or write errors; it may return a `partial` snapshot
when source parsing issues can be recorded.

## 4. Custom LaTeX environments

The tool recognises common `\newtheorem` declarations. You may also provide an
explicit mapping, for example `parser.json`:

```json
{
  "environment_map": {
    "result": "theorem",
    "claim": "lemma",
    "dfn": "definition"
  }
}
```

Then run:

```bash
qecgraph split path/to/main.tex \
  --project-id my-paper \
  --project-root path/to \
  --config parser.json \
  --out work/my-paper
```

The mapping says which directory a source environment should enter; it does not
prove its mathematical content. Reading `n=13,k=1,d=3` from a table does not
automatically create a verified code instance.

## 5. Query the graph after splitting

Splitting already produces a standard graph store; there is no second import:

```bash
qecgraph show lem:css-commutation --store work/qec-demo
qecgraph deps thm:hgp-css --store work/qec-demo
qecgraph context thm:hgp-length --store work/qec-demo
qecgraph validate --store work/qec-demo
```

Plain `ref` stays a citation relation; `uses` is an author-declared dependency;
a proof association inferred only from proximity stays a candidate; `leanok`
stays an author annotation. Splitting never raises the evidence level of these
relations.

## 6. Exact meaning of a fragment

This extracts source blocks by semantic structure:

- A theorem fragment may contain an equation environment, while the equation
  also has its own fragment.
- Fragments can therefore nest and overlap; concatenating every `.tex` file
  repeats content.
- A section node stores the section title and adjacent labels and links section
  content through structural edges; a cross-file section never fabricates a
  contiguous source range.
- A fragment may depend on macros, packages and context from the preamble and is
  not guaranteed to compile alone.
- Use `sources/` to recover the `.tex` files that were read; use fragments for
  locating, searching, reviewing and building AI context.

The current snapshot does not automatically collect unread `.tex` files, local
`.sty/.cls` files, inputs generated by dynamic macros or unresolved resources.
It is not a complete compilation archive for an arbitrary LaTeX project. Keep
the complete original project separately; the archived `sources/` and `assets/`
are enough to inspect what was actually extracted but not to guarantee rebuilding
the original PDF.

Source character positions count Unicode codepoints after UTF-8 decoding; the
range is `[char_start, char_end)` and line numbers start at 1. File SHA-256 is
computed over the original bytes, preserving details such as CRLF.

The parser recognises zero-argument environment aliases declared directly by
`\newcommand`, such as `\be` for `\begin{equation}`, and preserves the original
form in the fragment. For `\iftrue`, `\iffalse` and `\ifdefined` where a prior
declaration proves the macro is defined, it selects the decidable branch and
records a diagnostic. Included files may use those declarations visible at the
call site.

The parser does not run TeX or Lean and does not expand arbitrary user macros.
Conditions it cannot decide statically, repeated includes, include cycles,
missing resources and unsupported configuration become diagnostics. A
`complete_for_supported_syntax` status only means supported syntax was handled.

## 7. Snapshots, repeat runs and exit codes

Running again with the same project ID, source files, configuration, dependency
versions and tool source reuses the same snapshot. Original files and existing
snapshot fragments remain unchanged; changed inputs or tool versions produce a
new snapshot.

`CURRENT.json` points to the current snapshot. If the current snapshot has
annotations or a catalog, `split` reports an error. Use a separate `--out` for
split results, or pass `--force` to publish a source-only snapshot explicitly.
When replacing explicitly, the report includes the old `previous_snapshot_id`
and the new `snapshot_id`; the old snapshot remains queryable by ID.

| Exit code | Meaning |
|---|---|
| `0` | A complete snapshot for supported syntax was created or reused; warnings may still exist |
| `1` | A path, configuration, output-directory or other unrecoverable error; stderr has the error JSON |
| `2` | A partial snapshot was saved; stdout has the result and diagnostics; inspect `extraction_status` |

Argument-usage errors exit `64`; in that case stderr shows
usage and no split-result JSON is produced. Automation can distinguish the two
cases by whether stdout has a result and by `extraction_status`.

A partial result means usable parts were saved, not that the run was rolled
back. For example, if a lemma was extracted correctly but a later `input` file
is missing, the output still contains the lemma and its exact source, and
records the missing file explicitly.

Edit local sources or human annotations and generate a new snapshot. Editing
fragments inside a snapshot makes later hash verification fail.

## 8. Verification of this implementation

`tests/integration/pipeline/test_splitter.py` covers classified fragments, source bytes, graph
queries, repeat imports, write boundaries, partial-extraction exit codes, parity
of the two entry points and environment configuration.

Run only this group:

```bash
python3 -m unittest discover -s tests -p test_splitter.py -v
```

These checks verify files, provenance and interface behaviour. They do not
execute a mathematical proof, numerical code-distance verification, LaTeX
compilation or a Lean build.
