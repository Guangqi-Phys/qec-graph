# QEC Graph — 系统设计

> **状态：当前权威设计（0.6.x）。** 这是唯一有效的设计文档。

> **中文** · [English](DESIGN.md)

| | |
|---|---|
| **状态** | 当前权威设计（0.6.x） |
| **评审日期** | 2026-11-12 |
| **替代** | 此前的 architecture、graph-contract、data-formats、incremental、MCP 和 CodeGraph 设计页。Lean 集成已移除；见 §10。 |
| **实现** | `qecgraph/`、`tests/`、`tools/`、`validation/` |

本文是系统架构、数据契约、证据语义、发布协议、查询/MCP 接口、人类视图和延期
产品边界的唯一权威来源。如果代码、测试和本文不一致，以可执行行为及其验证为
当前状态；修改设计的同一个变更必须更新本文。不要为新想法创建第二份设计页：
扩展本文，或在这里记录替代决策。

| 状态 | 含义 |
|---|---|
| **Implemented** | 已存在于包中，并由测试或记录的验证覆盖。 |
| **Usable（可用）** | 满足 §16.8 真实论文与独立人工验收契约；不能仅从测试通过推断。 |
| **Partial** | 机制存在，但记录了缺失或有局限的部分。 |
| **Not implemented** | 设计目标没有可执行实现。绝不要把它描述为可用。 |
| **Historical** | 被替代的材料只保留在 Git history 中，不在当前文档树。 |

---

## 本页目录

- [1. 范围与非目标](#1-范围与非目标)
- [2. 系统总览](#2-系统总览)
- [3. 权威、存储和发布](#3-权威存储和发布)
- [4. 数据契约](#4-数据契约)
- [5. 来源抽取](#5-来源抽取)
- [6. 审核、证据和查询资格](#6-审核证据和查询资格)
- [7. 工作区事务与发布协议](#7-工作区事务与发布协议)
- [8. 查询、CLI 和 MCP 契约](#8-查询cli-和-mcp-契约)
- [9. 人类视图](#9-人类视图)
- [10. Lean 路线已移除](#10-lean-路线已移除)
- [11. CodeGraph 参考与第三方归属](#11-codegraph-参考与第三方归属)
- [12. 不变量和失败案例](#12-不变量和失败案例)
- [13. 当前限制和非目标](#13-当前限制和非目标)
- [14. 验证和变更规则](#14-验证和变更规则)
- [15. AI 接入](#15-ai-接入)
- [16. 可搜索知识体系与实施路线](#16-可搜索知识体系与实施路线)
- [附录 A — 决策记录（替代当前行为的独立 ADR）](#附录-a--决策记录替代当前行为的独立-adr)
- [附录 B — 主要参考](#附录-b--主要参考)

## 1. 范围与非目标

QEC Graph 把 LaTeX 论文和显式 QEC 研究记录变成保留来源的本地工作区。它面向五个问题：

1. 一个陈述、定义、证明、表格或参数究竟写在哪里？
2. 来源声称什么、显式记录了什么、审核了什么、计算了什么？
3. 哪些码、表示、电路、噪声模型、解码器、实验和软件版本与一个结果相连？
4. 什么可以交给只读 agent，而不会把候选、上界或作者声明悄悄变成事实？
5. 论文表达了哪些问题、动机、方法与开放问题，它们如何联系具体结果和前人工作？

**它不是：**

- TeX 引擎、PDF/OCR 流水线，或阅读论文的替代品；
- 数学证明助手或大规模码的距离求解器；
- 对论文定理为真、Lean 声明与 prose 匹配、报告 LER 可复现的声称；
- 多写者或分布式数据库；或
- 在读取时执行源码、TeX 或 Lean 的服务。

可执行范围是 Python 包、CLI、本地 MCP 服务、Obsidian 渲染器和 store/corpus
兼容层。

---

## 2. 系统总览

### 2.1 主流程：工作区

```mermaid
flowchart LR
    Inputs["inputs/ source packages"] --> Archive["archive/ bytes + receipts"]
    Archive --> Extract["LaTeX 抽取与来源注册"]
    Extract --> Records["paper_version 与参数提及"]
    Extract --> Proposals["可选 AI 提议"]
    Manual["显式 research 导入"] --> Validate["候选发布校验"]
    Records --> Validate
    Proposals --> Validate
    Validate --> Machine["machine/ immutable release"]
    Machine --> CLI["CLI query"]
    Machine --> MCP["read-only MCP"]
    Machine --> Human["human/YYYY/MM/*_thoughts.md"]
```

工作区是只有一个写者的本地目录。`init` 创建布局；`sync` 归档并处理收件箱包；
`rebuild` 重新检查整个归档；`status`、`validate` 和 `doctor` 是偏只读的检查命令。
成功事务发布不可变机器 release，然后渲染独立的人类视图。查询和 MCP 会话固定
release，绝不在会话中途读取移动的 `CURRENT`。

### 2.2 从一篇论文到一次回答

1. 将 `paper.tar.gz` 放入 `inputs/`，运行 `qec-graph workspace sync --workspace /path/to/workspace`。writer 认领副本，原样归档到 `archive/blobs/sha256/` 并写入回执。
2. 验证后的解包产生 `sources/<tree-hash>/`，受管理的 store 位于 `machine/source_snapshots/`。自动登记论文版本和字面参数提及；**不自动**归并码、译码器、噪声及实验身份。
3. 显式配置 `[ai].allow_source_upload = true`、启用 skill 并提供凭据后，可选抽取将四类 proposed 产物写入 `machine/ai/proposals/`。通过程序校验的结果也直接写入规范研究库，类型为 `ai_extraction`，来源标为 `ai_extracted`。记录保留论文版本、行号引用和模型出处。名称在论文内使用，尚未绑定的提及不进入码或性能精确筛选。
4. 校验将来源、记录和已登记审核哈希绑定在 `machine/states/<release>.json`，原子替换 `CURRENT.json` 后发布，之后才可消费认领输入。必需步骤失败保留旧 release；可选检索投影不可用时可发布 `stale` 并回退关键词检索。
5. 人类生成器只读这个固定 release。research MCP 客户端调用 `qec_list_papers`、`qec_search`，再用返回的短标识调用 `qec_fetch` 或 `qec_get_context`，获取来源坐标、proposed/reviewed 状态和明确缺项。回答引用这些坐标；搜索命中不等于数学验证。

写入者先发布结构，再完成符合条件的认领。可选语义抽取在写锁之外执行。待处理任务由已发布的来源绑定确定，可由 sync 重试。发布 AI 结果时重新取锁，并核对固定 release 和配置。解决入口或恢复来源结构所需的 AI 在结构事务中运行。

### 2.3 工作区接口

知识库只接受工作区发布。独立切割器可以导出 LaTeX 片段。

### 2.4 运行时与部署

- Python 3.11+，POSIX 文件系统；SQLite 带 FTS5。
- 运行时依赖 `pylatexenc==2.10` 和 `jsonschema==4.26.0`。
- 安装：GitHub Releases 的单文件可执行程序、本地 wheel/sdist，或从 checkout
  执行 `pip install -e .`。
- research Compose profile 和 macOS 只读 MCP 隔离 profile 是发布检查；用
  `validation/README.md` 中的命令重新运行。Linux profile 使用替代的本地 Ubuntu base，因为默认
  Docker Hub 查询超时。没有新验证时，不要声称通用 Docker Hub 构建或 Windows 支持。
- 包版本与 graph/record schema 独立。`qec-graph --version` 是
  已安装包版本的权威来源。

### 2.5 模块边界

```mermaid
flowchart TB
    CLI["CLI / splitter 入口"] --> APP["workspace、store、corpus、review、research"]
    MCP["只读 MCP"] --> APP
    APP --> CORE["parser、graph、query、validators、coordinates"]
    APP --> OUTPUT["human 渲染、SQLite/FTS5、machine release"]
```

| 层 | 模块 | 规则 |
|---|---|---|
| 入口 | `qecgraph/cli`、`qecgraph/mcp/server.py`、`qecgraph/source/splitter.py` | 可导入应用模块；包导入不得加载 CLI |
| 应用 | `store.py`、`workspace.py`、`workspace_*.py`、`corpus.py`、`registry.py`、`review.py`、`query.py`、`domain/*` | 拥有事务和策略；不得导入开发层 |
| 内核 | `core/graph.py`、`core/transactions.py`、`core/coordinates.py`、`source/*`、`validators/*` | 纯逻辑或本地副作用；不得导入 tests/tools/validation |
| 输出 | `render/human.py`、`domain/status.py`、`domain/software.py`、`mcp/*` | 从固定 release 渲染/读取；不得通过 `human/` 写回 |

`tests/contracts/tooling/test_architecture.py` 强制执行导入边界。实现现在位于
`core/`、`source/`、`domain/`、`render/`和 `mcp/`；`store.py`、
`workspace.py`、`corpus.py` 继续保持为内聚服务模块，后续再拆。
`qecgraph/splitter.py` 和 `qecgraph/mcp_server.py` 是文档化模块入口的薄兼容 shim。

---

## 3. 权威、存储和发布

### 3.1 每个字段只有一个可编辑所有者

| 层 | 权威内容 | 可编辑？ | 可重建？ |
|---|---|---|---|
| 原始资产 | 固定 commit 的原始论文/TeX 包、PDF、矩阵、证书、Lean 源码 | 否（追加新版本） | 否 |
| 人工记录 | `research` JSON、审核绑定、显式关系、资产清单 | 是，通过显式记录/事务 | 否 |
| 执行证据 | 构建日志、导出、计算检查、运行输出 | 发布后否 | 否 |
| 查询投影 | `graph.json`、视图、SQLite/FTS5、人类页面 | 否 | 是 |

Markdown 解释决策，不拥有 QEC 事实。YAML 是导入/模板格式，不是第二份可编辑真相。
SQLite 和生成图视图可重建，绝不能被修补以改变事实。

机器 release 是查询或 MCP 会话唯一可消费的权威状态。人类视图是固定 release 的
渲染，不是新的知识来源。审核者或 agent 不得通过人类视图写回。

### 3.2 工作区布局

```text
workspace/
├── qecgraph.toml                 # workspace id, limits, explicit source metadata
├── inputs/                       # claimed inbox; successful packages are consumed
│   └── .processing/              # durable claims for crash recovery
├── archive/
│   ├── blobs/sha256/<hash>       # original package bytes
│   └── receipts/<job>.json       # claim/archive receipt
├── sources/<tree-hash>/          # verified expanded source tree
├── machine/
│   ├── CURRENT.json              # published release pointer
│   ├── states/<release>.json     # immutable registry state
│   ├── operational/status.json   # sanitized operational projection
│   ├── source_snapshots/         # 受管理 store：来源、graph、views、SQLite
│   ├── research/                 # 带修订的 research JSON
│   ├── ai/proposals/             # 四类 skill 输出，仅 proposed
│   ├── derived/normalizations/   # 原字节投影及来源映射
│   ├── retrieval/        # 可选 JSON 向量/块投影
│   ├── assets/                   # 登记的数据和证据资产
│   └── .writer.lock              # single-writer lock
├── human/
│   └── YYYY/MM/
│       └── Surname_First_Two_thoughts.md
└── .qecgraph/                    # claim/rotation/staging internals
```

查询和 MCP 只接受当前工作区发布。已有旧发布时，用新的工作区和归档副本重新构建，原始归档保持不动。

### 3.3 身份不是哈希、标题或参数元组

| 概念 | 含义 | 不等同于 |
|---|---|---|
| `work_id` | 论文/work 身份 | 来源版本、文件、标题 |
| `source_version_id` | work 的特定版本 | 包归档哈希 |
| 来源 occurrence | 来源版本中精确区间的 parser block | 规范化 claim |
| 实体 `id` | 稳定领域对象身份 | `[[n,k,d]]`、标签、文件名 |
| `revision` | 实体的内容状态 | 包 release |
| `content_sha256` | 精确序列化内容 | 对象身份 |
| `snapshot_id` / `release_id` | 一次抽取或发布状态 | 论文版本 |
| 资产 ID | 内容寻址的受管理字节 | 源文件路径 |

重复标签有歧义，必须用精确 ID 消解。缺少记录不能证明对象不存在。`[n,k,d]`
相等不能证明码身份；construction、check-matrix representation、logical basis 和 evidence 保持分离。

---

## 4. 数据契约

### 4.1 Schema family

| Schema | 用途 | 位置 |
|---|---|---|
| `qecgraph.research` | 当前 workspace 研究记录（27 kinds、47 typed relations） | `qecgraph/validators/schemas/research.schema.json` |
| `qecgraph.graph` | 抽取图及 SourceGraph/LemmaGraph/DataGraph 投影 | `qecgraph/validators/schemas/graph.schema.json` |
| `qecgraph.annotations` | 对抽取 store 的人工/AI 增补 | packaged schema |

未知 schema 版本被拒绝或作为不透明历史输入保留；绝不用最新字段重新解释。
包版本和数据 schema 版本独立演进。规范 schema 是打包资源；不要在仓库根创建
第二份可编辑副本。

### 4.2 Research 记录信封

`research` 记录携带：

- `schema`、`id`、`revision`、`kind`、`is_synthetic`；
- 带 kind 专属字段的 `data`；
- 把每个字段指针（`/data/<field>`）映射到证据状态和来源的 `field_evidence`；
- schema 定义的可选审核/信封字段。

规则：

- 缺失值是 `null` 并带显式 unknown 状态/原因；不是 `false`、`0` 或空列表。
- 已知值不得悄悄替换冲突的来源主张。保留冲突及其条件。
- `source_reported`、`computed_exact`、`certificate_checked` 和 `lean_build` 是不同证据类型。
- 字段级来源定位必须解析到已登记版本和逐字区间。
- 结构/schema 验证不是数学验证；通过的测试或 Lean 构建也不是。
- AI/provider 输出默认是 draft/proposal；只有显式审核决定才能发布。

### 4.3 领域对象和必需区分

领域模型有意拆分；这些概念不可互换：

| 概念 | 区分 |
|---|---|
| `code_family` / `construction` / `quantum_code` | family 或 construction 规则不是具体 `[n,k,d]` 实例 |
| `classical_code` | 经典码/seed 不是由它导出的量子码 |
| `check_matrix` | stabilizer space 与特定校验矩阵/生成元集是不同对象 |
| `distance_estimate` | 对象、check-matrix representation、metric、sector、方向、假设、方法、条件、证据 |
| `syndrome_measurement_circuit` | 电路距离和码距离不同；深度必须说明计数定义 |
| `noise_model` / `noise_model_instance` | channel 模型模板不是解析后的概率点 |
| `decoder` | 算法、软件/release、参数和版本彼此不同 |
| `experiment` | 论文报告结果不是本地执行的 `execution_run` |
| `performance_curve` / `performance_data_point` | 点属于一个 experiment/curve/metric revision；不做跨实验排名 |
| `hardware_model` / `execution_environment` | 硬件声称与模拟 CPU/GPU 环境分开 |
| `software_usage` | 提及、引用、来源报告使用和本地观察使用是不同证据等级 |
| `catalog_source` | 软件 catalog 条目不是已安装/测试的 release |
| `research_thought` | 作者原文或注明归属的解读不等于已验证结果，也不自动建立证明依赖 |

必需最低字段包括：

- `quantum_code`：code type 和 `n`/`k`（或显式 unknown 原因）、construction 引用、check-matrix representations。
- `check_matrix`：父码、校验矩阵/资产、索引/bit-order 约定、重建状态。
- `distance_estimate`：精确 subject/metric/sector、relation（`exact`/`lower_bound`/`upper_bound`/`interval`）、bounds、assumptions、method、evidence。
- `syndrome_measurement_circuit`：representation、scheduling、ancillas、rounds、boundaries、observables；带显式单位/定义的 depth metrics。
- `noise_model`：channels、locations、probability parameters、temporal/spatial correlations、boundaries；idle/loss/erasure/leakage 分开，无证据时 `unknown`。
- `experiment`：精确 code/check-matrix representation/circuit/noise-model instance/decoder/metric/source revisions。
- `performance_data_point`：experiment、noise-model instance、metric、value、coordinates、shots/discards/uncertainty、selection policy；不跨曲线插值。
- `software_usage`：usage kind、project、release（或显式 unknown），以及 source/experiment 绑定。
- `research_thought`：类别、陈述、归属、精确原文引用和论文版本引用；真实记录的陈述与引用绑定同一来源区间。

Check weight 始终绑定实际 check-matrix representation 和 check 集，包括 sector（`X`/`Z`/`mixed`）、
scope（`stabilizer`/`gauge`/`measured`）和 min/max/mean/histogram。在 symplectic
表示中，一个 `Y` 贡献一个 support 位置。

### 4.4 关系和边状态

规范关系 registry 是 `qecgraph.research.RELATIONS` / graph validation，不是这段 prose。
常见边：

- 结构：`contains`、`defined_in`、`includes`、`uses_resource`；
- 文本：`references`、`cites`、`describes`；
- 数学：`depends_on_declared`、`depends_on_candidate`、`depends_on_reviewed`、`proof_of`、`proof_of_candidate`、`normalizes_to`；
- 数据：`has_check_matrix`、`has_matrix`、`instance_of`、`generated_by`；
- 实验：`uses_circuit`、`uses_noise`、`uses_decoder`、`reports`、`supports`、`contradicts`；
- catalog：`catalog:*` 保留导入含义；它们不变成证明边。
- 思路：`addresses_refs`、`motivated_by_refs`、`extends_refs`、`contradicts_refs` 关联思路；`related_refs` 关联研究对象，目标均包含精确修订。

每条边保留 `source`、`target`、`relation`、`status` 和 `evidence`。

- `observed` — 语法/解析观察。
- `declared` — 作者或元数据声称。
- `candidate` — 假设；不是确认依赖。
- `reviewed` — 绑定显式审核和精确输入。
- `stale`、`unbound_review`、`unresolved` — 不进入默认依赖/上下文答案。

`references` 不是证明依赖。只有当证明目标显式时，证明的 `uses` 才能提升；目标是
candidate 时，提升边也是 candidate。默认遍历过滤非活动状态；显式 audit `show`
可以显示它们。引用环合法；只报告活动 reviewed 逻辑依赖 SCC 供判断。include 环是
parser diagnostic，不是数学环。

### 4.5 来源坐标和哈希

- 文件身份和资产身份使用原始 bytes 的 SHA-256。
- 文本区间使用解码后的 Unicode codepoints，半开 `[char_start, char_end)`；行号从 1 开始，末尾包含。
- 字节偏移、字符偏移、PDF 页码和源码行号绝不混用。
- 父子片段可以重叠；不要拼接片段重建原文。
- JSON canonicalization 保留显式协议标签。既有协议不被静默改标为 RFC 8785/JCS。除非 schema 声明 set，数组顺序有语义。
- 来源或资产变化使绑定审核失效；`stale` 证据保留，不通过刷新哈希隐藏变化。

---

### 4.6 文件格式与校验器

下列路径相对 `machine/`。链接的打包 schema 是权威；此表是阅读入口，不是第二套 schema。

| 产物 | 必需身份和主要字段 | 校验器 / 边界 |
|---|---|---|
| `states/<release>.json` | `schema`、`format_version=2`、`workspace_id`、`works`、`versions` | [Registry schema](../../qecgraph/validators/schemas/registry.schema.json)；只接受当前工作区格式 |
| `materials[archive_sha256]` | `archive_sha256`、`status`、`processing_completed`；完成项还绑定 source version、snapshot、tree、entrypoint、work；`original_names`、配置指纹及诊断保留来源 | Registry schema 与 workspace 校验；AI/诊断深层信封仍用各自校验器 |
| `research/` | `id`、`revision`、`kind`、`data`、证据；state 保存登记的修订哈希 | [Research schema](../../qecgraph/validators/schemas/research.schema.json) |
| `ai/proposals/` | Skill 与版本、来源快照、输出及请求来源 | Skill schema 和引文校验 |
| `retrieval/` | JSON 描述向量块的模型和范围，向量使用按哈希寻址的 float32 文件 | BM25 独立检索原文。可选索引不可用时标记 `stale` |
| `source_snapshots/` | Store manifest、原始字节、graph 及派生 views | [Graph schema](../../qecgraph/validators/schemas/graph.schema.json) 与 store 完整性检查；完整 store 和单体 JSON 仍限制规模 |

新快照身份使用来源/配置和显式 `PARSER_VERSION` / `RULE_VERSION`；包字节身份仅作来源记录。可能改变解析的依赖升级必须提升语义版本并回放来源。不得只为消除 stale 而刷新审核绑定。单材料指纹排除无关论文及 AI 凭据/模型配置。

## 5. 来源抽取

### 5.1 Parser

`qecgraph/source/parser.py` 使用 `pylatexenc==2.10` 识别结构声明，不运行 TeX。它记录：

- 文件 bytes/hash 和精确来源区间；
- sections、definitions、lemmas、theorems、propositions、corollaries、conjectures、proofs、equations、tables、figures、remarks、examples；
- labels/references、literal includes/resources、macro/environment declarations；
- 缺失/歧义 include、unsupported syntax、path escape、dynamic path 和 parse failure 的 diagnostics。

它不展开任意宏、不判断条件、不执行 TeX、不推断数学真值。partial 抽取是有效且
显式标记的快照；`--strict` 把它留在 staging，不推进 `CURRENT`。

数学块之外的 `\uses` 作为带诊断的引用保留。形式化标记保留在原始来源字节中。`\def` 和 `\let` 仅为后续可静态判定的 `\ifdefined` 标记
已定义，替换文本保持不透明。

带花括号的 `\href`、`\url` 和 `\nolinkurl` 目标保留 URL 中的百分号编码。
链接的可见文本仍按常规 TeX 解析。

解析类型还包含 abstract、algorithm、assumption、claim、notation、acknowledgments、statement_other、title、author_block 及字面 bib_entry。唯一的本地参考文献键解析到精确条目，重复键保持歧义。读取字面的 BibTeX 条目及显式引入的传统 .bbl。跨论文边要求精确匹配唯一登记的 DOI 或 arXiv 编号。片段读取附带有界字面宏定义和引用预览，不展开宏、不推断证明依赖。非 UTF-8 输入明确报告不支持编码，归档保留原字节。

### 5.2 来源块与规范化 claim

parser 的 theorem/lemma 是 **source block**：文档在固定区间说了什么。规范化
`claim` 是独立且带修订的领域对象，带显式 statement、quantifiers、hypotheses、
definitions、subject 和 evidence。两者可以多对多；相似文本或参数绝不合并身份。
`proof_of` 指向预期目标，不断言证明有效。

### 5.3 规则和 provider 提案

离线抽取器执行两遍：定位记法/结构，再应用本地措辞/列规则。它生成带精确定位和
规则版本的 `code_parameters_mention` 提案；不把表格参数提升为已验证码实例、不推断距离界、
不根据括号形状猜码类。

兼容的 corpus 交接只导出有界摘录供显式外部流程使用，本身不调用模型。独立的工作区 AI 管线（§15）可在显式启用来源上传后于 sync 调用已配置 provider。两条路径都不批准自己的草稿，也不自动转换为 research 记录。决定通过发布 state 绑定精确 proposal/source 哈希；输入变化使其 stale。

---

## 6. 审核、证据和查询资格

审核决定是一个对象，带 actor/kind、time、scope、rationale、decision 和精确输入
绑定（record IDs/revisions/content hashes、source versions、assets、proposal）。
绑定覆盖被改动记录及其显式引用闭包；无关记录的修订不会使决定失效，依赖记录变化会。
`apply` 在检查这些绑定后原子发布新修订；重复 apply 幂等。测试通过不会使审核
变成真，schema 通过也不会变成数学验证。

`claim.subject_id` 必须解析到已注册主体。悬空 subject 是验证错误；错误的主体 kind
（对距离论断而言，不是 quantum code、check-matrix representation、circuit、family、construction 或
classical code）是 warning，而不是静默消失。

证据策略：

- 硬距离过滤要求精确 subject/check-matrix representation/metric/sector、合格 relation（`exact`、
  `lower_bound`、`interval`）、足够下界，以及绑定到 claim 精确修订的当前证据。
- 只有上界绝不满足 `distance >= d`。
- 来源报告结果只在显式策略下选择；不被静默视为数学验证。
- `execution_run` 可支持本地执行结果；不覆盖论文报告值。
- 缺失/无结果表示固定范围内无匹配；不是不存在证明。

默认查询排除非活动边（`stale`、`unbound_review`、`unresolved`）和 candidate/
proposed/`needs_review` 的边或注释信息，除非显式请求。research 记录不会仅因
proposed 而被隐藏；每行携带 `review_status`，硬过滤按证据策略执行，不把草稿静默
升级为已验证。`show` 是 audit 视图，保留所有状态。任何截断都显式；来源陈述/假设
不被静默缩短。

---

## 7. 工作区事务与发布协议

### 7.1 Claim → archive → stage → validate → publish → consume

1. 在 `inputs/.processing/<job>` 下 **Claim** 收件箱文件，并写持久 job 记录。
2. 把原始 bytes **Archive** 到 `archive/blobs/sha256/`；写不可变收据（size/hash/name）。
3. 按内容 **Unpack**（TeX、gzip、tar、tar.gz、ZIP），限制 path/link/special-file/member/size/depth。拒绝 traversal、links、case collisions、forged ZIP counts、encrypted/unsupported members 和 oversized inputs。保留原始 bytes 和带哈希的展开树。
4. 只从证据 **Select entry point**：显式 config override，或唯一的带 `\documentclass` 和 `\begin{document}` 的 TeX 文件。歧义保持 `needs_entrypoint`；不按最长文件名猜。
5. **Extract** 到 store，然后 stage source/research records 和 proposals。结构性 partial 不发布为 complete；来源以 `semantic_pending`/`parse_failed` 状态可见。
6. 从所有活动状态 **Build candidate machine release**。复用的 projection 在发布前重新验证。
7. **Validate** candidate（source hashes/spans、record references、review bindings、assets、graph endpoints、SQLite、project identity）。失败 candidate 保持 `CURRENT` 不变。
8. 在 writer lock 下原子替换 pointer 来 **Publish**。
9. 只 **Consume** 成功事务的 claimed input copies；保留失败包和 receipts。恢复的名字不得覆盖更新文件。`--keep-inputs` 保留副本。

任何失败都必须让旧 release 可读、原包可恢复、没有重复事实。成功批次可包含失败；
结果是 `partial_batch`。`rebuild` 检查完整归档和 receipts，包括此前失败/未解决的包；
不把 manifest 当作论文白名单。`inputs quarantine` 把持续失败的包移到一边，不删除 bytes；
`inputs restore` 拒绝覆盖替代文件。成功提交后对应 claim 目录会被清理；失败或保留的
claim 仍可恢复，空 claim 目录在 writer lock 下清理。

### 7.2 锁、原子性和恢复

- 一个 workspace writer；`transactions.writer_lock` 使用 POSIX advisory lock，并拒绝 linked/special lock files。
- 崩溃后可留下不可变对象；只有 pointer 发布使 release current。
- store/workspace 发布可崩溃恢复：pointer switch 后的 claim cleanup 从精确 claim 重放；SIGKILL 测试覆盖该窗口。
- 锁保护本地进程，不保护 NFS 或分布式 writer。不声称掉电持久性或 multi-writer 支持。
- `human_stale` 是派生视图失败，不是机器 release 回滚。从固定 release 重新渲染。

### 7.3 增量和 watch

- 每文件 pylatexenc AST 缓存按内容寻址并验证；不使用 pickle/任意加载。parse error 不缓存。
- 每次运行重新发现 includes/resources，并重建 semantic projections、graph views、review status 和 SQLite。缓存命中绝不复活 stale review。
- macro/environment/include-set/config/processor 变化保守回退到完整解析；不信任 mtime。
- `watch` 是同一 ingest 外的内容轮询。临时文件、输出 store 和缓存被忽略；批量保存去抖。它不引入第二个 extractor。
- 对同一最终输入，增量和全量运行必须产生相同语义输出。性能声称是测量，不是保证。

### 7.4 退出行为

- `0` — 请求工作完成（或无变化）。
- `1` — 致命失败；没有新 release。
- `2` — partial batch/未解决输入/派生视图 stale，带可读报告。
- `4` — 缺少必需文件或精确查询目标。
- `5` — writer lock 或输入目标已被其他所有者占用。
- `64` — 命令用法错误。
- `130` — 被中断。
- 机器 JSON 错误带稳定 error code/message/details；人类错误写到 stderr。自动化应读结构化状态，不只从 `2` 推断语义。

---

## 8. 查询、CLI 和 MCP 契约

### 8.1 作用域

每次读取固定到一个 scope：

- `--workspace` + 可选 `--release`（workspace machine release）；
- `--machine`（严格只读 machine mount，无 workspace/human 访问）；

返回结果包含 scope identity、source/evidence status 和 truncation/absence notes。
会话在启动时固定 release/snapshot；改变 `CURRENT` 不改变现有会话。要读取新
release，重新连接/固定。

### 8.2 CLI

CLI 按名词分组（`workspace`、`query`、`review`、`mcp`、`human`、`software`、
`maintain`、`snapshot`、`inputs`、`doctor`、`version`、`help`）。扁平旧名称仍可用，带弃用提示。全局选项包括 `--json`、`--quiet`、
`--verbose`、`--debug`、`--color`、`--progress` 和 `--version`。

人类输出简洁且有状态：workspace/release、indexed/pending/failed/quarantined
计数、human-view 状态和下一步动作。`--json` 是唯一机器输出开关；TTY 检测影响
样式，不影响数据模型。错误可操作，除非请求 `--debug`，绝不输出原始 Python/OS/TOML traceback。

进度事件独立于 stdout 数据和退出码，由 CLI 在 stderr 展示；未知总量不伪造百分比。它们表示本地活动，不表示模型内部进度或科学证据。视觉规范见[进度展示](../user/advanced-usage.zh-CN.md#进度展示)。

### 8.3 MCP

- 本地 stdio，protocol `2025-06-18`；stdout 只承载 JSON-RPC，日志到 stderr。
- Store/corpus 会话暴露五个旧 `qecgraph_*` read tools。
- Research resources 枚举紧凑论文卡片；稳定 source URI 绑定版本、文件哈希、范围及类型。短标识限于固定 release。Search/list 默认精简输出，`detail="full"` 获取完整信封。
- 会话固定一个 release；工具参数不能传任意 paths/SQL/shell 或改变 scope。
- 预算：depth/nodes/results/characters；截断结果说明省略内容；预算过小返回显式错误，而不是部分根陈述。
- Read tools 绝不写、运行 TeX/paper code 或触发 Lean builds。
- 严格部署只挂载 machine 目录。`human/`、`inputs/` 和私人笔记 必须不可读。MCP roots 不是访问控制机制。

类型化 JSON envelope（`ok/data` 或 `error/code/message/details/scope`）在适用处由
Python、CLI 和 MCP 共享。MCP protocol errors 和 business-query errors 保持可区分。

---

## 9. 人类视图

`human/` 只保存 ThoughtsGraph 问答 Markdown，每篇登记论文（`work_id`）一个文件：
`human/YYYY/MM/一作姓_文章前两个词_thoughts.md`。
本布局已随 **v0.6.3** 发布；v0.6.2 使用旧布局。

- 正文固定包含 [Human.md](../reviews/review-2026-11-12/Human-2026-11-11.zh-CN.md) 的九个问题、AI 回答、逐字原文依据和版本/行号。
  缺少答案时明确显示尚无可用回答；匹配来源修订的 `research_thought` 记录也会显示，
  保留实际审核状态。AI 提案始终是 `proposed`。
- 文件最前面依次放 YAML 字段 `tags`、`link`、`title`、`author`。`tags` 只放论文主要
  主题词，空格转连字符；`author` 按论文顺序列出作者；`link` 为公开 HTTP(S) URL 或 null，
  缺失列表用 `[]`。格式遵循 [Obsidian properties](https://obsidian.md/help/properties)
  和 [tags](https://obsidian.md/help/tags)，不再添加图类型、release、审核状态标签。
- 显式登记的标题和 canonical URL 优先。字面 TeX 标题命令（包括 `\begin{document}` 后的 RevTeX 元数据）优先于来源绑定的 AI `paper` 元数据；不执行宏。共享元数据解析同时供论文卡片和 human 使用。没有主题时从标题中的已知 QEC 短语生成 tags；未知日期不取导入时间或 `\today`。
- 目录年月优先取原始包名中的现代 arXiv 编号：`arXiv-2611.12971v2.tar.gz` 对应
  `2026/11/`。`YYMM` 表示首次提交年月，后续 v2 等版本仍用同一年月；规则见
  [arXiv 编号格式](https://info.arxiv.org/help/arxiv_identifier.html)。解析在本地完成，
  不根据文件名推断或改写论文身份、来源版本。非 arXiv 包名回退到来源日期；包名年月冲突
  时保留未知，不随意选一个文件名。
- sync/rebuild 把归档回执的原始包名写入 machine release 的 `materials[*].original_names`。
  旧库可通过一次空收件箱 sync 补齐，无须为了包名重抽来源；渲染只读固定快照，不读实时回执。
- 文件名只取第一作者姓氏（last name）和标题按空白分隔的前两个词，YAML `author` 仍保留
  完整作者列表。逗号分隔的“姓, 名”形式取逗号前部分；其余取最后一个词，保留常见姓氏
  前缀（如 `van Loock`）和连字符，去掉 Jr./Sr. 等后缀。未分词的单词姓名原样保留。
  危险字符转下划线。未知作者和标题
  用 `UnknownAuthor`、`Untitled_Paper`；未知年月用 `unknown`，仅知年份时为
  `YYYY/unknown/`。同名论文在 `_thoughts.md` 前增加 work ID 的短哈希，避免覆盖。
- 同一 work 的多个版本共用一份文件，回答逐条标明来源版本。书目信息选择最小的显式数字
  版本 `vN`；没有数字版本时按来源 ID 确定性排序，不声称它是最新版本。
- `human/` 不再生成索引、实体页、原文预览、manifest、墓碑页或私人笔记目录。
  管理状态和未完成发布日志位于 `.qecgraph/human-{published,pending}.json`。
  个人笔记放在 `human/` 之外；生成笔记在重建时会被替换。
- 迁移依据旧生成器的管理历史识别旧布局：**直接删除整个旧 `human/`，包括旧 `notes/`，
  不读取其中内容，也不建立备份**。新内容先准备完成，再清理旧目录。没有管理记录的外部
  vault 会被拒绝。后续重建只删除过时的受管理笔记和空年月目录，拒绝覆盖未登记的同名文件。
- 发布仍是逐文件原子，不是整个 vault 的原子事务。中断时报告 `human_stale`，重新运行
  `qec-graph human build` 完成发布和清理，machine release 不回滚。渲染不会调用 AI。
- 人类笔记只是单向阅读视图，不作为查询、MCP 或 embedding 输入，也不成为权威数据；
  更正通过 machine 层的显式结构化修订完成。

---

## 10. Lean 路线已移除

数据库专注于论文来源与知识查询。Lean 命令、构建集成、实验项目和运行验证材料已移除。论文原文中出现的形式化标记仍按原文保留。

---

## 11. CodeGraph 参考与第三方归属

本项目独立实现其 Python 架构。它参考 [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)
的 commit `f72c9d2efb14454ff4f9fd7b8460abd82f19a287`（MIT，Copyright (c) 2026
Colby Mchenry），用于 extraction/storage/resolution/query/watch 边界。没有复制
上游代码，也没有上游性能数字适用于本项目。下面的决策记录总结该参考；详细检查
（包括 `6560052a6f856855d3f71eee838fd66ccfa4285d`）保留在 Git history 中。

映射摘要：

- code symbol graph → source spans、claims、entities、evidence 和 typed relations；
- tree-sitter/AST → `pylatexenc` structural extraction（不是 TeX 引擎）；
- reference resolution → labels/includes/citations 加显式 typed edges；
- graph query/context → 有界、证据过滤的 traversal；
- watch/sync → 同一 ingestion pipeline 外的内容轮询；
- AI tools → 一个只读 query layer，通过 CLI、Python 和 MCP 暴露。

[leanblueprint](https://github.com/PatrickMassot/leanblueprint) 注解（`uses`、
`proves`、`lean`、`leanok`）保留为作者观察/声称；它们不是 proof-term dependencies、
build evidence 或 semantic equivalence。

---

## 12. 不变量和失败案例

### 12.1 可测试不变量

| ID | 不变量 |
|---|---|
| G01 | 每个 source block 精确等于其区间的归档源码切片。 |
| G02 | 注释/verbatim labels 和 commented includes 绝不进入真实索引。 |
| G03 | 嵌套 labels 保持不同；重复 labels 有歧义，绝不静默消解。 |
| G04 | `references`、declared dependencies、candidates 和 reviewed dependencies 保持不同。 |
| G05 | 非活动 input edge 不能被 promotion 或 query 复活。 |
| G06 | resource hashes 在 review matching 前固定；内容变化使 review stale。 |
| G07 | `\leanok`/`formalizes` 绝不产生 Lean-verified 或 semantic-equivalence 状态。 |
| G08 | 表格参数不被抽取提升为已验证码实例。 |
| G09 | 重建相同 input/tool state 幂等，且不修改 source bytes。 |
| G10 | Graph、views 和 SQLite 指向同一 snapshot；所有边端点有效。 |
| G11 | 显式 data relations 可扩展 matrix, check-matrix, metric and evidence context。 |
| G12 | Partial extraction、truncation、unresolved targets 和 stale reviews 可观察。 |
| G13 | 失败发布保持旧 release 可读、输入可恢复。 |
| G14 | 人类笔记和私人笔记不作为知识输入。旧 human 文件按 §9 迁移规则直接删除，不读取内容。 |
| G15 | Workspace/MCP 会话不能混用两个 releases。 |

### 12.2 必需失败案例

- 证明提到背景定理但没有声明依赖：保留 `references`；只有 candidate edges。
- 重复 label：返回歧义；要求精确 ID。
- distance estimate 只有上界：不得满足 lower-bound filter。
- source/asset/review input 变化：标 stale，保留旧证据，从默认答案排除。
- 归档包含 traversal、links、special files、forged ZIP count 或不支持的 member：在 materialization 前拒绝。
- 包永久不受支持：保留、报告并允许 quarantine；绝不删除或伪造抽取。
- `CURRENT` 损坏或 writer lock 被持有：报告精确路径/所有者状态，不写入。
- 渲染器在发布后失败：保留 machine release，报告 `human_stale`，重新渲染。
- MCP 请求要求 path/SQL/shell 或不同 scope：拒绝；不要重新解释为 query。
- 查询无结果：说明固定 scope 和 absence semantics；不要说定理不存在。

---

## 13. 当前限制和非目标

| 领域 | 状态 |
|---|---|
| 真实论文 corpus | 固定 replay 中有六个带版本 arXiv 来源；不是全面文献 corpus |
| LLM extraction | 配置 provider，用于规范化、符合条件的结构恢复和默认开启的提案；需要凭据，校验 schema/证据，不声称质量 |
| Chart/curve digitization | 未实现；值需要显式证据 |
| PDF/OCR | 未实现；LaTeX 源是受支持输入 |
| Vector/semantic retrieval | 可选本地词法向量或 OpenAI-compatible embedding，BM25/cosine 混合检索；质量须按语料实测 |
| Distance algorithms | 小码枚举/验证；没有通用大码 solver 或 certificate bridge |
| Lean formalization | 已移除 |
| Platforms | POSIX（macOS/Linux 已验证）；Windows 不支持/未验证 |
| Distribution | 独立 GitHub Releases 和本地 wheel/sdist；公开 PyPI 发布受门控/手动，不假设 |
| Concurrency | 单 writer，本地 POSIX 文件系统；没有 multi-writer/distributed transactions |
| Docker | Linux Compose 和 macOS isolation 已验证并记录 caveats；不声称通用 image build |

这些是当前 release 的限制，不是用看似合理的值填补缺口的许可。

---

## 14. 验证和变更规则

- 测试套件和 `tools/reproduce*.py` 是可执行检查；`validation/README.md` 列出当前检查。
- `python -m unittest discover -s tests -v`、`python tools/reproduce.py --out build/reproduce` 和 CLI/MCP 检查是标准本地门禁。
- CI 只运行 ruff、mypy、advisory pyright 和 unit 测试层。integration/contract 测试、覆盖率、distribution、installed-wheel、Docker 和隔离检查是本地/手动检查。
- 任何 identity、source coordinates、evidence semantics、review binding、publication order 或 MCP scope 变化都要求新 invariant test，并在兼容性受影响时写迁移说明。
- 只有本文、实现、测试和 validation claim 一致时，设计变更才算完成。不要把第二份矛盾设计页留在活动文档树中。

---

## 15. AI 接入

即使已有凭据，来源上传也默认 **false**；只有显式设置 `[ai].allow_source_upload = true` 才启用 provider 请求，已有明确选择保持原值。共享 client 限制包含重试的实际请求数（`max_batch_requests`，默认 128）和累计已报告费用（`max_batch_cost_usd`，默认 20）。缺价及在途请求使美元上限无法成为硬保证。Dry-run 不联网，报告限额和未知费用。AI 审核在 writer 锁内登记，仅新固定的 release 可见；审核身份仍是自声明。

AI 是 `qecgraph/llm/` 下的可选本地编排层。`init` 只写 provider 模板，不调用模型、
不抽取文献包。`sync` 由本地解析器处理普通包。配置 provider 后可协助解决多入口歧义，
或恢复符合条件的结构解析失败。日常语义提案默认开启，接入点默认为 OpenRouter，
模型为 `deepseek/deepseek-v4.1-flash-1017`。模板中的 API key 留空，由用户填写；
缺少 key 时仍能本地导入，不发起 AI 请求。已有明确配置保持原值，省略的接入点、模型和
提案开关使用与新配置相同的默认值。

normalizer 接收有界 inventory 和原文片段，返回 normalization plan；assembler
按计划复制原始字节生成派生 `main.tex`。原始压缩包和 source tree 仍是权威来源，
需要审核的方案会保留归档包并等待入口。发布版本通过哈希绑定归一化 TeX 和来源映射。
来源读取会标注派生坐标，并单独返回对应的原始路径和区间。AI 抽取写出可审核的
`qecgraph.ai.proposal` 产物，绝不自动提升为 verified 记录。

Provider 在 `qecgraph.toml` 中选择（OpenAI、Anthropic、OpenRouter 或本地 CLI
适配器）。请求经过 schema 校验，仅对瞬时错误重试，受预算约束，按内容哈希缓存，
并记录 model/prompt/run 来源。`[ai].max_parallel_packages` 限制已登记文献包的并发抽取，
登记、发布和收件箱清理仍串行执行。API key 会脱敏，配置文件以 `0600` 创建。

| 组件 | 状态 |
|---|---|
| Init 与 provider 配置 | 已实现；`init` 不联网 |
| Provider/client 重试、schema、缓存 | 已实现 |
| 版本化 skill packs | 已实现 |
| 来源映射规范化 | 已实现于歧义文献包 |
| 软件优先的结构回退 | 已实现于符合条件的原始 TeX 入口，块分类保留为 proposed |
| 定理/假设/数据/思路 proposal | 显式允许上传并配置凭据后写入 `machine/ai/proposals`；审核决定会记录，但不会自动转换为权威研究记录 |

四个语义抽取 skill 使用 v7：共用安全 system、带文件映射的编号纯文本证据，以及证据之后的 skill 任务。provider 前缀缓存收益尚未测量。请求包含主投影及已选入口登记的 TeX 文件集合，
包括嵌套正文与附录。每个文件都核对归档和来源快照，以明确行号、独立路径、哈希和
原始字节映射提供；不混入压缩包中的无关文件。模型直接使用提供的行号，引用解析到
对应文件，逐字引文仍须是一个原文区间内的连续子串，生成包装和拼接引文会被拒绝。
显式允许来源上传且 `extract_proposals = true` 后，多文件论文自动走此流程，无需手动合并文件。预算约束完整请求。超过输入上限时按论文的 TeX 标题边界重试，包括最深的子章节。每段保留全局文件与行号。成功段带覆盖范围及失败信息发布，后续 sync 重试失败段。单段仍超过输入上限时保持待处理。
响应未通过 schema 或原文校验时，抽取最多追加一次纠错请求，携带相同证据，并将
被拒绝的输出明确标为不可信数据。完整请求预算和全部校验再次生效；成功提议的来源信息
保留两次请求 ID、prompt 哈希与用量。再次失败则保持待处理；无效响应不会作为成功结果
缓存或发布。传输错误仍使用原有的独立重试次数上限。

### 15.1 软件优先的正文抽取实施计划

**状态：已实现。** 下表记录实施与验收顺序。

| 步骤 | 改动 | 验收条件 |
|---|---|---|
| 1 | 记录触发条件、来源证据、发布与迁移规则 | 保留归档权威、固定发布读取和现有原文查询行为 |
| 2 | 增加共用阅读投影 | 两种抽取共用来源块图谱；阅读文本隐藏已识别的排版和引文，保留公式并隔离参考文献，原文视图保留逐字切片 |
| 3 | 增加带版本的结构回退 skill 和程序校验 | 离线假 provider 能标注有行号的正文区间；拒绝遗漏、重叠、虚构字段、错误锚点和不确定计划 |
| 4 | 接入工作区的严格发布流程 | 仅在符合条件的解析失败后调用模型；方案绑定原始字节和快照身份，分类保留 proposed，重建复用已校验方案 |
| 5 | 接入阅读搜索、来源状态和配置 | CLI 与 MCP 读取同一固定发布。原文搜索继续可用；关闭语义提案时，普通导入调用模型零次 |
| 6 | 跑完整、安装版 CLI 与真实归档验收，再合并 | Git 中逐步可审阅，推送分支并在检查通过后合并到 `main` |

回退在归档校验和入口选择之后执行。首版处理原始 UTF-8 入口，要求正文边界独占行且唯一，
并且没有外部 TeX 正文输入。结构扫描或解析失败可触发回退。入口未定、归档或路径不合法、
依赖缺失、边界歧义或证据超过预算时，保留为可恢复的工作区失败。多入口归一化沿用独立的
方案校验和来源映射规则。

模型只读取有界的带行号正文，返回有序区间和块类型。程序检查正文完整覆盖，校验章节与
参考文献的字面锚点，并从归档复制每个切片。回退能提取字面引用键和章节标题，标签命令及
其他未支持的元数据保留在原文中。未分类内容仍然可见。快照绑定已校验方案、来源摘要、skill 版本、模型和 prompt 哈希。
读取时标明 AI 建议的分类及其来源，禁止由此产生已审核主张或逻辑依赖。

结构重试遵循现有的单写者和发布协议。provider 缺失、拒绝、方案无效或验证失败时保留归档、
旧投影和待重试认领。已提交的方案可以针对同一份原文离线复用。解析器或输入变化后先重跑
本地解析，使解析器修复可以取代回退投影。单论文 store 命令继续使用现有解析器。

`[ai].structure_fallback` 控制新的回退调用，并遵循已有的启用、provider、凭据和来源上传配置。
日常语义抽取由 `[ai].extract_proposals` 控制，默认值为 `true`，显式设置 `false` 可跳过
这些 skill。模型结果仍为 proposed。实现用离线夹具覆盖成功、拒绝、禁用、格式错误、
篡改和重建。

## 16. 可搜索知识体系与实施路线

本节整合 2026-11-11 的 `QEC_KNOWLEDGE_MCP_SUMMARY.md` 和
[Guangqi 保留的需求](../reviews/review-2026-11-12/Human-2026-11-11.zh-CN.md)。原始总结保存在 Git 历史中，它是工程输入，
不是功能已经实现的证据。沿用现有工作区、ID、Schema、审核流程和 CLI。

### 16.1 研究问题与四种图视图

服务保留全部登记来源，同时组织 QEC 假设、定义、定理、构造、矩阵、距离声明、
syndrome 电路、噪声（包括 idle/loss）、decoder、硬件保真度与实验表现。
已有研究类型覆盖这些对象；缺失值与尚未提取的字段必须明确标注。

| 视图 | 内容 | 边界 |
|---|---|---|
| SourceGraph | 文档、章节、顺序、来源区间、引用、版本 | 引用不等于证明或支持某个具体结论 |
| LemmaGraph | 定义、假设、陈述、证明与类型化依赖 | 作者声明、候选、审核与形式化依赖分开 |
| DataGraph | 码、呈现、距离、电路、噪声、decoder、实验与软件 | 同文出现不代表属于同一实验 |
| ThoughtsGraph | 问题、动机、方法/结果、直觉、假设、结论、开放问题、反直觉发现、支线结论 | 作者陈述与解读分开，绑定确切来源证据 |

四种图共享身份与来源，不是四个独立数据库。抽取快照仍保留 source/lemma/data
三个命名投影；ThoughtsGraph 由版本化 `research_thought` 记录、类型化查询和生成页面
实现，当前不会另行输出 `thoughtsgraph.json` 快照。来源区间将这些记录连接回论文原文。

#### ThoughtsGraph 契约

ThoughtsGraph 保存有来源依据的研究意图与解读。九个类别和阅读流程见
[研究思路参考](../user/data-and-search.zh-CN.md#研究思路--thoughtsgraph)。
每条记录表达一项思路；不同类别或不同来源主张分别保存，使证据和修订可以独立演进。

| 字段或关系 | 契约 |
|---|---|
| `category` | 九个受支持研究思路类别之一 |
| `statement`、`source_quote` | 非空陈述和逐字原文引用；`author_explicit` 要求二者相同 |
| `attribution` | `author_explicit` 或 `editorial_inference`；归属不代表审核通过或数学有效 |
| `source_ref`、`field_evidence` | 精确 `paper_version` 修订；真实陈述与引用绑定同一登记来源区间，发布时核对原文 |
| `relation_to_prior` | `extends`、`strengthens`、`contradicts`、`unrelated` 或 null；是记录的解读，不是自动确立的科学结论 |
| `addresses_refs`、`motivated_by_refs`、`extends_refs`、`contradicts_refs` | 其他 `research_thought` 记录的精确修订，附字段证据 |
| `related_refs` | 允许的研究类型的精确修订，如构造、实验或 decoder；解析块仍通过来源证据访问 |

`extract_thoughts` v7 产生 `qecgraph.ai.proposal` 包，默认可搜索（`include_proposals=false` 可排除），以
`research_thought_proposal` 条目暴露，与已发布研究记录分开。明确审核与记录导入是
两个步骤，AI 结果或批准都不会自动创建规范记录。记录和提案保留实际审核状态；
候选解读关系需显式开启遍历，引用和思路关联不会转为证明依赖。

[Skill](../../qecgraph/llm/skills/extract_thoughts/SKILL.md) 给出类别边界、原文阅读步骤、
归属与精确行号规则以及完整示例。条件随结果保留，缺失类别明确写入 `unresolved`。
v3 新增可选 `paper` 元数据：标题、按顺序排列的作者、日期、公开
链接和主要主题。每项均附逐字引用和来源行号，日期和 URL 另有程序校验；没有 `paper`
的旧包仍可读取。跨记录关系需要另行整理。程序验证格式与引用，不据此保证解读的科学
正确性或元数据的真实性。v4 读取带行号的多文件证据，引用只保留可搜索的关键短句，
建议少于 240 字符；新抽取中超过 480 字符的思路或元数据引文，或超过 18 条核心思路的
批次，在缓存前被拒绝。
解释与适用条件放在回答里，并可附上下文引用。旧包保留原引文长度，仍可读取。
v0.6.2 使用 v1；v2 细化步骤，v3 扩展输出 schema；v4 改进证据输入与引用要求，
不改变输出字段。
v5 要求生成的回答、元数据、主题词、未解决项统一使用英文；所有 AI 输出在缓存与发布前
检查中文字符。数学符号和带重音的拉丁姓名仍可使用。human 的九问、标签和缺失提示，
以及内置软件目录也统一为英文。Sync 检查旧提案，含中文的 skill 会重新抽取，已经完成的
英文结果继续复用。仅工具升级导致 snapshot 变化时，复用还必须核对相同入口、
来源树和完整证据文件哈希，并在新快照上重新校验引用。复制的提案保留原模型、prompt、
skill 版本和 proposed 状态，在 `provenance.source_rebindings` 中记录旧路径与哈希；
审核记录不会自动换绑。替换结果使用新的不可变路径和哈希；历史 release 默认保留，只有明确
要求时才清理。重提取失败时保留 pending，不发布被拒绝的内容。原始证据逐字保留，
不能为满足语言要求悄悄翻译。human 生成器拒绝包含中文的元数据或回答，避免混合语言笔记。

human 文件夹没有独立的 AI 抽取步骤。ThoughtsGraph 的提议视图和人类生成器读取固定
machine release 中同一个哈希绑定的 `extract_thoughts` 包。Sync 先发布机器结果，再由
程序生成 Markdown；重建 `human/` 可以离线进行，不改变原提议。
`[ai].max_parallel_packages` 控制跨论文并发；同一论文内各 skill、发布与人类生成保持顺序。

当前来源绑定的 AI 提案和已登记记录汇入 `human/YYYY/MM/*_thoughts.md`（见 §9），
按论文展示九个问题、回答、原文、归属和来源。
生成器与查询从不读取私人笔记。某个类别没有记录表示覆盖缺失，不代表论文不存在该类
思路；不得捏造作者未披露的推理过程。

### 16.2 存储、检索与阅读单位

存储不可变论文/记录/资产，用小证据单元定位，阅读时补齐定义、假设、图注与方法。
论文入口提供目录和源文件；章节提供连续文本及子节点。保留父 ID、顺序、来源版本、
快照和 codepoint 区间。不拼接可能重叠的片段来重建全文。原始 TeX 与派生阅读文本
同时可用，尚无语义记录的来源也能检索与阅读。

指定版本不得静默回退；缺失时报告可用绑定。内部 `qec://` 资源 ID 与公开引用 URL
分开，canonical citation 只能使用登记的真实公开 URL。
没有公开 URL 的本地论文仍能通过研究工具访问。

### 16.3 检索、枚举与覆盖

默认关键词检索使用缓存 BM25、QEC 词规范化、来源绑定摘要和重叠排除。仅正文无命中时回退标题上下文；除非指定 kind，默认排除整文件/章节/元数据/书目。论文轮换改善多样性。这是词法相关性，不是语义验证。

关键词、可选向量候选、类型化字段/关系查询共用固定 release。
混合排序合并候选并去重，类型和来源硬过滤先于排序。相似度不能满足参数或距离条件。
结构化查询通过明确分页枚举所有匹配，top-k 发现不能称为穷尽。
结构化结果为空时仍提供原文检索路径，报告字段缺失、解析失败、版本缺失与未知证据。

距离下限查询只使用 exact/lower/interval 证据，单独上界不满足要求。
码距与电路距离分开。性能比较绑定码、呈现、电路、噪声实例、decoder、指标、来源、
选择方法和不确定性。缺失目标点不能补造；报告值、读图、插值和模拟值分别记录。
未知、未报告、未提取、排除、失败和不适用不混淆。软件版本只记录论文实际报告的版本。

向量投影可重建、可选，并绑定文本哈希、release、模型身份/版本、维度和归一化配置。
同维度不代表模型可互换。索引构建属于离线写事务；查询不重建索引或抽取论文。
本地词法向量基线可离线运行，外部 embedding 要显式配置 provider，披露身份和覆盖。
计算出向量不意味着已证明语义检索质量。

### 16.4 少量稳定接口与任务上下文

CLI 默认八个 research 工具；显式 legacy workspace 与 store/corpus 接口继续兼容，通用 profile 共用核心：

| 研究工具 | 职责 |
|---|---|
| `qec_list_papers` | 紧凑论文卡片，包含元数据来源与来源版本 |
| `qec_search` | 关键词/向量/混合发现，支持类型和精确来源过滤 |
| `qec_fetch` | 读取论文目录、源文件、章节、occurrence 或记录 |
| `qec_get_context` | 为定理、性能、构造、思路组装有界上下文 |
| `qec_query_codes` | 枚举精确码/参数/距离条件 |
| `qec_query_performance` | 枚举绑定实验的报告点 |
| `qec_trace` | 按证据/状态过滤的有界类型化关系 |
| `qec_status` | 来源登记、处理状态、记录/字段/检索覆盖 |

通用 profile 提供 `search(query)` → `{results:[{id,title,url}]}` 和
`fetch(id)` → `{id,title,text,url,metadata}`，用 MCP text JSON 返回。
它暴露带真实公开引用 URL 的完整登记证据单元。超出预算明确失败，不能截断后宣称全文。
研究工具额外返回来源/修订/快照、证据、未知项、冲突、范围、分页和截断。
声明输出 Schema 并校验成功结果。stdio 协议继续固定为 `2025-06-18`，
参考链接里更新的版本不自动改变实际协议。

上下文用途标明缺失组成：定理 → 定义、假设、证明、依赖；性能 → 指标和实验绑定；
构造 → 参数、约定、矩阵/资产；思路 → 作者陈述和关联证据；
上下文选择是结构化与显式的，
不宣称推断出了全部数学前提。

### 16.5 维护、隔离与规模

全部材料默认登记，不设发表/质量门槛。解析失败保留归档身份和可检索元数据，
覆盖信息注明全文不可用。`init` 仍只初始化配置，`sync` 导入，`rebuild` 核对归档。
发布后才消费认领输入。哈希缓存包含 parser/schema/skill/model/index 配置，
变化只使受影响的投影失效，不覆盖旧 release。

索引和上下文只消费登记的机器数据。`human/YYYY/MM/*_thoughts.md` 是单向视图，
私人笔记放在 `human/` 之外。严格服务只挂载机器数据；整个工作区的 shell 访问会破坏该隔离。

本地仍以 Python/文件/SQLite/FTS5 起步。PostgreSQL/pgvector、共享 HTTP 与独立 worker
是未来部署选择，不是当前要求。假设一万篇、每篇 25–100 单元、768–1536 维 float32，
仅向量数值约为 0.77–6.14 GB（十进制），不含正文、索引、资产、多版本和备份。
这是规划计算，不是容量或延迟实测。先测单元/资产分布、带过滤召回、p50/p95 延迟、
并发、增量/重建成本和磁盘峰值，再决定后端。不为每个检索单元生成 Markdown 文件。

### 16.6 分阶段交付与验收

| 阶段 | 当前状态 | 交付内容 |
|---|---|---|
| 1. 设计整合 | 已完成 | 保留 Human.md，整合总结，提交实现契约 |
| 2. 原文阅读 | 已实现 | 目录/完整源文件/章节、严格版本、覆盖、通用 search/fetch |
| 3. ThoughtsGraph | 已实现 | 九类思路、类型化证据、校验 AI 提议、检索、人类视图 |
| 4. 检索 | 已实现；语义质量未测 | 离线版本化向量投影、混合排序、原文回退 |
| 5. 任务上下文 | 已实现；结构性选择 | 按用途组装、类型化 trace、精确查询别名、缺失组成报告 |
| 6. 评测 | 机制已验证；科学问答待评测 | 可复现检索/上下文基线、可得真实来源检查、明确记录限制 |

每阶段单独测试并提交，随实现更新真实状态。不把路线图或生成 fixture 当成科学结果。
PDF/OCR、读图提取、自动证明和千篇/万篇生产验证不属于本轮实现。

阶段 2 已实现：论文/文件/章节读取、严格版本选择、字段/来源覆盖和可选 MCP profiles。完整源文件从登记快照读取并核验哈希，包含解析块之外的文本。

阶段 3 已实现：九类思路、精确引用记录及关系、`extract_thoughts` 提议和人类思路页面。显式允许来源上传并启用 `[ai].extract_proposals = true` 时 sync 运行四个抽取 skill（含思路）；缺失某个 skill 的批次在下次 sync 补提取。已经完成的英文 skill 不会因版本变化自动重跑；旧中文提案会按英文输出要求重新抽取。`qec_search(include_proposals=true, kind="research_thought_proposal")` 发现候选思路而不提升为记录；精确 `qec_fetch` 保留 proposed 状态。

阶段 4 已实现：`[retrieval].enabled = true` 在 sync/rebuild 发布前生成哈希绑定投影。本地模型为离线词法基线；`openai_compatible` 支持明确配置的外部 embedding，使用环境变量凭据和上传授权。模型版本、维度、分词与分块配置绑定缓存；新增来源复用未变化分块向量；可选索引构建失败发布 stale 状态，关键词检索继续可用，来源或记录完整性失败仍保留旧 release。研究搜索支持 keyword/vector/hybrid、排序前过滤、分页、显式回退与校验重建。向量区间属于派生检索文本，权威引用坐标来自 fetch。

阶段 5 已实现：按用途组装上下文、类型化双向追踪、当前证据绑定的分类/校验权重/噪声过滤、比较条件分组、缺失/未知/冲突报告和分开的原文候选。记录枚举保留分页；原文候选不能满足硬条件。

阶段 6 有 `tools/reproduce_knowledge.py` 的机制检查和 `tools/eval_retrieval.py` 的真实论文来源绑定检索 smoke。执行命令和限制见[验证索引](../../validation/README.zh-CN.md)。它们不是独立标注的科学 QA。单次运行结果应放入带日期的验证证据，不作为永久能力声明。

### 16.7 收益证据

在同语料、同模型、同预算下比较 A（能放进上下文的直接阅读）、B（原文搜索加阅读）、
C（B 加领域字段、关系和任务上下文）。记录实际工具输入输出、证据位置、正确性、
带过滤召回、上下文完整性、未知/冲突处理、返回字符/token、延迟、失败和维护成本。
合成离线回归只验证机制，不能证明模型回答质量。未来整理 50–100 个真实 QEC 问题
可作起点，不是行业标准，也不是已完成的 benchmark。

### 16.8 可用性验收与发布约定

**Implemented** 只表示可执行机制存在。**Usable** 还要求固定版本上至少五篇真实论文、50–100 个自然问题的独立人工标注，以及下表检查。目前各阶段均**尚未达到 Usable**：八问 smoke 的锚点在查看检索结果后选择，仅为工程证据，且自动权威实体归并尚未实现。不含适用码或实验的论文必须保持明确不适用/未知，不为满足数量指标编造记录。

| 阶段 | 可重复的真实数据检查 | 仍需人工验收 |
|---|---|---|
| 1. 设计 | 文档命令、链接、双语契约通过；每项能力指向实现和限制 | 退役兼容之前确认事务/迁移决策 |
| 2. 原文阅读 | 在副本的固定 release 运行 `reproduce_knowledge.py --machine`；返回引文逐一对应预期文件/哈希/区间，零错误版本替代 | 对照每篇原论文检查标题/作者身份及章节/摘要/算法/假设覆盖 |
| 3. ThoughtsGraph / 领域数据 | 四种 proposal 均可枚举和精确读取；schema/来源校验通过；无关 release 变化不改变 human 页面字节 | 每个 skill 至少盲审 30 条输出，标注缺失前提、实体/实验绑定和拒答；按 skill 评估 precision，不用总数量代替 |
| 4. 检索 | 用冻结的独立标注 cases 运行 `eval_retrieval.py`；同 release 报告 literal/BM25 的 recall@5/10、MRR@10、响应大小和延迟 | 发布目标：≥5 篇论文、≥50 个问题上 recall@5 ≥ 0.80，并人工分析漏项；smoke 结果不满足此门槛 |
| 5. 任务上下文 | 回放直接阅读/搜索/上下文用例，指定精确证据坐标及预期缺项；不混入 stale、错误版本或未请求 candidate 依赖 | 对适用的码/性能问题，将显式记录及条件与人工标注对照；基于证据的实体归并验收前不声称自动记录可用 |
| 6. 评测 | 保留 commit、解释器/依赖、release/数据哈希、命令、指标、失败和未执行项；只比较相同输入 | 独立审核者签认科学答案及各 skill 判断；来源保真必须 100%，零私人笔记泄露、零提议自动提升 |

宣称 Usable 前，应与审核者**先于评测调优**冻结每种 skill/任务的 precision 和完整性目标。阈值或判断缺失时，即使工程测试通过也仍为待验收。人工身份/批准另行记录，不能把本地 AI review 的自声明当成人类认证。

真实工作区只复制登记的 machine 树用于只读评测，不复制/读取 `human/`、私人笔记或凭据，报告写在副本外。使用仓库已验证的 Python 环境：

```sh
python tools/reproduce_knowledge.py --machine /path/to/copied-machine --out build/knowledge-real.json
python tools/eval_retrieval.py --machine /path/to/copied-machine --cases validation/retrieval_qa.json --out build/retrieval-eval.json
```

自带 cases 只检查 smoke；独立人工金标使用各自冻结的路径与 release。不得悄悄重建原库或刷新审核哈希以通过检查。前后数字只比较可比的方法；当前代码的 literal/BM25 对照不等于历史代码回放。

普通变更可以独立于版本 tag 合入 main。建议维护者采用每周最多一次普通发布、紧急安全修复例外的政策，尚需维护者采纳。未来破坏性 machine 迁移必须先有可审阅 dry-run、备份/恢复方案，并在执行前获得明确批准；§9 中此前确认的旧 human 不读取、不备份删除仍是限定例外。本轮不创建版本/tag。

## 附录 A — 决策记录（替代当前行为的独立 ADR）

| 决策 | 当前解决 | 背景 | 本次评估的替代方案 | 原因 / 取舍 |
|---|---|---|---|---|
| **D1 — 一个 workspace，一个 writer** | Immutable release + POSIX lock + atomic pointer；没有 distributed writer。 | 本地恢复必须可审计。 | 分布式写者或原地可变 state。 | 保留锁与不可变发布；并发需先验证 CAS/恢复协议。 |
| **D2 — 证据分层，不是评分** | Source/claim/review/computation/build 状态保持分离；默认过滤排除非活动状态。 | 主张和证据含义不同。 | 单一 confidence/verified 分数。 | 单值会掩盖未支持假设和失效证据。 |
| **D3 — 只读 agents** | 固定 scope、有预算的 CLI/Python/MCP reads；没有 path/SQL/shell 访问；只有 stdout protocol。 | Agent 需要有界可重放读取。 | 任意文件系统/SQL 工具。 | 固定资源减少范围错误，machine-only 挂载实现访问边界。 |
| **D4 — 人类视图隔离** | 从固定 machine release 为每篇论文生成一份 thoughts；human 不作为输入；逐文件原子发布、旧布局清理与 `human_stale` 恢复。 | 私人笔记不能成为机器证据。 | 双向 vault 导入。 | 单向渲染防止混入；保留明确批准的旧 human 删除例外。 |
| **D5 — Lean 集成已移除** | 工作区专注论文知识库。 | 论文原文保持不变。 | 保留实验执行能力。 | 移除构建和工具链依赖。 |
| **D6 — CodeGraph 仅供参考** | 架构比较，不复制代码，不导入性能声称；保留归属。 | 代码智能可提供架构参考。 | 引入引擎或继承性能承诺。 | 工作负载不同；保留归属并独立测量本项目。 |
| **D7 — 兼容优先于重写** | Store/corpus 继续受支持；machine 迁移保留数据；human 布局重置在 §9 明确说明。 | 旧记录和审核哈希必须可读。 | 立即替换所有 API/格式。 | 兼容会保留重复；批准迁移后再退役。 |
| **D8 — Schema 所有权单一** | Packaged schemas 是规范；未知版本不重新解释。 | 可编辑的重复 schema 会漂移。 | 同时维护根目录和打包副本。 | 打包资源负责校验；拒绝未知版本。 |

## 附录 B — 主要参考

1. [SQLite: appropriate uses](https://www.sqlite.org/whentouse.html)
2. [SQLite FTS5](https://www.sqlite.org/fts5.html)
3. [DuckDB Parquet](https://duckdb.org/docs/stable/data/parquet/overview)
4. [Docker storage](https://docs.docker.com/engine/storage/)
5. [pylatexenc 2.10 LatexWalker](https://pylatexenc.readthedocs.io/en/v2.10/latexwalker/)
6. [CodeGraph](https://github.com/colbymchenry/codegraph)
7. [leanblueprint](https://github.com/PatrickMassot/leanblueprint)
8. [Error Correction Zoo data](https://github.com/errorcorrectionzoo/eczoo_data)
9. [OpenAI MCP search/fetch](https://developers.openai.com/api/docs/mcp)
10. [MCP tools (deployed protocol)](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
11. [Microsoft Learn MCP](https://learn.microsoft.com/en-us/training/support/mcp-developer-reference)
12. [Context7 clients](https://context7.com/docs/resources/all-clients)
13. [DeepWiki MCP](https://docs.devin.ai/work-with-devin/deepwiki-mcp)
14. [Anthropic tool design](https://www.anthropic.com/research/writing-tools-for-agents)
15. [PostgreSQL text search](https://www.postgresql.org/docs/current/textsearch-controls.html)
16. [pgvector](https://github.com/pgvector/pgvector)

历史理由和替代页面只在 Git history 中保留；不属于当前文档树。
