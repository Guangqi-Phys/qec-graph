# Test layout

> **English** · [中文](README.zh-CN.md)

Tests use the standard library `unittest` runner and do not require a separate
test dependency. The tree has three layers, with functional subdirectories
inside each layer.

```text
tests/
├── unit/          # pure parsing, graph/domain rules, schema checks
├── integration/   # store, workspace, corpus, MCP, CLI, rendering
├── contracts/     # docs, packaging, architecture and tooling contracts
├── fixtures/      # shared input fixtures
├── golden/        # pinned arXiv manifest and instructions
└── support.py     # shared root/fixture paths
```

| Layer | Functional group | Files | Focus |
|---|---|---|---|
| Unit | Parsing | `unit/parsing/test_parser.py`, `unit/parsing/test_source_package.py` | TeX parsing, archive safety, source spans |
| Unit | AI | `unit/domain/test_ai_config.py`, `test_ai_client.py`, `test_ai_provider.py`, `test_ai_skills.py`, `test_ai_normalize.py`, `test_ai_normalize_runner.py`, `test_ai_extract.py`, `test_ai_prefetch.py` | Provider config, structured output, skills, normalization and concurrent prefetch |
| Unit | Domain | `unit/domain/test_semantic.py`, `unit/domain/test_qec_validation.py`, `unit/domain/test_validators.py`, `unit/domain/test_schemas.py` | Graph/evidence rules, QEC checks, schema contracts |
| Integration | Pipeline | `integration/pipeline/test_pipeline.py`, `test_publication.py`, `test_registry.py`, `test_splitter.py` | Snapshot, publication, registry, splitting |
| Integration | Workspace | `integration/workspace/test_workspace.py`, `test_workspace_migration.py`, `test_workspace_query.py`, `test_incremental.py`, `test_watch.py`, `test_status.py` | Init/sync/rebuild, migration, queries, incremental/watch, status |
| Integration | Corpus/review | `integration/corpus/test_corpus.py`, `test_review.py`, `test_apply.py`, `test_research.py` | Corpus identity, review/apply, typed research records |
| Integration | MCP/CLI/rendering | `integration/mcp/test_mcp.py`, `integration/mcp/test_ai_tools.py`, `integration/cli/test_cli.py`, `integration/rendering/test_human.py` | Read-only MCP, CLI, Obsidian rendering |
| Integration | Lean (deferred) | `integration/lean/test_lean_export.py`, `integration/lean/test_lean_integration.py` | Experimental regression fixtures only |
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

## References

The layout follows the test-layering ideas used by high-star testing projects:
[Superpowers test-driven-development](https://github.com/obra/superpowers/tree/main/skills/test-driven-development)
(≈315k stars; RED-GREEN-REFACTOR and evidence before completion),
[JavaScript testing best practices](https://github.com/goldbergyoni/javascript-testing-best-practices)
(≈24.6k; unit/component/integration/e2e separation), and the
[pytest repository](https://github.com/pytest-dev/pytest) (≈14.7k; focused test
packages and a separate test tree). The project keeps standard-library
`unittest`, so these are structural references, not new dependencies.
