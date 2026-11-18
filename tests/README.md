# Test layout

> **English** · [中文](README.zh-CN.md)

Tests use the standard library `unittest` runner and do not require a separate
test dependency. The tree has three layers, with functional subdirectories
inside each layer.

```text
tests/
├── unit/          # pure parsing, graph/domain rules, schema checks
├── integration/   # store, workspace, MCP, CLI, rendering
├── contracts/     # docs, packaging, architecture and tooling contracts
├── fixtures/      # shared input fixtures
├── golden/        # pinned arXiv manifest and instructions
└── support.py     # shared root/fixture paths
```

| Layer | Functional group | Files | Focus |
|---|---|---|---|
| Unit | Parsing | `unit/parsing/` | TeX, archive safety, source coordinates and preparation syntax |
| Unit | Domain and AI | `unit/domain/` | Research evidence, schemas, provider and extraction behavior |
| Unit | Search and rendering | `unit/query/`, `unit/rendering/` | Lexical ranking, progress and output |
| Integration | Pipeline | `integration/pipeline/` | Snapshot publication, native compilation, sandbox, material and prepared extraction |
| Integration | Workspace | `integration/workspace/` | Registry, archive ingestion, recovery, knowledge, retrieval, query and status |
| Integration | MCP, CLI and rendering | `integration/mcp/`, `integration/cli/`, `integration/rendering/` | Read-only stdio, installed commands and Obsidian notes |
| Contract | Docs | `contracts/docs/test_docs.py`, `contracts/docs/test_docs_bilingual.py` | Status/TOC/link contracts and English/Chinese parity |
| Contract | Packaging | `contracts/packaging/test_distribution.py`, `contracts/packaging/test_installer.py` | Metadata, installer, packaged distribution |
| Contract | Architecture/tooling | `contracts/tooling/test_architecture.py`, `contracts/tooling/test_tools.py` | Import boundaries/public API and every `tools/*.py --help` path |

Run by layer:

```sh
python -m unittest discover -s tests/unit
python -m unittest discover -s tests/integration
python -m unittest discover -s tests/contracts
```

Run everything:

```sh
python -m unittest discover -s tests
```

Fixtures live in `tests/fixtures/`; pinned-source instructions are in
`tests/golden/README.md`.

Native TeX integration is opt-in locally. Install TeX Live, Poppler, and the
platform sandbox, then run:

```sh
QECGRAPH_TEST_TEX=1 python -m unittest tests.integration.pipeline.test_compilation_sandbox tests.integration.pipeline.test_compilation -v
```

The independent sandbox probe also runs during ordinary discovery where a
supported sandbox is available. The opt-in CI job requires the sandbox to work.

## References

The layout follows the test-layering ideas used by high-star testing projects:
[Superpowers test-driven-development](https://github.com/obra/superpowers/tree/main/skills/test-driven-development)
(≈315k stars; RED-GREEN-REFACTOR and evidence before completion),
[JavaScript testing best practices](https://github.com/goldbergyoni/javascript-testing-best-practices)
(≈24.6k; unit/component/integration/e2e separation), and the
[pytest repository](https://github.com/pytest-dev/pytest) (≈14.7k; focused test
packages and a separate test tree). The project keeps standard-library
`unittest`, so these are structural references, not new dependencies.
