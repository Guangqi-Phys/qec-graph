# QEC Graph 设计更新交付包

日期：2026-11-09。编号：RFC-QEC-002。

本包是给现有 QEC Graph 仓库的**增量设计与实施任务**，不包含本次新增功能的已完成程序，也不代表已经检查用户当前仓库。

## 文件

| 文件 | 用途 |
|---|---|
| `QEC_GRAPH_DESIGN_UPDATE.md` | 自包含主设计文档：数据契约、抽取证据、软件目录、压缩包工作流、MCP、human、迁移及验收 |
| `CODEX_UPDATE_TASK.md` | 可直接交给 Codex 的实施任务与完成标准 |
| `software_catalog.seed.json` | 14 项官方来源的软件目录种子；不是穷尽清单或环境锁文件 |
| `examples/performance_context.synthetic.json` | 明确标记的合成关联样例，展示未知值与实验绑定 |
| `DESIGN_VALIDATION.json` | 本交付包的文件/JSON/关联检查；不表示业务功能测试已通过 |

## 交给 Codex

将本包放在现有代码仓库的一个独立文档目录，然后给 Codex：

> 请阅读 CODEX_UPDATE_TASK.md 和 QEC_GRAPH_DESIGN_UPDATE.md，先检查当前仓库实际实现并产出 IMPLEMENTATION_AUDIT.md，再按 RFC-QEC-002 完成增量更新、迁移与验收。保留已经工作的 SourceGraph、LemmaGraph、DataGraph 和 Lean 接口，不要按旧原型重建项目。示例与软件目录按本文要求适配。

实际功能、命令和公开发行包须由 Codex 实现并验证后才可宣称可用。主文档中的所有演示路径、synthetic 记录与 MCP 形状示例均不是真实论文或实测结果。
