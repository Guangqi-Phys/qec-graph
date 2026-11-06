# 05 · Lean 接入、证明状态与可查询映射

状态：本文保留原接入规范。当前实现及真实构建、声明/依赖、公理报告见 [13_LEAN_EXECUTION.md](13_LEAN_EXECUTION.md)。
已运行的 core-only Bool 向量边界与旧 HGP 距离示例分开；`knowledge_starter/records/formalization_rep3_hgp_distance.json` 的状态仍为 `not_started`，真实距离声明与构建证据为 null。

## 1. 最先确定的数学接口

从有限二元 CSS 码出发，采用已审核的一套定义。先检查所选固定版本的 mathlib 和候选 QEC 项目是否有兼容表示，再决定复用或适配。不能只因为声明名称相似就认为定义等价。

第一批接口必须约定：

- 标量域 GF(2)，矩阵行表示校验、列表示物理比特，向量的左右乘约定。
- X/Z 校验约定、物理比特顺序、冗余生成元的处理。
- `HX * transpose(HZ) = 0`、秩、核、行空间以及逻辑商空间。
- Hamming weight 和非平凡逻辑算符；CSS 的 X 距离与 Z 距离如何合成码距离。
- `k = 0`、空集合最小值、零长度向量、非满秩种子矩阵等边界。

码参数中的 `k` 由秩决定，不能默认等于 `n - HX行数 - HZ行数`。证明具体实例与证明一般构造分别建 claim；证明码距离与证明电路距离也分别建 claim。

## 2. 保留三种陈述及其对应关系

| 对象 | 权威内容 | 维护方式 |
|---|---|---|
| 来源块 | 论文版本中的原始 TeX、标签、定位、哈希 | 由 parser 提取，归档原文 |
| 规范化 claim | 量词、假设、定义引用、标准化陈述、适用范围 | 经审核的 JSON/TeX 记录 |
| Lean declaration | 实际类型、模块、名称、定义与证明常量依赖 | 从固定构建的 Lean 环境导出 |

它们不是一一对应。一个文献定理可能被拆成多个 Lean lemma，多个文献表述可能映射到同一个形式化结果。用独立的 mapping 对象记录这种关系：等价、特例、加强、弱化、附加假设版本、尚未确定。状态不能仅凭 AI 的“看起来一致”推进。

最小 mapping 字段：

| 字段 | 要求 |
|---|---|
| `id`, `schema_version` | 稳定映射 ID 与明确 Schema |
| `claim_id`, `claim_revision` | 目标数学主张及绑定的版本 |
| `source_refs[]` | source-version ID、标签或 TeX span；PDF 页码单独记录 |
| `definition_refs[]`, `notation_map` | 定义版本与符号对应 |
| `statement_relation`, `extra_assumptions[]` | 与来源的关系及额外条件 |
| `lean_project_id`, `project_commit` | 固定项目与真实提交；未建立时为 null |
| `module`, `declarations[]` | 精确 import 与全限定声明名 |
| `export_ref`, `build_evidence_ref` | 实际导出与构建产物的引用 |
| `semantic_review` | 审核者、日期、绑定版本、结论与说明 |

当前原型的 `formalizes` 是 **Lean 标注节点 → 来源陈述**，只表示作者宣称。未来 importer 必须把它和“环境里确实存在的声明”和“语义对应已经审核”的映射区分开；不要就地升级同一条作者标注。

## 3. 建议的状态模型

将以下维度分别保存，查询时组合使用：

| 维度 | 示例状态 | 谁能推进 |
|---|---|---|
| 来源审核 | extracted / source_checked / disputed | 来源核对工作流 |
| 语义审核 | not_reviewed / matched / extra_assumptions / mismatch | 能阅读原文与 Lean 类型的审核者 |
| 证明进度 | planned / stated / in_progress / build_passed | 构建与开发流程 |
| 公理审计 | not_run / allowed / rejected / unknown | 固定策略的审计器 |
| 新鲜度 | current / stale / missing_inputs | 根据绑定的 revision 和依赖计算 |

上述是**目标规范**，当前 `qecgraph.graph.v1` 尚未提供这些完整字段。迁移时保持旧 `verification_status` 的含义：导入记录不代表重新验证。

## 4. 构建和审计记录

一次构建保存：项目 commit、工作树是否有修改及其补丁哈希、Lean toolchain 原值、Lake manifest 原件与哈希、mathlib commit、平台、实际命令、退出码、日志、目标模块、导出器版本及导出结果哈希。不存在的结果保存 null 和未运行状态，不能填示例值冒充证据。

源文件、`lean-toolchain`、`lakefile.toml` 或 `lakefile.lean`、`lake-manifest.json` 进入版本控制。正常复现不自动执行会改变依赖的 `lake update`。[Lake 官方文档](https://lean-lang.org/doc/reference/latest/Build-Tools-and-Distribution/Lake/)

每个实际声明至少导出：

- 全限定名称、模块、完整类型、命名空间和源码定位（若可用）。
- 类型中的常量依赖与证明项中的直接常量依赖，分字段记录；“使用某定义”不等于“用某定理证明”。
- 传递公理依赖及审计结果，保留完整原始名称，不靠简单搜索源代码里的 `sorry`。
- 导出时的项目、toolchain、依赖哈希与构建证据 ID。

仅 `lake build` 通过不足以确认目标没有依赖 `sorryAx` 或项目自定义公理。Lean 支持跟踪和显示声明的公理依赖；实现时按固定工具链调用 `#print axioms` 或等价环境 API，保留真实输出。[Lean 公理文档](https://lean-lang.org/doc/reference/latest/Axioms/)

对 AI 生成证明，还需检查实际陈述和假设：把结论放到假设里，可以得到一个合法但无助于原目标的定理。根据用途选择进一步的独立检查；不能用“内核接受”替代“它陈述了想证明的数学命题”。[Lean 验证指南](https://lean-lang.org/doc/reference/latest/ValidatingProofs/)

公理策略是项目配置，不是假定所有可构建的结果都合格。可明确评估 `propext`、`Classical.choice`、`Quot.sound` 等基础依赖；原生求值产生的依赖要按实际 Lean 版本审计。不要把某一历史版本的原生计算公理名称硬编码成永久规则。

## 5. 计算与证明如何连接

保存以下证据的区别：

| 证据 | 能支持什么 | 不能自动支持什么 |
|---|---|---|
| Python 穷举所有有限候选 | 在实现与输入正确的前提下，某有限实例的 exact computational result | Lean 已验证、一般参数定理 |
| 一个非平凡逻辑算符 witness | 对应度量的距离上界 | 距离下界 |
| 搜索不到更小 witness | 特定搜索过程的结果 | 完备排除所有更小候选 |
| 求解器与可检查证书 | 绑定编码与实例的候选证明材料 | 编码一定表达正确的 QEC 性质 |
| 已证明编码桥接 + 已证明检查器 + 实例证书检查 | 该正式陈述的可核查证明链 | 未审核的论文语义对应 |

`proof_method` 与 `trust_profile` 是两个字段。外部 SAT/ILP 搜索不必进入最终数学信任基础，前提是它产生的证书由正确且适用的检查器验证，且 QEC 性质到编码的桥接已经证明。文件哈希只绑定数据，不证明桥接或求解器编码正确。

包中的普通 HGP `[[13,1,3]]` 数据保留 GF(2) 种子、校验矩阵、逻辑算符和有限检查结果，适合作为未来 Lean checker 的小型验收实例。它当前仍是计算验证案例。

## 6. 分阶段接入

1. **映射层**：存 claim 与声明计划；真实构建字段保持 null，允许 AI 查询尚缺什么定义和假设。
2. **构建导入层**：选定并构建一个小 Lean 工程，导出一条真实声明的类型、公理、依赖及版本信息。
3. **语义核对层**：对原文、规范化陈述和 Lean 类型做明确对应审核，支持附加假设与不匹配。
4. **依赖图层**：导入真实类型依赖与证明依赖；保留计划依赖，展示差异。
5. **实例与证书层**：逐个证明 GF(2)/CSS 接口、构造对易性、有限实例和证书检查器。

具体阶段编号和验收以 `08_ROADMAP_ACCEPTANCE.md` 为准。一次性接入所有 QEC 定理不作为第一版交付要求。

## 7. 必须覆盖的失败案例

- TeX 中有 `\leanok`，但本地没有 Lean 工程：只显示作者标注，真实构建状态仍为未运行。
- 名称存在，类型额外假定待证结论：声明存在检查通过，语义审核失败。
- 目标源文件不含 `sorry`，传递依赖含 `sorryAx`：公理策略拒绝。
- 数据矩阵发生变化：旧实例的证书和构建仍可查，但不作为新版证据。
- 更换 toolchain 或 mathlib 提交：产生新的 build/export 身份，不能沿用旧构建标签。
- 计划依赖与编译后证明项依赖不同：同时保留并可查询，不覆盖成同一关系。

## 8. 参考项目的使用方式

`leanblueprint` 可作为作者声明、证明目标和 Lean 名称标注的参考；`checkdecls` 检查声明名称，不能替代完整语义与公理审核。[官方仓库](https://github.com/PatrickMassot/leanblueprint)

旧资料 `knowledge_starter/docs/LEAN_ROADMAP.md` 记录了候选 QEC Lean 项目链接。采用前由 Codex 在本次开发环境中读取其当前代码，固定实际 commit、审查许可证、比较定义并实际构建。不要把旧文档提到项目等同于它已经成为依赖。
