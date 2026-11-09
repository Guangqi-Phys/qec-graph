# 给 Codex：在现有 QEC Graph 仓库中实施 RFC-QEC-002

## 任务与输入

用户已经执行过旧版构建任务。请在当前真实仓库上做增量更新，先阅读 `QEC_GRAPH_DESIGN_UPDATE.md`，不要按旧原型版本重建整个项目，也不要覆盖已有工作。

**用户最新明确要求：不要限制为“正式接纳”的论文。** 用户投递材料默认登记和可发现，是否采信由用户判断；不设人工批准、发表状态、质量/相关性分数门槛。处理失败、字段未知和冲突作为状态展示。

本轮输入：

- `QEC_GRAPH_DESIGN_UPDATE.md`：完整设计、对象语义、工作区事务、MCP/human 边界和验收。
- `software_catalog.seed.json`：14 项非穷尽的软件目录种子，来源核查不等于安装测试。
- `examples/performance_context.synthetic.json`：仅用于结构与缺失值测试的合成关联样例，不能混进正常研究结果。

若现有 kind/字段名称不同，以保留本文语义的兼容适配为优先；先写映射，不要为照搬名称重写已兼容的模块。

## 先盘点，再实现

先生成 `IMPLEMENTATION_AUDIT.md`：实际分支/commit、CLI、模块、Schema、已有测试和本文每项要求的已完成/部分/缺失状态。运行与修改范围相关的既有基线，指出已存在的问题。没有访问或没有运行的项目标为未核查。

随后按 U0–U6 推进，持续完成实现与必要验收，不要停在一份计划或占位接口上。正常可逆开发和已有授权的修改无需重复询问。发布到公共包索引属于独立交付动作；本任务先构建、验证可安装 wheel/sdist 和发布说明。

## 必须保持的领域语义

1. 码实例、码的检查矩阵/生成元呈现、测量电路、噪声规则、噪声参数点和实验结果分别建模。
2. 保存 `[[n,k,d]]`，但 d 来自 DistanceClaim，必须有度量、exact/lower/upper/interval、算法/定理、适用条件与来源；不得只用 `is_upper_bound`。
3. CSS、构造族、LDPC、QC 等按不同分类轴保存。相同 n/k/d 不能证明两个码相同。
4. check weight 绑定实际 Presentation 与校验集合，区分 X/Z/mixed、stabilizer/gauge/measured、min/max/mean/分布。辛矩阵中的 Y 只贡献一个支撑位置。
5. 矩阵构造保存域、shape、索引、位序、种子、公式和版本；缺少种子时不能标为完整可重建。
6. ErrorModel 保存具体通道、作用位置、概率参数映射、时间/空间相关性和边界。idle、loss、erasure、leakage 分开；缺少证据时 unknown，不写 false。
7. SEC depth 有计数口径，TICK、两比特门层数、全部操作层数、物理时长分开。码距离与 circuit distance 分开，固定故障模型与轮数/边界。
8. 每条 PerformancePoint 固定 code/presentation/circuit/noise instance/decoder/metric/source 的准确修订；选点理由、数值出处、shots/discards、区间与缺失配置可查。
9. 来源报告的实验用 ReportedExperiment；只有实际执行才创建 ExecutionRun。作者报告值与本地复现不能相互覆盖。
10. 量子硬件假设与仿真 CPU/GPU 环境分开。硬件字段包括连接、门集、时长、资源、移动/等待、并行限制与经典反馈。
11. 每个值/关系有 field-level evidence；来源核对、数学验证和人工审核是独立状态。LLM 输出默认是提案。
12. 区分经典种子与量子码，保留 non-stabilizer/subsystem 的原记法和 K/k/r 语义；不根据括号风格猜测，不把 K 当 k。暂不支持的矩阵计算返回 unsupported，来源主张仍可保存。

## 软件注册表

区分 Algorithm、SoftwareProject、SoftwareDistribution、SoftwareRelease 和 SoftwareUsage。导入种子时做显式 schema adapter，不直接把 seed JSON 当生产数据库。

分别保存 mention、citation、source-reported use、locally observed use；仅有包名或算法名不能推断某条 LER 使用了具体软件。BP-OSD 算法不能默认归到 bposd；软件版本未知不能补今天最新版。

新论文中的未知包进入发现/消歧队列。在线 `software refresh` 与离线论文入库分开；刷新目录不安装软件、不更新历史实验依赖、不覆盖用户审核条目。对外显示目录范围和缺口，不宣称穷尽互联网。

## CLI、工作区与消费 inputs

目标用户流程：

```bash
mkdir -p ~/qec/inputs
cd ~/qec
# 放入下载完成的 arXiv TeX source 包
qec-graph init

# 后续再投递新包
qec-graph sync

# 从归档重建
qec-graph rebuild
```

这些是待实现契约。`init` 创建并默认导入，已初始化时幂等且不覆盖配置；`sync` 增量；`rebuild` 使用归档和权威记录；`rebuild --include-inputs` 显式组合两者。保留已有兼容入口。

标准安装包含本地 MCP 与 human 渲染；LLM provider、图表数字化、向量模型和仿真器可以是可选 extras。没有 API key 仍可归档、结构解析、规则提取、查询和启动 MCP；未完成的领域语义明确列出。

按内容识别 tar/tar.gz/zip/单文件 gzip/普通 TeX；安全解包；明确主文件和 supplement，不用最长文件猜。保留原始字节、展开树和完整来源映射。未知 arXiv 版本不能默认 v1。

成功处理顺序：认领输入 → 归档并验证哈希 → 暂存解析/记录 → 构建完整机器 release → 校验 → 原子发布指针 → 可恢复地登记提交 → 只消费该事务的输入副本。

任何失败不能 `rm inputs/*`。失败包保留；部分批次可提交成功子集；崩溃恢复不丢输入、不重复事实。同一 workspace 单写者，多读者固定不可变 snapshot。人工修订受到版本和字段所有权保护。

默认 rebuild 检查全部归档材料，包括以前只归档、未解析成功和版本冲突的材料，并用当前处理器尝试处理；只有用户明确设置的范围/排除规则才缩小范围。manifest用于固定本次输入和结果，不是论文批准名单。未解析材料保留可见来源条目和原包，不能伪造提取产物；重试失败也不能覆盖旧有效产物。

来源条目可见不代表其输入事务已经完成。仅登记 parse_failed 状态时仍保留 inbox 副本；只有归档、校验、配置承诺的处理阶段和提交都完成后才消费成功输入。

支持 `status`、`validate`、`review list`、`sync --dry-run`、`--keep-inputs`，以及清晰的 JSON 报告。归档/结构/语义/机器发布/human 状态分开；semantic_pending 不能冒充全部参数已提取。

## 真正实现 MCP 和 human

MCP 必须是真实可连接、经实际 client 测试的只读服务，不能仅导出目录或写一份工具列表。CLI/Python/MCP 共用查询层，硬筛选依据精确字段与证据政策，返回来源、snapshot、unknown/conflict、分页/截断信息。

最低工具能力：status、search、get_entity、find_codes、find_performance、get_context、dependencies/impact、get_source、find_software。ID 经注册表解析，不能接受任意路径、任意 SQL 或 shell；stdout 仅用于协议。

运行状态以脱敏 operational 投影提供，带 observed_at 和所指 release；与固定 knowledge snapshot 分开。MCP 不得为返回 human 构建状态而访问 human、inputs 或完整 journal。

`human/` 是独立 Obsidian vault，使用稳定的 generated 页面、分类索引和引用链接。`human/notes/` 是人工笔记，任何提取、索引、embedding、MCP、日志和 renderer 都不读取其内容；自动生成器不覆盖 notes。

机器库不反向读取 human。用户纠错要显式写结构化修订。改名/合并保留稳定路径或 tombstone；人库渲染可能存在逐文件更新窗口，失败报告 human_stale，从固定机器 release 恢复，不能宣称多文件全局原子发布。

跨挂载部署中，逐页发布先写到目标目录内临时文件，再同目录原子替换；不能直接跨文件系统 rename staging 文件。

AGENTS.md/human_only 标记只是约定。应用层实施白名单/真实路径校验；另交付可验证的严格隔离 profile，研究 agent 与 MCP 不挂载 human，renderer 独立运行。不把 MCP roots 当访问控制。

## 实施顺序与验证

| 阶段 | 必须交付 |
|---|---|
| U0 | 实际仓库 audit、兼容与迁移映射、基线结果 |
| U1 | 领域 Schema、typed relations、unknown/evidence、软件目录 adapter |
| U2 | 可安装 package、工作区、归档事务、init/sync/rebuild、恢复 |
| U3 | 两遍领域抽取、规则/可配置 LLM 提案、审核、选点和 coverage |
| U4 | 固定快照查询、只读 MCP、来源上下文、human 隔离 |
| U5 | 确定性 human renderer、稳定链接、notes 保护、恢复 |
| U6 | 数据迁移、安装/升级/跨平台说明、相关真实论文回归 |

执行主文档 F5 的 A01–A11、D01–D14、M01–M04、H01–H03、P01–P02。特别检查 upper-bound 筛选、缺失噪声、软件名歧义、多实验串线、全部归档参与重建、解包路径逃逸、崩溃窗口和 human canary。先复用现有测试；只增加验证真实新风险的测试。

合成 fixture 是关联示例，不是生产 Schema；导入前适配，所有实体必须带 synthetic 标记并从默认研究结果排除。建立独立、人工核对的真实论文 golden 集；有分发权才将原论文完整打包进公共测试。

## 交付完成条件

在源码目录外安装实际 wheel，新目录只建 inputs，执行 init 后能够查来源、码/实验字段及明确缺失状态；再 sync 和空 inputs 下 rebuild 都成功；MCP client 能查，Obsidian 可打开 human，notes 不变。

提交实际改动、迁移器、测试结果、安装包、示例工作区、MCP 配置、软件目录覆盖报告和限制清单。逐项标记已运行验证、部分实现和未实现；不把 mock、仅 Schema 通过或“有函数名”作为整个功能完成。
