# Repository tools

> **English** · [中文](README.zh-CN.md)

Helper scripts run from the repository root. They are development/release
tooling, not part of the installed `qecgraph` package.

| Group | Scripts | Purpose |
|---|---|---|
| Reproduction | `reproduce.py`, `reproduce_workspace.py`, `reproduce_mcp.py`, `reproduce_golden.py`, `reproduce_incremental.py`, `reproduce_installed.py` | End-to-end regressions for the core, workspace, MCP, pinned sources, incremental mode and installed package |
| Isolation | `reproduce_isolation.py`, `reproduce_linux_isolation.py`, `mcp_isolated_macos.py` | OS-level MCP isolation checks |
| Release | `check_distribution.py`, `qec-graph.spec` | Distribution metadata checks and PyInstaller spec |
| Performance | `bench.py` | Generated incremental workload and pinned-source benchmark |
| Knowledge evidence | `reproduce_knowledge.py` | Compare complete reading, source search and task context; no LLM execution |
| Offline preparation and extraction | `prepare_compiled.py`, `reproduce_preparation.py`, `report_preparation.py`, `compare_preparation.py`, `extract_prepared.py` | Native compilation, fixed-corpus replay and verified extraction |

The standard gates are:

```sh
python tools/reproduce.py --out build/reproduce
python tools/check_distribution.py dist
```

`tools/reproduce_*` scripts write machine-readable reports to `build/`;
`validation/` indexes the current executable checks.

Run the offline evidence comparison, or use a read-only registered machine release:

```sh
python tools/reproduce_knowledge.py --out build/knowledge-synthetic.json --include-payloads
python tools/reproduce_knowledge.py --machine /path/to/machine --out build/knowledge-real.json --include-payloads
```

`--release` pins an older release. `--cases` accepts a JSON list with `name`,
`query`, `kind`, `purpose`, `source_version_id` and `expected_evidence` (exact
passage strings). Without cases, existing sources supply mechanical probes;
these are not curated scientific questions. Reports disclose retrieval coverage
and fallback. `--include-payloads` retains the exact tool responses locally;
omit it to save only hashes and measurements. A/B/C measure evidence retrieval,
not model answer accuracy or mathematical correctness.

## Offline preparation

Use `prepare_compiled.py` for the new preparation workflow. It compiles original
source in a local sandbox, then converts it into source-mapped TeX syntax JSON,
retaining formulas, authored structure, table cells/spans, figures/assets, footnotes,
literal BIB and emitted AUX/BBL/BCF citation bindings. It never calls AI or performs
scientific extraction. See [the material contract](../docs/design/DESIGN.md#54-offline-source-preparation).

```sh
python tools/prepare_compiled.py /path/to/source-tree --entry main.tex --out build/material/paper
python tools/prepare_compiled.py --out build/material/paper --check
python tools/prepare_compiled.py /path/to/source-tree --entry main.tex \
  --support-dir /path/to/pinned-dependencies --out build/material/paper
python tools/reproduce_preparation.py --manifest test-sources/arxiv-sources/manifest.json --out build/material-replay
python tools/report_preparation.py --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/material-replay --out build/preparation-acceptance.json
python tools/report_preparation.py --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/material-replay --out build/preparation-acceptance.json --check
python tools/compare_preparation.py --baseline build/material-baseline \
  --current build/preparation-refactor/final-verified --out build/preparation-comparison.json
```

After original compilation, supported invalid UTF-8 bytes can pass a reversible
spelling and an additional native/PDF-text check; retain `source-projection.json`,
`projected-sources/` and original byte locators. A pinned native Harvmac adapter
keeps the source dialect while writing the common syntax/bibliography JSON.
`manifest.preparation_capabilities` separates body, bibliography, reference preparation
and unique bindings. Preserved cross-reference ambiguity passes preparation;
`status=ambiguous` and all candidates remain, unique bindings stay partial, and missing
targets still block ready. `--support-dir` searches
author package files, explicit support, then system files; changed supplied
dependencies fail the build. Pin support contents and retain their hashes.

`--engine` selects a local engine; repeat `--support-dir` for explicit, hashed
support files. There are no dependency downloads or system TeX changes. Exit 0
means ready, 2 means explicit partial material, and 1 means an input/configuration
or publication failure. A partial retry retains a ready output and writes `.attempt`.
`--check` verifies artifacts and exact original spans without rebuilding. macOS
uses sandbox-exec; Linux requires bubblewrap. Unsupported isolation never falls
back to unrestricted TeX. `report_preparation.py` reopens every archived bundle and
recalculates counts and source probes; stale code/corpus hashes, missing inputs or
summary/material disagreement are rejected. Pass the same `--cases` used by the
replay. `--baseline-revision <commit>` pins the comparison and
`--machine-evaluation <json>` attaches separate success/failure evidence. `--check`
does not compile, modify the report or call a model. The handoff is `qecgraph.prepare/3` with `content.json`,
not a research record or workspace snapshot; arbitrary macro expansion is unavailable.

The workflow exports `normalized.tex` and `normalized-map.json`, then recompiles
the derived copy with the same engine/support files. Supported surface rewrites
normalize math delimiters outside macro/group arguments and expand uniquely declared,
runtime-bound citation wrappers. Consumed classic BBL is inlined for standard
article/report/book classes; RevTeX deferred bibliography/notes and Biblatex retain
their external calls and payloads. Unknown macros, author classes and assets remain.
`normalization.json` separately reports syntax, recompilation and optional per-page
non-whitespace PDF-text equality via pdftotext. A detected mismatch keeps the material
partial; text equality is not a pixel or mathematical-equivalence claim.
`content.json` coordinates address `entry.tex`; use the verified normalized mapping
before locating a derived passage in original source. `--check` never recompiles.

Interrupted publication can be recovered by the next write or explicitly.

```sh
python tools/prepare_compiled.py --out build/material/paper --recover
```

The publisher checks the journaled manifest and artifact hashes. A conflict keeps
the recovery evidence and returns exit 1. Use the verified bundle for extraction.

```sh
python tools/extract_prepared.py build/material/paper --out build/extracted/paper.json
```

For refactors, `compare_preparation.py` independently reopens both retained corpus
replays and compares stable source/syntax/reference/mapping payloads, diagnostics,
capabilities and outcomes. It excludes volatile native logs/PDF bytes and verified
build/projection report hashes, and lists these limits in its output. It returns 2
for differences and never recompiles or calls a model.
