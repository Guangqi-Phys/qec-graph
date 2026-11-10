# 测试布局

> **中文** · [English](README.md)

测试使用标准库 `unittest`，不需要额外测试依赖。

| 分组 | 文件 | 重点 |
|---|---|---|
| 文档 | `test_docs.py`、`test_docs_bilingual.py` | 状态/目录/链接契约和中英一致性 |
| 架构和工具 | `test_architecture.py`、`test_tools.py` | 导入边界/公共 API 和所有 `tools/*.py --help` 路径 |
| 包和分发包 | `test_distribution.py`、`test_installer.py`、`test_schemas.py` | 元数据、安装器、打包 Schema |
| 解析和来源 | `test_parser.py`、`test_source_package.py`、`test_splitter.py` | TeX 解析、归档安全、来源区间 |
| Store 和发布 | `test_pipeline.py`、`test_publication.py`、`test_registry.py`、`test_migrations.py` | 快照、写锁、原子发布、恢复 |
| 工作区 | `test_workspace.py`、`test_workspace_migration.py`、`test_workspace_query.py`、`test_human.py` | init/sync/rebuild、迁移、查询和 Obsidian 渲染 |
| 研究和审核 | `test_research.py`、`test_review.py`、`test_apply.py`、`test_qec_validation.py`、`test_validators.py` | 类型化记录、证据、决定、apply 事务 |
| MCP 和隔离 | `test_mcp.py`、`test_ai_tools.py`、`test_watch.py`、`test_status.py` | 只读 MCP、状态和 watch 路径 |
| Lean（延期） | `test_lean_export.py`、`test_lean_integration.py` | 仅实验回归 fixtures |

运行全部：

```sh
python -m unittest discover -s tests
```

fixtures 在 `tests/fixtures/`；固定来源说明在 `tests/golden/README.zh-CN.md`。
