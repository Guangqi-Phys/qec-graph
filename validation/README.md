# Validation evidence

Reports describe runs against specific source revisions. For the current audit
status see [the remediation ledger](../docs/AUDIT_REMEDIATION.md).

| Stage | Source revision | Command | Result |
| --- | --- | --- | --- |
| 0.4.0rc1 audit batch | `3e6f687e199b173a22eeb7e7b89f76148033c84c` | `python -m coverage run -m unittest discover -s tests -v` | 181 passed, 79% branch-aware coverage. [Test log](audit-0.4.0rc1/unittest.log) |
| Python distributions | Same audit revision | `python -m build --no-isolation`, `python -m twine check --strict dist/*`, `python tools/check_distribution.py dist` | Wheel and sdist matched source metadata and schema bytes. [Artifact hashes](audit-0.4.0rc1/report.json) |
| Installed wheel and standalone | Same audit revision | `tools/reproduce_installed.py`, `tools/reproduce_workspace.py` | 19 installed CLI checks, 11 installed wheel workspace steps, and 21 macOS arm64 standalone steps. The standalone run exercised one arXiv source and migration from 0.3.0. [Run summary](audit-0.4.0rc1/report.json) |
| Read-only MCP | Same audit revision | `python tools/reproduce_mcp.py --out build/reproduce-mcp` | 22 stdio assertions passed. [Check list](audit-0.4.0rc1/report.json) |
| RFC-QEC-002 | `71c7904` | Workspace and macOS isolation replays | [Historical RFC acceptance](rfc002/REPORT.md) |
| P0–P5 and 0.3.0 | Per-run commits where recorded | Python, Lean, installed CLI, MCP, and incremental replays | [Historical stage reports](REPORT.md) |

The 181-test run used existing Lean evidence fixtures. The release checks
above used the Python and standalone artifacts built locally on macOS arm64.
The source-bound tests checked provenance and extraction, with no new
mathematical verification claim.
