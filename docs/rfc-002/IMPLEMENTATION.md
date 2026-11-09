# RFC-QEC-002 实施进度

[现有实现审计](../../IMPLEMENTATION_AUDIT.md)固定 0.3.0 基线；
[设计](QEC_GRAPH_DESIGN_UPDATE.md)定义目标，[任务说明](CODEX_UPDATE_TASK.md)列出验收。
设计目录中的合成样例和目录核查记录不代表论文数据或本地实验。

| 阶段 | 进度 |
|---|---|
| U0 | 已盘点，复现基线通过 |
| U1 | 研究记录、字段证据、版本绑定、软件目录及显式观察 |
| U2 | 来源包、工作区原子发布、可恢复消费和安装 |
| U3 | 离线记法提议、可选 provider 文件交接与审核；复杂实验仍需提取 |
| U4 | 固定 release 的查询、MCP 原文与资产、机器隔离 |
| U5 | Obsidian 文件生成、稳定链接、笔记保护与故障恢复 |
| U6 | 0.3.0 迁移、发行候选和真实来源回归；平台缺口见[验收报告](../../validation/rfc002/REPORT.md) |

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

两遍规则现区分带明示语义的非加性维数 K、子系统 k/r 与 K/R、
以及标注为 parent BCH 的经典种子列。数值或符号记法都绑定原文；
不按括号猜类别、混用 K/k，或把表格距离当成经过验证的数值。
真实 *Subsystem Codes* v1 回放校对了表中量子码、经典 parent 与正文 K/R 记法。

工作区 MCP 另支持固定发布的 `resources/list` 和 `resources/read`。
只接受本会话登记的 `qec://source/...` 标识，带代码点坐标、内容哈希和 release；
不解析 file URI 或任意编码路径。协议固定为
[MCP 2025-06-18 resources](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)。

可选语义提议采用本地文件交接：`extract-request` 导出有预算的完整原文块；
使用者自行选择 provider；`extract-submit` 核对模型、处理器、提示哈希和字段所引的摘录，
只登记草稿。`extract-review` 用显式人员决定发布特定草稿，来源投影变化后自动排除失效审核，
历史快照仍可审计。无自动网络请求，也不要求论文经过批准。已通过合成 provider 合同回放；
未连接外部模型或验证通用 LLM 抽取质量。

macOS 严格运行配置：`tools/mcp_isolated_macos.py --python VENV/bin/python --machine WORKSPACE/machine`
用 deny-by-default profile 启动 wheel 中的 MCP。实际进程验证可读机器库，无法读取或列出
测试 notes、列出 inputs、写机器库或绑定网络端口。Docker Compose profile 已解析，
本机 Docker daemon 不可用，未执行 Docker/Linux 容器验收。

工作区写入先保存候选机器状态，再按固定候选修订验证来源、图、引用与审核状态，
通过后才切换 CURRENT。已通过验证拒绝后的恢复测试：旧发布不动，原包与认领保留，
重试可发布且不重复收据。没有将进程中断测试表述为掉电或分布式文件系统保证。

研究校验额外拒绝把未知噪声写成 false、无来源声明排除噪声、以 TICK 表示物理时间，
或用不全的公式/种子宣称矩阵可重建。校验重量口径必须指定检查集合、sector 和 scope；
现有辛重量例验证 Y 计一个位置。字段通过结构校验并不证明模型或数学正确。

`qec-graph software refresh --project-id software:stim` 显式核对公开 GitHub 仓库元数据，
只追加绑定项目修订的观察记录。不跟随重定向，不安装软件，也不修改项目、发行版本或论文使用记录。
已用 [Stim 官方仓库](https://github.com/quantumlib/Stim) 实测成功。其他目录项未批量刷新；
非 GitHub 来源保留待核对。

`asset-add` 将显式选择的矩阵/线路/数据文件按哈希保存，拒绝 human 路径和链接。
研究记录的资产字段只接受受管理的 ID；只读工具 `qec_get_asset` 仅返回当前快照中
有效记录实际绑定的资产，可按字节分页。未被记录引用的文件即使知道哈希也不可通过 MCP 读取。

已用源码目录外安装的 0.3.0 创建并审核两版声明，再用候选版复制迁移。
安装回放检查旧 CURRENT 未变化、新库可读原始和人工审核修订、重建不丢历史；
同时用实际 stdio client 检查工具及资源列表、原文与哈希一致和 vault 路径拒绝。
