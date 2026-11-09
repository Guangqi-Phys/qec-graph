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

U2 工作区：`qec-graph init/sync/rebuild/status/validate --workspace PATH`。
机器发布复用 Registry 的不可变状态与单写锁；原包以 SHA-256 归档，
每次投递留独立收据。失败材料留在收件箱并登记；默认 rebuild 遍历全部
归档收据和内容库存。成功结构处理标记 `semantic_pending`，随后才清理认领文件。
入口和来源身份可在 `qecgraph.toml` 中用来源树哈希显式配置。
工作区测试已覆盖部分批次、重投、空箱重建、版本冲突、写锁及指针切换后故障。

U3 第一段：已接入离线、两遍的码记法提议（定位记法后再检查局部语义），
保存精确 TeX 位置、源快照和规则版本；不依据括号猜码类别、把 d 晋升为已知界、
或按参数合并码实例。`review-list` 列出提议，`research-import` 可显式导入
修订化研究记录、软件 seed 或隔离合成 fixture。未实现 LLM、曲线数字化或跨表格实验归属。

U4：`qec-graph mcp serve --workspace PATH` 或严格部署使用 `--machine MOUNT`。
每个会话固定 release；可查来源状态、精确原文、关联上下文、码、性能与软件，
并区分实时脱敏运行投影。按要求下界筛选时不匹配仅有上界的记录；
source-reported 是显式、与数学验证分开的政策。工作区工具拒绝机器目录中的链接，
不读取外部 Lean 工作树，保守报告其现场新鲜度未核查。现有独立 corpus/Lean 命令保留。
实测包含 stdio 调用、固定旧 release、URL 编码路径、链接及合成记录隔离。

U5：工作区 CLI 在机器发布后单独启动 human renderer；
`qec-graph human build --workspace PATH` 可重试，`--no-human` 可跳过。
生成稳定的 Obsidian 页面和分类索引，固定来源 release；旧链接保留 tombstone。
仅替换自己的目标文件，写入目标目录内的临时文件后逐页原子替换；
发布中失败报告 `human_stale`，不能承诺 vault 全局原子。没有读取或覆盖 notes。
测试通过：重复渲染、旧 release 被拒绝、发布中断恢复、notes symlink 负例。
`compose.mcp-isolated.yaml` 提供只读 machine 单挂载 profile；容器执行状态另记录。

U6 迁移：`qec-graph workspace-migrate --corpus OLD --workspace NEW` 验证旧库后复制到
新工作区。保留旧状态、记录、来源快照和审核证据的精确绑定，不在原库改写数据，也不制造旧库
从未保留的下载包。报告记录身份映射、未决字段和审核警告；旧实验维持旧契约，
不自动当成新版可比性能点。实测迁移后仍能从旧修订查询，空收件箱 rebuild 保持旧版本。

发行候选 `0.4.0rc1` 的 wheel/sdist 包含工作区、MCP、human、研究 Schema 和附件软件种子，
不含用户工作区。用 `qec-graph software import-seed` 显式导入 14 个项目；
`qec-graph software coverage` 报告目录范围和未解析使用。导入不会安装软件或补全历史版本。

性能点查询可按坐标精确筛选，或在各自固定曲线修订内选最近已报告点；
结果同时记录请求坐标和实际坐标，不插值、不跨实验排序。已报告率值与计数
必须绑定准确原文位置，缺少条件时返回缺项。软件发布版本还需验证确属该软件项目。
