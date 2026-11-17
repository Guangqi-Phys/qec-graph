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
| Offline preparation | `prepare_compiled.py`, `reproduce_preparation.py`, `report_preparation.py`, `prepare_arxiv.py` | Compile-first source material and fixed-corpus replay; retain the static compatibility tool |

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
```

After original compilation, supported invalid UTF-8 bytes can pass a reversible
spelling and an additional native/PDF-text check; retain `source-projection.json`,
`projected-sources/` and original byte locators. A pinned native Harvmac adapter
keeps the source dialect while writing the common syntax/bibliography JSON.
`manifest.preparation_capabilities` separates body, bibliography and cross-reference
completeness without promoting overall partial material. `--support-dir` searches
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

The following retained static interface is independent and is never an automatic
fallback from the compile-first route.

`tools/prepare_arxiv.py` recognizes a LaTeX entry by content, assembles literal includes into `entry.tex`, and writes the `document/2` model with section levels, block text and source spans. By default it does not call AI. It never runs TeX or requires a compilable project.

```bash
python tools/prepare_arxiv.py /path/to/source-tree \
  --entry main.tex --out build/prepared/paper --json
```

For failed/partial input, use a configuration explicitly enabling AI and source upload:

```sh
python tools/prepare_arxiv.py /path/to/source-tree \
  --out build/prepared/paper --json \
  --ai-prepare --ai-config-root /path/to/config-directory
```

Literal grammar adapters run locally first; complete local inputs skip AI. The `prepare_input` v9 skill returns only entry,
encoding and syntax plans. The program converts a derived copy, then the independent
downstream parser validates it. AI never classifies theorems/proofs or extracts
scientific content. Failed candidates retain the previous output.
`normalization.json` retains original bytes, hashes, changes and projections;
source coordinates explicitly identify the derived layer. Existing `document.json`
comes from downstream validation. `--ai-structure` is a deprecated alias.
Budgets, timeouts and validated-response caching use the selected configuration.
`--ai-reasoning-effort low` optionally overrides reasoning for this tool only;
OpenAI-compatible provider tables may also set `reasoning_effort`. The default
remains the provider default, and distinct settings have separate response caches.
For the OpenRouter wire format see its [reasoning documentation](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).
This tool does not publish a workspace release.

`--no-parser-recovery` and `--no-transparent-containers` disable the opt-in partial-structure fallbacks. Exit `0` means `document_complete`; `2` means content is complete but structure is partial, or content remains unresolved.

The output directory is managed as a unit: artifacts are staged and published through a journaled backup, so a normal failure leaves the previous complete artifacts in place. An existing directory without a prepare manifest is refused; pass `--overwrite` to replace it whole, including unrelated files. If the process is killed between the two directory renames, the target path is absent until the next write or `--recover` restores the journaled previous result and removes staged leftovers. Recovery compares the target manifest and every journaled artifact digest with the recorded versions; a directory recreated by someone else, or one with the right manifest but missing or altered artifacts, is reported as a conflict (exit `1`) and the backup and journal are kept:

```bash
python tools/prepare_arxiv.py --out build/prepared/paper --recover
```
