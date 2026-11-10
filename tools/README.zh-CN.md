# 仓库工具

> **中文** · [English](README.md)

辅助脚本从仓库根目录运行。它们是开发/发布工具，不属于安装后的 `qecgraph` 包。

| 分组 | 脚本 | 用途 |
|---|---|---|
| 复现 | `reproduce.py`、`reproduce_workspace.py`、`reproduce_mcp.py`、`reproduce_golden.py`、`reproduce_incremental.py`、`reproduce_installed.py` | 核心、workspace、MCP、固定来源、增量和安装包的端到端回归 |
| 隔离 | `reproduce_isolation.py`、`reproduce_linux_isolation.py`、`mcp_isolated_macos.py` | OS 级 MCP 隔离检查 |
| 发布 | `check_distribution.py`、`qec-graph.spec` | 分发包元数据检查和 PyInstaller spec |
| 性能 | `bench.py` | 生成增量负载和固定来源基准 |
| Lean（延期） | `reproduce_lean.py`、`reproduce_lean_checks.py`、`reproduce_lean_mapping.py` | 仅历史/实验 Lean 证据；不是受支持流程 |

标准门禁：

```sh
python tools/reproduce.py --out build/reproduce
python tools/check_distribution.py dist
```

`tools/reproduce_*` 脚本把机器可读报告写到 `build/`；`validation/` 按功能区域保留
选定的历史报告。
