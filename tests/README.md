# Test layout

Tests use the standard library `unittest` runner and do not require a separate
test dependency.

| Group | Files | Focus |
|---|---|---|
| Documentation | `test_docs.py`, `test_docs_bilingual.py` | Status/TOC/link contracts and English/Chinese parity |
| Architecture and tooling | `test_architecture.py`, `test_tools.py` | Import boundaries/public API and all `tools/*.py --help` paths |
| Package and distribution | `test_distribution.py`, `test_installer.py`, `test_schemas.py` | Metadata, installer, packaged schemas |
| Parsing and provenance | `test_parser.py`, `test_source_package.py`, `test_splitter.py` | TeX parsing, archive safety, source spans |
| Store and publication | `test_pipeline.py`, `test_publication.py`, `test_registry.py`, `test_migrations.py` | Snapshots, writer locks, atomic publication, recovery |
| Workspace | `test_workspace.py`, `test_workspace_migration.py`, `test_workspace_query.py`, `test_human.py` | Init/sync/rebuild, migration, queries and Obsidian rendering |
| Research and review | `test_research.py`, `test_review.py`, `test_apply.py`, `test_qec_validation.py`, `test_validators.py` | Typed records, evidence, decisions, apply transactions |
| MCP and isolation | `test_mcp.py`, `test_ai_tools.py`, `test_watch.py`, `test_status.py` | Read-only MCP, status and watch paths |
| Lean (deferred) | `test_lean_export.py`, `test_lean_integration.py` | Experimental regression fixtures only |

Run everything:

```sh
python -m unittest discover -s tests
```

Fixtures live in `tests/fixtures/`; pinned-source instructions are in
`tests/golden/README.md`.
