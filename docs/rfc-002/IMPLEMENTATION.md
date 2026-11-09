# RFC-QEC-002 实施进度

[现有实现审计](../../IMPLEMENTATION_AUDIT.md)固定 0.3.0 基线；
[设计](QEC_GRAPH_DESIGN_UPDATE.md)定义目标，[任务说明](CODEX_UPDATE_TASK.md)列出验收。
设计目录中的合成样例和目录核查记录不代表论文数据或本地实验。

| 阶段 | 进度 |
|---|---|
| U0 | 已盘点，复现基线通过 |
| U1–U6 | 见后续提交与实测记录 |

U1 数据契约：`qecgraph.research.v1` 与历史 v3 并存；`research.validate_bundle`
验证字段证据、未知值、目标类型和具体修订，拒绝跨实验拼接。目录通过
`software.adapt_seed` 显式转换项目、发行物与算法，未推断使用或历史版本。
合成样例单独适配；仅检查数据契约，未验证论文或实验数值。

U2 解包：按内容识别 TeX、gzip、tar 和 ZIP；限制原包与展开资源，
拒绝链接、特殊成员和会覆盖的路径；来源树哈希包含每个文件的原始字节。
只有唯一有 `documentclass` 和 `begin{document}` 的 UTF-8 文件才自动选作入口，
多个候选留待配置。解包测试通过；工作区提交与回收由下一步接入。
