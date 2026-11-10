# 验证证据

> **状态：当前（0.6.x）。** 这里是可执行检查的索引，不是历史运行归档。

> **中文** · [English](README.md)

仓库不再携带历史运行产物。早期 release 的证据保留在 Git history；本目录只保留
当前索引，避免把过期报告误当成对当前代码的结论。

## 当前检查

| 检查 | 命令 |
|---|---|
| 单元、集成和契约测试 | `python -m unittest discover -s tests` |
| 端到端抽取和查询复现 | `python tools/reproduce.py --out build/reproduce` |
| Workspace、MCP 和隔离检查 | `python tools/reproduce_workspace.py` 和 `python tools/reproduce_mcp.py` |
| 发行分发包 | `python -m build` 后运行 `python tools/check_distribution.py dist/` |
| 发行二进制 | `Standalone Release` GitHub workflow |
| AI 配置与 provider 探针 | `qec-graph ai status` 和 `qec-graph ai test` |
| AI proposals | `qec-graph ai proposals --json` |

检查只对实际运行它的源码修订和环境构成证据。测试通过不代表论文定理为真、
距离界已被数学验证，或 Lean 声明已语义匹配。

## 添加证据

把新日志或报告附在产生它的 release/CI 运行上；或者仅在该版本仍是当前版本时
新增版本化目录。不要把旧报告复制到新版本，也不要修改已记录的结果来匹配新代码。
