# 测试布局

> **中文** · [English](README.md)

测试使用标准库 `unittest`，不需要额外测试依赖。目录分为三层，每层内部再按功能
分组。

```text
tests/
├── unit/          # 纯解析、图/领域规则、Schema 检查
├── integration/   # store、workspace、corpus、MCP、CLI、渲染
├── contracts/     # 文档、分发包、架构和工具契约
├── fixtures/      # 共享输入 fixtures
├── golden/        # 固定 arXiv manifest 和说明
└── support.py     # 共享 root/fixture 路径
```

| 层级 | 功能组 | 文件 | 重点 |
|---|---|---|---|
| Unit | 解析 | `unit/parsing/test_parser.py`、`unit/parsing/test_source_package.py` | TeX 解析、归档安全、来源区间 |
| Unit | 领域 | `unit/domain/test_semantic.py`、`unit/domain/test_qec_validation.py`、`unit/domain/test_validators.py`、`unit/domain/test_schemas.py` | 图/证据规则、QEC 检查、Schema 契约 |
| Integration | Pipeline | `integration/pipeline/test_pipeline.py`、`test_publication.py`、`test_registry.py`、`test_splitter.py` | 快照、发布、registry、切割 |
| Integration | 工作区 | `integration/workspace/test_workspace.py`、`test_workspace_migration.py`、`test_workspace_query.py`、`test_incremental.py`、`test_watch.py`、`test_status.py` | init/sync/rebuild、迁移、查询、增量/watch、状态 |
| Integration | Corpus/审核 | `integration/corpus/test_corpus.py`、`test_review.py`、`test_apply.py`、`test_research.py` | corpus 身份、review/apply、类型化研究记录 |
| Integration | MCP/CLI/渲染 | `integration/mcp/test_mcp.py`、`integration/mcp/test_ai_tools.py`、`integration/cli/test_cli.py`、`integration/rendering/test_human.py` | 只读 MCP、CLI、Obsidian 渲染 |
| Integration | Lean（延期） | `integration/lean/test_lean_export.py`、`integration/lean/test_lean_integration.py` | 仅实验回归 fixtures |
| Contract | 文档 | `contracts/docs/test_docs.py`、`contracts/docs/test_docs_bilingual.py` | 状态/目录/链接契约和中英一致性 |
| Contract | 分发包 | `contracts/packaging/test_distribution.py`、`contracts/packaging/test_installer.py` | 元数据、安装器、分发包 |
| Contract | 架构/工具 | `contracts/tooling/test_architecture.py`、`contracts/tooling/test_tools.py` | 导入边界/公共 API 和所有 `tools/*.py --help` 路径 |

按层运行：

```sh
python -m unittest discover -s tests/unit
python -m unittest discover -s tests/integration
python -m unittest discover -s tests/contracts
```

运行全部：

```sh
python -m unittest discover -s tests
```

fixtures 在 `tests/fixtures/`；固定来源说明在 `tests/golden/README.zh-CN.md`。

## 参考

布局参考高星测试项目的分层思路：
[Superpowers test-driven-development](https://github.com/obra/superpowers/tree/main/skills/test-driven-development)
（约 315k stars；RED-GREEN-REFACTOR 和先证据后完成）、
[JavaScript testing best practices](https://github.com/goldbergyoni/javascript-testing-best-practices)
（约 24.6k；unit/component/integration/e2e 分离）和
[pytest 仓库](https://github.com/pytest-dev/pytest)（约 14.7k；聚焦测试包和独立测试树）。
项目继续使用标准库 `unittest`，这些只是结构参考，不增加依赖。
