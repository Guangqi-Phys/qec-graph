# 仓库工具

> **中文** · [English](README.md)

辅助脚本从仓库根目录运行。它们是开发/发布工具，不属于安装后的 `qecgraph` 包。

| 分组 | 脚本 | 用途 |
|---|---|---|
| 复现 | `reproduce.py`、`reproduce_workspace.py`、`reproduce_mcp.py`、`reproduce_golden.py`、`reproduce_incremental.py`、`reproduce_installed.py` | 核心、workspace、MCP、固定来源、增量和安装包的端到端回归 |
| 隔离 | `reproduce_isolation.py`、`reproduce_linux_isolation.py`、`mcp_isolated_macos.py` | OS 级 MCP 隔离检查 |
| 发布 | `check_distribution.py`、`qec-graph.spec` | 分发包元数据检查和 PyInstaller spec |
| 性能 | `bench.py` | 生成增量负载和固定来源基准 |
| 知识证据 | `reproduce_knowledge.py` | 对比完整阅读、原文搜索和任务上下文；不执行 LLM |
| Lean（延期） | `reproduce_lean.py`、`reproduce_lean_checks.py`、`reproduce_lean_mapping.py` | 仅历史/实验 Lean 证据；不是受支持流程 |

标准门禁：

```sh
python tools/reproduce.py --out build/reproduce
python tools/check_distribution.py dist
```

`tools/reproduce_*` 脚本把机器可读报告写到 `build/`；`validation/` 索引当前可执行检查。

运行离线证据对照，或只读使用已登记的 machine release：

```sh
python tools/reproduce_knowledge.py --out build/knowledge-synthetic.json --include-payloads
python tools/reproduce_knowledge.py --machine /path/to/machine --out build/knowledge-real.json --include-payloads
```

`--release` 固定旧 release。`--cases` 接受 JSON 列表，每项含 `name`、`query`、
`kind`、`purpose`、`source_version_id` 和 `expected_evidence`（精确段落字符串）。
未提供题目时，从现有来源生成机械探针，不是经过整理的科学问题。报告披露检索覆盖和
回退。`--include-payloads` 将精确工具返回保存在本地；省略时只保存哈希和测量。
A/B/C 测量证据检索，不评定模型回答质量或数学正确性。
