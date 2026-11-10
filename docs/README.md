# QEC Graph documentation

> **Status: Current (0.4.x).** This is the single documentation entry point.

> [!TIP]
> New here? Start with the [Chinese quick start](user/quickstart.zh-CN.md) for
> a five-minute run, or [Advanced usage](user/advanced-usage.md) for the full
> command reference. Agents should read this page and then
> [the system design](design/DESIGN.md).

## Choose your path

```mermaid
flowchart TD
    A[What do you want to do?] --> B[Import a paper]
    A --> C[Query sources and records]
    A --> D[Run or operate a workspace]
    A --> E[Understand the design]
    B --> B1[Quick start]
    C --> C1[Data and search]
    D --> D1[Workspace guide]
    D --> D2[Advanced usage]
    E --> E1[System design]
```

| I am… | Start here | Why |
|---|---|---|
| A new user | [中文快速开始](user/quickstart.zh-CN.md) | Shortest path from archive to first query |
| Importing or maintaining a workspace | [Workspace guide](user/workspace.md) | Archive configuration, entry points, Obsidian and provider handoff |
| Querying records or sources | [Data and search](user/data-and-search.md) | Record types, evidence policy and CLI/MCP queries |
| Running commands | [Advanced usage](user/advanced-usage.md) | Install, exit codes, grouped commands and release checks |
| Working on the splitter | [Single-paper splitter](user/splitter.md) | Source spans, fragment layout and LaTeX limits |
| An agent or contributor | [System design](design/DESIGN.md) | Authoritative architecture, data, publication and boundaries |
| Operating a legacy corpus | [Operations](operations/README.md) | Corpus/review maintenance and validation pointers |

## On this page

- [Choose your path](#choose-your-path)
- [Current user pages](#current-user-pages)
- [Design and operations](#design-and-operations)
- [Page types](#page-types)
- [Language and status](#language-and-status)

## Current user pages

| Page | Language | Type | Use when |
|---|---|---|---|
| [Quick start](user/quickstart.zh-CN.md) | 中文 | Tutorial | You want the shortest working example |
| [Advanced usage](user/advanced-usage.md) | English | How-to / reference | You need installers, command groups, exit codes or release checks |
| [Workspace guide](user/workspace.md) | 中文 | How-to | You need archive configuration, Obsidian layout or provider handoff |
| [Data and search](user/data-and-search.md) | English | Reference | You need `research.v1` records, evidence and query semantics |
| [Single-paper splitter](user/splitter.md) | 中文 | Reference | You need source spans, fragment layout or LaTeX limitations |

## Design and operations

| Page | Status | Type | What it covers |
|---|---|---|---|
| [QEC Graph — System Design](design/DESIGN.md) | Current | Explanation / reference | The only design document: architecture, data/evidence, workspace publication, CLI/MCP, human view and deferred Lean |
| [Operations](operations/README.md) | Current | How-to / reference | Legacy store/corpus maintenance, corpus/review workflows and validation pointers |
| [Validation evidence](../validation/README.md) | Evidence | Evidence | Recorded inputs, commands, revisions and results; not a design contract |
| [Changelog](../CHANGELOG.md) | Current | Reference | Compatibility and behavior changes |

## Page types

Pages follow the four documentation needs from [Diátaxis](https://diataxis.fr/):
**tutorial** (learning), **how-to** (a task), **reference** (facts) and
**explanation** (why). A page has one primary type; a guide may also contain a
reference table.

## Language and status

Current pages are deliberately bilingual: the quick start, workspace and
splitter guides are Chinese; advanced usage, data/search and design are English.
Each page declares its status at the top. **Only Current pages describe 0.4.x.**

There are no redirect-only or archive pages. Superseded material lives in Git
history, not in a second documentation tree.
