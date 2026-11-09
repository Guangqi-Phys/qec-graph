# QEC Graph 设计更新交付包

日期：2026-11-09。编号：RFC-QEC-002。

本页归档 RFC-QEC-002 的原始设计与实施任务。当前命令见[工作区说明](WORKSPACE.md)，
实施范围见[实施记录](IMPLEMENTATION.md)。

## 文件

| 文件 | 用途 |
|---|---|
| `QEC_GRAPH_DESIGN_UPDATE.md` | 自包含主设计文档：数据契约、抽取证据、软件目录、压缩包工作流、MCP、human、迁移及验收 |
| `CODEX_UPDATE_TASK.md` | 可直接交给 Codex 的实施任务与完成标准 |
| [软件目录种子](../../qecgraph/catalog/software_catalog.seed.json) | 包内的 14 项官方来源软件目录 |
| [合成关联样例](../../tests/fixtures/performance_context.synthetic.json) | 测试未知值与实验绑定 |
| `DESIGN_VALIDATION.json` | 原设计包的路径与哈希记录。目录种子和合成样例已迁至上表位置 |

## 交给 Codex

将本包放在现有代码仓库的一个独立文档目录，然后给 Codex：

> 请阅读 CODEX_UPDATE_TASK.md 和 QEC_GRAPH_DESIGN_UPDATE.md，先检查当前仓库实际实现并产出 IMPLEMENTATION_AUDIT.md，再按 RFC-QEC-002 完成增量更新、迁移与验收。保留已经工作的 SourceGraph、LemmaGraph、DataGraph 和 Lean 接口，不要按旧原型重建项目。示例与软件目录按本文要求适配。

实际功能、命令和公开发行包须由 Codex 实现并验证后才可宣称可用。主文档中的所有演示路径、synthetic 记录与 MCP 形状示例均不是真实论文或实测结果。
