# QEC Graph documentation

> **Status: Current.** This is the documentation entry point for the 0.4.x release.

Start with the [project README](../README.md) or the [中文快速开始](user/quickstart.zh-CN.md).

| Section | Status | Purpose |
|---|---|---|
| [User guides](user/README.md) | Current | Install, use a workspace, search, read the Obsidian vault, and connect MCP |
| [System design](design/DESIGN.md) | Current | The single authoritative design: data, evidence, publication, query/MCP, human and Lean boundaries |
| [Operations](operations/README.md) | Current | Legacy store/corpus maintenance, corpus/review workflows, audit ledger and validation evidence |

## Current user pages

| Page | Purpose |
|---|---|
| [Quick start (中文)](user/quickstart.zh-CN.md) | Shortest path from an archive to `human/Index.md` and a first query |
| [Advanced usage](user/advanced-usage.md) | Installers, workspace lifecycle, command groups, exit codes, MCP and release checks |
| [Workspace guide](user/workspace.md) | Archive configuration, entry points, Obsidian layout and provider handoff |
| [Data and search](user/data-and-search.md) | `research.v1` records, evidence, fixed releases and CLI/MCP queries |
| [Single-paper splitter](user/splitter.md) | Source spans, fragment layout and LaTeX limitations |

## Design and operations

- [QEC Graph — System Design](design/DESIGN.md) is the only design document.
  Decisions and historical rationale live in Git history and the design's
  decision-record appendix, not in a second set of design pages.
- [Operations index](operations/README.md) covers legacy store/corpus maintenance,
  review, audit remediation and links to executed validation.
- [Validation evidence](../validation/README.md) records inputs, commands and
  source revisions. It is evidence, not a substitute for the design contract.

## Language and status

English is the primary language for the user guides, design, and CLI help. Some
operations pages retain Chinese text; every page states its status at the top.
Only **Current** pages describe the 0.4.x release.

There are no redirect-only or archive pages in the current tree. Every page has
a real body, a status marker, and a place in the navigation above.
