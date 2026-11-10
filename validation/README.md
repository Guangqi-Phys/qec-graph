# Validation evidence

> **Status: Current (0.6.x).** This is an index of executable checks, not a
> historical run archive.

> **English** · [中文](README.zh-CN.md)

Historical run artifacts are not shipped. Earlier release evidence remains in
Git history; this tree intentionally keeps only the current index so stale
reports cannot be mistaken for a claim about the current code.

## Current checks

| Check | Command |
|---|---|
| Unit, integration and contract tests | `python -m unittest discover -s tests` |
| End-to-end extraction and query reproduction | `python tools/reproduce.py --out build/reproduce` |
| Workspace, MCP and isolation checks | `python tools/reproduce_workspace.py` and `python tools/reproduce_mcp.py` |
| Release distributions | `python -m build` then `python tools/check_distribution.py dist/` |
| Release binaries | The `Standalone Release` GitHub workflow |
| AI configuration and provider probe | `qec-graph ai status` and `qec-graph ai test` |
| AI proposals | `qec-graph ai proposals --json` |

A check is evidence only for the exact source revision and environment in which
it ran. A passing test does not make a paper's theorem true, a distance bound
mathematically verified, or a Lean declaration semantically matched.

## Adding evidence

Attach new logs or reports to the release/CI run that produced them, or add a
new versioned directory only while that version is current. Do not copy old
reports forward or edit a recorded result to match newer code.
