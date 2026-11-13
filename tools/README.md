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
| Offline preparation | `prepare_arxiv.py` | Recognize an entry, assemble literal includes and write the `document/2` model; no AI or TeX execution |

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

`tools/prepare_arxiv.py` recognizes a LaTeX entry by content, assembles literal includes into `entry.tex`, and writes the `document/2` model with section levels, block text and source spans. It does not call AI, run TeX, or require a compilable project.

```bash
python tools/prepare_arxiv.py /path/to/source-tree \
  --entry main.tex --out build/prepared/paper --json
```

`--no-parser-recovery` and `--no-transparent-containers` disable the opt-in partial-structure fallbacks. Exit `0` means `document_complete`; `2` means content is complete but structure is partial, or content remains unresolved.

The output directory is managed as a unit: a failed write leaves the previous complete artifacts untouched, and an existing directory without a prepare manifest is refused. Pass `--overwrite` to replace such a directory deliberately; it is replaced whole, including unrelated files.
