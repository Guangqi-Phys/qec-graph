# qec-graph：统一图与三个视图的工程规范

## 1. 范围与术语

本文规定图的语义、查询和兼容约束；领域字段以 [04_DATA_FORMATS.md](data-formats.md) 为准，维护流程见 [06_MAINTENANCE.md](../operations/maintenance.md)，Lean 证据见 [05_LEAN.md](../05_LEAN.md)。

项目称为 **qec-graph**，Python 包为 `qecgraph`。SourceGraph 在本文中专指论文及研究资料的来源结构视图，与同名商业代码检索产品无关。

“必须”是实现及验收约束；“建议”允许在记录理由后采用替代实现。“原型已有”描述现有代码，“目标”指后续任务，不得在 UI、README 或回答中把目标标成已经完成。

## 2. 原型能力基线与验收目标

下表记录交接时的基线与阶段目标，当前的数据和查询能力见[数据与检索指南](../DATA_AND_SEARCH.md)。

| 能力 | 本交付包原型 | 后续目标 |
|---|---|---|
| 工程范围 | 一个输出 store 对应一个 `project_id` | 多工作、多版本注册表与跨文档查询 |
| LaTeX | pylatexenc AST、常见结构、字面 include、源位置 | 按实际资料增加受测解析适配器 |
| 图存储 | 完整 JSON、三个 JSON 视图、SQLite/FTS5 | 版本化实体注册表与索引适配层 |
| 人工补充 | 独立 annotations JSON；已有 catalog 导入 | 具备冲突检测的 review/apply 命令 |
| 数学数据 | 明确输入的领域记录；保留原证据状态 | 逐类 QEC schema 与数学验证插件 |
| 更新 | 全工程重建、不可变快照、原子切换指针 | 文件级增量、依赖失效与 watch |
| AI 访问 | CLI/Python/JSON | 复用查询层的只读 MCP 接口 |
| Lean | 作者声明名和对应关系，状态未检查 | 实际类型、依赖、公理与构建证据导出 |

`qecgraph split`、独立 `qec-latex-split` 与 `qec-graph` 别名属于本次交付入口契约；发布前须通过 P0 验收。两个 splitter 入口必须复用 `qecgraph.store.ingest`，不建立第二套切分器。

旧实现说明位于 [原型文档](../archive/prototype/DESIGN.md)。实际命令、测试及结果由 [验证报告](../../validation/REPORT.md) 索引；历史测试记录不能替代本次验证。

## 3. 权威输入与派生产物

原始源码、人工维护的 JSON、已有知识记录及计算证据是权威输入。原型的 `graph.json`、视图、片段副本和 SQLite 都由这些输入生成。

必须保留源文件字节；人工改动写入 sidecar 或领域记录。不得直接修补某个生成视图来更新事实，也不得让 SQLite 与 JSON 同时成为同一字段的独立编辑入口。

YAML 可作为填写和导入模板；统一知识库的人工结构化真本采用 JSON。导入后执行版本化转换，不能长期维护两份可独立修改的数据。

## 4. 节点的四种身份

| 概念 | 意义 | 约束 |
|---|---|---|
| `id` | 对象或来源出现的身份 | 不用参数组、显示标题或文件名代替身份 |
| `revision` | 某个身份在特定上下文中的状态 | 不能据 ID 相同沿用旧审核 |
| `content_sha256` | 准确文本或结构数据的内容 | 必须注明相应序列化协议 |
| `snapshot_id` | 一次完整提取的输入与工具状态 | 不与论文版本、包版本混用 |

有唯一 label 的来源节点使用项目命名空间与 label；重复 label 保留多个出现及歧义，引用不能静默选择其一。无标签节点使用内容与出现信息定位，不承诺任意编辑后的稳定身份。

当前来源区间使用 UTF-8 解码后的 Unicode codepoint `[char_start,char_end)`；行号从 1 开始且含结束行。文件哈希针对原始字节，包括 CRLF/BOM。不能把字节偏移当字符偏移，也不能把源码行号当 PDF 页码。

## 5. Source block 与规范化 Claim 必须分开

原型中 `kind=lemma/theorem/definition` 且 `origin=parser` 的节点表示文档中的一个来源块。它记录作者写了什么，不自动成为经过审核的数学结论。

规范化 `claim` 是独立领域对象：陈述、量词、假设、定义版本、适用对象及证据可以独立修订。形式化是否完成属于另外的证据维度；“规范化”不等于“Lean 已证明”。

来源块与 Claim 必须允许多对多：同一来源段落可能含多个结论，同一结论可能在多篇论文中以不同假设或记号出现。相似文本、相同参数和相同标题不能触发自动合并。

v1 可通过 sidecar/catalog 中的 `claim` 节点与 `describes` 等现有关系建立显式连接。P1 若增加 `states`、`normalizes_to`、陈述等价类型，必须注册语义并升级对应 schema；不得改变现有关系的含义来冒充兼容。

例：一个 LaTeX 参数表是来源节点；表中某个 HGP 实例是 `code_instance`；关于其距离的论断是 `claim`；逻辑 witness 或计算报告是 evidence。四者的身份和证据不能合成一个“已验证表格”字段。

## 6. 三个视图的定义

| 视图 | 当前主要种子节点 | 面向 AI 的问题 |
|---|---|---|
| SourceGraph | parser 产生的文件、结构块、引用和资源；排除 Lean 名称作为种子 | 原文在哪里、结构如何、引用能否解析？ |
| LemmaGraph | 定义、定理类陈述、proof、equation、Lean 声明标注 | 声明依赖是什么、证明目标是否明确？ |
| DataGraph | sidecar/catalog 节点以及 table、figure、asset | 哪个对象、输入、指标和证据相互连接？ |

当前 `graph.views()` 会补入种子的一跳非结构关系邻居，再输出所选节点间的边。因此视图可以重叠，节点 ID 必须一致；视图不是三个独立数据库，也不等同于完整传递闭包。

P1 的目标视图应显式包括注册的规范化 Claim、Definition、Evidence 和领域实例。读取旧快照时仍按其原有视图规则解释，不重写旧文件。

所有视图都应保留边状态。默认面向回答的 context 过滤失效及未请求的候选关系；审核界面可以显示它们并解释原因。

## 7. 边的方向和证据语义

| 关系 | 固定方向 | 语义 |
|---|---|---|
| `contains` | 容器 → 子内容 | 文档结构包含，不表示推理依赖 |
| `defined_in` | 来源块 → 源文件 | 精确出处 |
| `includes` | 包含文件 → 被包含文件 | 字面文件包含 |
| `references` | 引用块 → 被引用块 | `ref/eqref/cref` 等语法引用 |
| `cites` | 引用块 → 书目键 | v1 只解析键，不补全文献语义 |
| `uses_resource` | 来源块或文件 → 资产 | 图片、书目等资源引用 |
| `depends_on_declared` | 使用结果 → 所需结果 | 作者 `uses` 或明确 sidecar 声明 |
| `depends_on_candidate` | 使用结果 → 可能所需结果 | 从证明引用或不确定绑定推测 |
| `depends_on_reviewed` | 使用结果 → 所需结果 | 经过绑定审核的文献依赖 |
| `proof_of` | 证明文本 → 目标陈述 | 作者明确指定目标；不宣告证明有效 |
| `proof_of_candidate` | 证明文本 → 可能目标 | 依据邻近结构推测 |
| `formalizes` | Lean 声明标注 → 文献陈述 | 作者对应标注；不是类型等价证明 |
| `describes` | 来源块 → 领域对象 | 文本描述某对象 |
| `has_matrix/has_presentation` | 码实例 → 矩阵/校验表示 | 显式记录的组成关系 |
| `generated_by` | 产物 → 生成实现或运行 | 生成来源；精确端点类型在 P2 校验 |
| `uses_circuit/uses_noise/uses_decoder` | 运行或配置 → 所用对象 | 实验依赖 |
| `supports` | 证据 → 论断 | 证据声称支持结论；须保留方法和作用范围 |
| `instance_of` | 实例 → 家族或构造类别 | 明确分类 |
| `catalog:*` | 保持原 catalog 方向 | 导入关系，不自动改变其数学含义 |

当前允许的 sidecar 关系以 `qecgraph.graph.KNOWN_RELATIONS` 为准；上表是常用核心语义。`about/reports/contradicts` 等关系的端点限制按数据规范扩展，不能擅自用来替代上述精确关系。

每条边保留 `source,target,relation,status,evidence`。`observed` 是语法观察，`declared` 是作者或元数据声明，`candidate` 是推测；它们不能压缩成单一“可信度分数”。

v1 的 `depends_on_reviewed` 通过关系名与哈希绑定表达审核类别；其有效 `status` 仍可能为 `declared`。迁移时必须保留这一区别，不能要求所有旧审核边的 status 都等于 reviewed。

## 8. 依赖提升与环的规则

普通 `references` 永远不能直接变成已审核依赖。证明中的 `uses` 只有在 proof 目标明确时，才能向目标陈述提升为作者声明依赖；目标只是候选时，提升后的关系也只能是候选。

只有符合依赖边类型约束的节点才能参与提升。指向普通段落、章节等来源块的引用保留为 `references`。

提升必须保存原 proof、原引用边和绑定边的 ID。任何输入边为 `stale/unbound_review/unresolved` 时，不得通过派生过程恢复为有效关系；子证明包含关系同样遵守此规则。

整个知识图谱不要求 DAG：文献互引、同义关联和数据关系可能有环。P2 只对选定的、经过审核的逻辑 `depends_on` 子图报告强连通分量，由审核者判断是粒度问题、联合论证还是错误依赖；不能自动删边或伪造证明顺序来消除环。

文件 include 循环属于解析问题，必须单独诊断；它与数学依赖环不是同一检查。

## 9. 补充输入和审核绑定

`annotations.json` 使用 `schema_version=qecgraph.annotations.v1`，包含 `nodes/edges/annotations`。端点可用精确 ID 或唯一的 `label:...` 选择器；未知、歧义目标必须诊断。

来源块的 reviewed 注释必须绑定 `expected_content_sha256` 与 `expected_project_source_hash`。审核依赖还必须用两端实际 ID 记录 `expected_hashes`。资源内容哈希必须在匹配审核之前完整计算。

原型的工程上下文指纹覆盖入口、读取的源文件、已解析资源及解析配置。这是保守的失效边界；P3 可以缩小重算范围，但不能降低旧审核失效的正确性。

审核绑定失败时保留原记录，计算 `stale` 或 `unbound_review`，并进入诊断。context 排除其影响；show 保留审核详情。新快照不得反向改写 sidecar。

catalog 导入保留完整原记录，关系加 `catalog:` 前缀，导入状态为 `imported_claim_not_rechecked`。原知识库的资产地址不因 JSON 被导入而变成本 store 内的资产；跨库资产解析需要 P1 的显式来源根或 URI 规则。

## 10. 查询契约

| 接口 | 当前实现入口 | 约束 |
|---|---|---|
| ingest/split | `store.ingest(...)` | 所有 splitter 入口调用同一流程 |
| search | `query.search(store,query,kind,limit)` | FTS5 字面短语与子串回退；没有 embedding |
| show | `query.show(store,id_or_label)` | 返回节点及全部入边/出边，供审核 |
| deps | `query.dependencies(...,reverse=False)` | 默认声明/审核依赖，候选需显式打开 |
| impact | 同函数，`reverse=True` | 仅报告已记录关系的潜在影响范围 |
| context | `query.context(...)` | 返回完整来源块和有界相关对象 |
| validate | `store.validate_snapshot(...)` | 验证完整性、结构和来源，不验证定理 |

默认 deps/impact 排除 `stale/unbound_review/unresolved`。默认 context 还排除 candidate 状态和候选关系，过滤必须同时发生在遍历、依赖提升、最终边输出及注释输出阶段。

`--include-candidates` 只允许加入有效候选，不使失效审核重新有效。show 是审核读取接口，故可以展示全部状态；AI 回答不能把 show 中的历史或候选关系当成已确认事实。

深度和 `max_nodes` 是有界检索参数；返回必须说明截断。结构祖先可帮助定位，但不要借此返回全部无关章节。将来加入 token 预算时，优先保持完整假设和陈述，不能只截出定理后半句。

查询显式指定一个 store 或已注册 corpus，可固定快照或版本。空结果只表示该范围未匹配。

## 11. 快照和输出契约

每个快照包含源文件、已解析资源、按 kind 归档的节点 JSON/TeX、完整图、三个视图、SQLite、输入副本、报告与 manifest。父子片段可能重叠；不能把所有片段顺序拼接来重建原文。

快照 ID 必须绑定准确输入、配置、sidecar/catalog、工具源码与解析器版本。相同输入产生相同身份；旧快照不覆盖，完整生成并验证后才切换 `CURRENT.json`。

默认 partial 抽取发布到 CURRENT，以 `extraction_status=partial` 和退出码 2 表明抽取不完整。
`--strict` 将 partial 保留在 staging，仍退出 2，CURRENT 不变。

致命构建错误或写入失败不得让 CURRENT 指向半成品；已有 CURRENT 保持原值。恢复见 [11](../11_INCREMENTAL.md)。

哈希清单检查误修改。单机 POSIX 写者锁和审核版本条件用于本地发布；不提供分布式写入事务。

## 12. 兼容及可测试不变量

包版本与数据 schema 版本分离。必须继续读取已有 `qecgraph.graph.v1`、`qecgraph.annotations.v1` 和旧知识库记录；不能把旧知识库的 `schema_version=0.1.0` 当作 graph v1。

后续升级通过显式 adapter 或迁移产物完成，保留原 ID、原文、出处、证据类型和未知字段。未知版本应报告不可解释，而不是按最新含义猜测。

| 编号 | 必须可测试的不变量 |
|---|---|
| G01 | 每个来源块严格等于已归档源码的对应字符切片 |
| G02 | 注释、verbatim 中的假标签和 include 不进入真实索引 |
| G03 | 嵌套公式拥有自己的标签，重复标签保持歧义 |
| G04 | 引用、作者依赖、候选依赖与审核依赖不混同 |
| G05 | 失效输入边不能通过证明提升或查询重新变有效 |
| G06 | 资源 hash 在审核匹配前已固定；内容变更能使审核失效 |
| G07 | `leanok` 不产生 Lean verified 或语义等价状态 |
| G08 | 参数表不能凭自动切分生成已验证码实例 |
| G09 | 同输入与工具状态重建幂等，原始文件不被修改 |
| G10 | 图、视图与 SQLite 指向同一快照，所有边端点存在 |
| G11 | 有效数据关系能补齐矩阵、表示、指标与证据上下文 |
| G12 | 部分抽取、截断、未解析目标与旧审核状态均可观察 |

测试入口和阶段验收见 [08_ROADMAP_ACCEPTANCE.md](../08_ROADMAP_ACCEPTANCE.md)。
已实现的注册、审核、增量、MCP 和 Lean 能力与其边界见[文档索引](../README.md)。
