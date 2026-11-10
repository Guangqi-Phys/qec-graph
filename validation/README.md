# Validation evidence

Reports describe runs against specific source revisions. For current user and
operations guidance see [the documentation index](../docs/README.md); historical
material is retained in Git history.

> **Lean note:** Lean is deferred in 0.4.x. The Lean fixtures under `validation/p5`
> are experimental regression inputs, not a supported verification claim. The
> database, query and MCP paths do not execute Lean.

| Stage | Source revision | Command | Result |
| --- | --- | --- | --- |
| 0.4.0rc1 audit batch | `3e6f687e199b173a22eeb7e7b89f76148033c84c` | `python -m coverage run -m unittest discover -s tests -v` | 181 passed, 79% branch-aware coverage. [Test log](audit-0.4.0rc1/unittest.log) |
| Third audit batch | `7ea59f0` | `python tools/reproduce.py --out build/reproduce` and a separate branch coverage run | All 14 replay steps and 191 tests passed, with 79.58% branch-aware coverage. Six arXiv sources and 19 installed wheel CLI steps also passed. [Results and distribution hashes](audit-0.4.0rc1/third-batch.json) |
| Fourth audit batch | `bf400f0` | `python -m coverage run -m unittest discover -s tests -v` and `python -m coverage report --fail-under=80` | 204 tests passed on macOS Python 3.13 and Ubuntu Python 3.11 at 80.22% branch-aware coverage on both. [Platform details and distribution verification](audit-0.4.0rc1/fourth-batch.json) |
| Fifth audit batch | `139f4e7` | Coverage, end-to-end and MCP replays, pinned arXiv replay, and installed wheel workspace replay | 211 tests passed on macOS and Linux at 80.32% branch-aware coverage. All 14 end-to-end steps, 22 MCP checks, six arXiv sources, and 11 wheel workspace steps passed. [Commands, platform details, and distribution hashes](audit-0.4.0rc1/fifth-batch.json) |
| Sixth audit batch | `94a84d4` with the recorded test update | Coverage, end-to-end and MCP replays, pinned arXiv replay, and offline source and wheel installs | 219 tests passed on macOS and Linux at 80.50% branch-aware coverage. All 14 end-to-end steps, 22 MCP checks, six arXiv sources, and 16 workspace checks for each install passed. [Commands, platform details, and distribution hashes](audit-0.4.0rc1/sixth-batch.json) |
| Python distributions | Same audit revision | `python -m build --no-isolation`, `python -m twine check --strict dist/*`, `python tools/check_distribution.py dist` | Wheel and sdist matched source metadata and schema bytes. [Artifact hashes](audit-0.4.0rc1/report.json) |
| Installed wheel and standalone | Same audit revision | `tools/reproduce_installed.py`, `tools/reproduce_workspace.py` | 19 installed CLI checks, 11 installed wheel workspace steps, and 21 macOS arm64 standalone steps. The standalone run exercised one arXiv source and migration from 0.3.0. [Run summary](audit-0.4.0rc1/report.json) |
| Read-only MCP | Same audit revision | `python tools/reproduce_mcp.py --out build/reproduce-mcp` | 22 stdio assertions passed. [Check list](audit-0.4.0rc1/report.json) |
| Linux MCP isolation | `839a660` | `python tools/reproduce_linux_isolation.py --out build/linux-isolation.json` | 12 Compose checks passed on Linux arm64 with an alternate local Ubuntu base. [Results](audit-0.4.0rc1/linux-isolation.json) |
| macOS MCP isolation | Same audit revision | `python tools/reproduce_isolation.py --python /path/to/wheel-venv/bin/python --out build/macos-isolation.json` | Six OS checks and a pinned stdio search passed on macOS arm64. [Results](audit-0.4.0rc1/macos-isolation.json) |
| Obsidian reading view | `3d9d91b` | Import an archive of `examples/paper`, run `qec-graph human build`, and open the generated `human/` vault in Obsidian | Eight checks passed in a disposable profile, including index and proof navigation, front matter, source, and status. [Results](audit-0.4.0rc1/obsidian.json) and [screenshot](audit-0.4.0rc1/obsidian-theorem.png) |
| Pinned arXiv corpus | `cdbe50b` | `python tools/reproduce_golden.py --archive-dir ARCHIVES --out build/golden-arxiv.json` | Six archived source versions imported and validated. [Fixture instructions](../tests/golden/README.md) and [results](audit-0.4.0rc1/golden-arxiv.json) |
| Performance baseline | `ad789c0` | `python tools/bench.py --runs 3 --archive-dir ARCHIVES --out build/benchmark.json` | Paired synthetic ingestion and six-source workspace timings. [Samples and environment](audit-0.4.0rc1/benchmark.json) |
| RFC-QEC-002 | `71c7904` | Workspace and macOS isolation replays | [Historical RFC acceptance](rfc002/REPORT.md) |
| P0–P5 and 0.3.0 | Per-run commits where recorded | Python, experimental Lean fixtures, installed CLI, MCP, and incremental replays | [Historical stage reports](REPORT.md) |

The 181-test run used experimental Lean fixtures only for regression. The release checks above used the Python and standalone artifacts built locally on macOS arm64.
The source-bound tests checked provenance and extraction, with no new
mathematical verification claim.

## Historical archive

The 574 historical paths listed in [archive.sha256](archive.sha256) are
available at the fixed commit `3e6f687e199b173a22eeb7e7b89f76148033c84c`.
This checkout keeps stage summaries, linked reports, current results, and
the experimental fixtures required by the Lean regression tests; Lean itself is not part of the supported release.
Detailed logs, duplicate copies, and empty output files remain in Git
history with their original paths and bytes.

From a checkout with that commit available, extract and verify the complete
archive in a separate directory:

```sh
repo=$(pwd)
restore_dir=$(mktemp -d)
git archive 3e6f687e199b173a22eeb7e7b89f76148033c84c validation |
  tar -x -C "$restore_dir"
(cd "$restore_dir" && shasum -a 256 -c "$repo/validation/archive.sha256")
```

In a shallow checkout fetch the fixed commit before extracting it. New
validation runs belong in `build/`. Check in their source revision, command,
environment, result, and the checksums needed to identify external artifacts.
Keep raw bytes in the tree when regression tests or a provenance check
directly require them.
