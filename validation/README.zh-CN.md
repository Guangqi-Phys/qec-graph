# 验证证据

> **状态：证据索引。** 报告描述针对特定源码修订的运行；它们不能替代当前设计或
> 新的测试运行。

> **中文** · [English](README.md)

> [!NOTE]
> Lean 在 0.4.x 中**延期/实验性**。`validation/lean-experimental/` 下的内容只是
> 回归证据，不是受支持的验证结论。数据库、查询和 MCP 路径不调用 Lean。

- [验证矩阵](index.json) 以机器可读形式列出领域/生命周期/路径。

## 如何使用这棵树

- **当前 release 证据**在 `audit/0.4.0rc1/` 和 `workspace-0.4.0rc1/`。
- **旧阶段**按所验证的子系统分组：baseline、corpus、review、incremental 和 MCP。
- **Lean 实验**隔离在 `lean-experimental/`，只用于保持历史回归测试有意义。
- **`legacy-report-0.3.0.md`** 是旧的阶段式报告，仅保留来源；其链接只作历史上下文。
- **`archive.sha256`** 是已删除批量证据的清单，保留用于审计；字节可从 Git history 取。

## 当前 0.4.0rc1

| 领域 | 证据 |
|---|---|
| 测试/覆盖率日志 | [unit-tests.log](audit/0.4.0rc1/unit-tests.log) |
| 审计批次 | [batch-3](audit/0.4.0rc1/batch-3.json)、[batch-4](audit/0.4.0rc1/batch-4.json)、[batch-5](audit/0.4.0rc1/batch-5.json)、[batch-6](audit/0.4.0rc1/batch-6.json) |
| 分发包检查 | [summary.json](audit/0.4.0rc1/summary.json) |
| Linux MCP 隔离 | [linux-isolation.json](audit/0.4.0rc1/linux-isolation.json) |
| macOS MCP 隔离 | [macos-isolation.json](audit/0.4.0rc1/macos-isolation.json) |
| Obsidian 阅读视图 | [obsidian.json](audit/0.4.0rc1/obsidian.json)、[截图](audit/0.4.0rc1/obsidian-theorem.png) |
| 固定 arXiv corpus | [golden-arxiv.json](audit/0.4.0rc1/golden-arxiv.json) |
| 性能基线 | [benchmark.json](audit/0.4.0rc1/benchmark.json) |
| 工作区验收 | [report.md](workspace-0.4.0rc1/report.md)、[installed.json](workspace-0.4.0rc1/installed.json)、[distributions.json](workspace-0.4.0rc1/distributions.json) |

## 功能证据

| 目录 | 覆盖内容 |
|---|---|
| [`baseline-0.3.0/`](baseline-0.3.0/) | 原始原型安装/复现基线 |
| [`corpus/`](corpus/) | 多文档 registry 导入和迁移 |
| [`review/`](review/) | 类型化记录验证、审核决定和 apply |
| [`incremental/`](incremental/) | 全量/增量等价与恢复 |
| [`mcp/`](mcp/) | 只读 stdio 客户端会话 |
| [`lean-experimental/`](lean-experimental/) | 不受支持的 Lean export/mapping/trust 实验 |
| [`workspace-0.4.0rc1/`](workspace-0.4.0rc1/) | 当前工作区验收和安装回放 |

## 历史 release

| 目录 | 覆盖内容 |
|---|---|
| [`release-0.3.0/`](release-0.3.0/) | 固定 commit 的 0.3.0 回放和安装检查 |
| [`handoff-0.3.0/`](handoff-0.3.0/) | 初始交接证据 |
| [`legacy-report-0.3.0.md`](legacy-report-0.3.0.md) | 阶段式历史报告 |

历史报告及其链接可能描述已被替代的路径。当前行为见[文档索引](../docs/README.zh-CN.md)。
