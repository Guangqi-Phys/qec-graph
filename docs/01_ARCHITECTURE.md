# 01｜架构、权威来源与部署边界

本文是供 Codex 执行的设计约定；标为“目标”的能力必须经过实现和验收后才能对外宣称可用。
图的边语义见 [02](02_QEC_GRAPH_SPEC.md)，文件契约见 [04](04_DATA_FORMATS.md)，操作流程见 [06](06_MAINTENANCE.md)。

## 1. 从研究问题决定结构

系统需要同时支持阅读、数值对象筛选和 Lean 构建准备。三者共享来源与身份，但使用不同的判断依据。

| 研究问题 | 必须返回 | 查询方式 |
|---|---|---|
| 论文怎样证明一个下界？ | 固定版本、完整陈述、假设、定义、证明和依赖出处 | 全文召回后取关系闭包 |
| 哪些码满足构造、长度与距离条件？ | 精确实例、参数论断、上下界及证据、矩阵表示 | 结构化过滤后核对证据 |
| 怎样在 Lean 中复用引理？ | 对应类型、声明、imports、依赖、版本与信任信息 | 精确声明查询和构建记录 |
| 两次解码实验能否比较？ | 表示、线路、噪声、解码器、错误事件、采样估计量 | 先检查可比性，再比较结果 |

语义相近只是召回依据。距离条件、定理适用条件和实验可比性需要显式字段及证据。
“未找到”应同时说明查询范围和索引状态，不能自动解释为不存在。

## 2. 当前交付与目标系统

| 层级 | 当前实现 | 扩展边界 |
|---|---|---|
| 原文抽取 | 受支持的 LaTeX 结构、来源位置、版本注册、跨文档固定查询 | 根据实际资料增加语法适配器 |
| 知识图 | 三视图、独立 claim、严格领域校验、显式迁移与审核事务 | 继续补有来源的 QEC 领域记录 |
| 查询 | 单 store FTS5、corpus 子串查询、证据过滤、只读 MCP | 向量索引与常驻服务未实现 |
| 数学检查 | CSS 对易/秩/有限距离、实验结构及可比性检查 | 大码距离求解、证书桥接未实现 |
| Lean | 固定工具链，实际 Bool 例的类型、常量和公理导出 | 原文语义需独立审核；HGP 距离未形式化 |
| 部署 | 本地 Python/Lean；research Compose 模板未运行验证 | 验证容器镜像 |

`knowledge_starter/schemas/record.schema.json` 的 `0.1.0` 是旧样例格式。
`schemas/graph.schema.json` 的 `qecgraph.graph.v1` 是当前抽取图格式。
它们承担不同职责，都不是完整 QEC 领域模型；新规范不能通过改一个版本字符串伪装成兼容升级。

## 3. 四层存储，一字段一个权威所有者

| 层 | 权威内容 | 修改规则 |
|---|---|---|
| 原始资产 | 特定版本的 PDF、完整 TeX、补充材料、上游代码归档 | 入库后不可变；新版新增对象 |
| 人工整理 | JSON 记录、显式关系、审核 sidecar、人工校正 | Git 版本化；新修订保留历史 |
| 执行证据 | 输入快照、矩阵、witness、证书、运行结果、构建日志 | 已发布结果不可变；重跑产生新记录 |
| 查询投影 | SQLite、全文索引、向量索引、图视图、检索片段 | 由前述输入重建；禁止独立修正 |

本项目选择 **JSON 作为人工结构化记录的唯一权威格式**。YAML 只作填写模板或外部导入格式。
YAML 导入完成后生成 JSON，后续修改 JSON；不允许 JSON 和 YAML 各自编辑同一对象。
Markdown 解释动机和推导；LaTeX 保存原文及可读数学；Lean 保存实际形式化实现。
说明页中的参数表由记录生成，或明确注明仅是带引用的叙述，避免形成第二个参数数据库。

| 字段组 | 权威所有者 | 其他位置的职责 |
|---|---|---|
| 标题、作者、DOI、引用键 | 指定的书目系统或 `source_work` 记录，二选一 | 导入器只更新获授权的书目字段 |
| 原文陈述及位置 | 固定 source version 的原始资产 | 抽取图复制片段并标定位 |
| 规范化假设、量词、结论 | 人工整理的 claim JSON | AI、Markdown、SQLite 引用或投影 |
| 码身份与参数论断链接 | `code_instance` JSON | 参数数值附支持论断，查询表不自行判断 |
| 矩阵、列序与逻辑代表 | 对应 presentation 及其资产 | 别的表示通过显式映射关联 |
| Lean 实际类型与依赖 | 固定提交的 `.lean` 源码及实际构建导出 | 人工映射只声明对应关系 |
| 一次实验观测结果 | 该 run 的不可变原始统计和估计配置 | 图表、摘要和索引可重算 |
| 审核结论 | 带审核者、范围和输入绑定的审核记录 | 不从“测试通过”推断有人审核 |

这是项目的设计决策。外部工具的不同格式可以保留在导入边界，不获得第二份写入权。

## 4. 一个 typed graph，三个查询视图

`graph.json` 是某次抽取输入的图快照；其节点、关系和状态由来源、sidecar、catalog 共同生成。
`sourcegraph.json`、`lemmagraph.json`、`datagraph.json` 是同一图的投影，不分别维护独立事实。

| 视图 | 主要对象 | 主要用途 |
|---|---|---|
| SourceGraph | 文件、节、原文块、公式、图表、资源、引用 | 回到出处、检查边界和版本 |
| LemmaGraph | 定义、原文定理、证明块、依赖与形式化映射 | 规划证明、取完整上下文、追踪失效 |
| DataGraph | 构造、实例、表示、资产、实验和证据 | 精确筛选、复现与证据审计 |

CodeGraph 通常描述程序模块、符号、调用和导入关系。其静态分析结果可作为本图的代码证据来源。
它不自动知道程序实现的数学对象，也不能把函数调用直接解释成定理依赖。
未来接入代码索引时，增加软件实体和显式 `implements`／`generated_by` 等版本化关系即可。
无需为每个视图先部署一个图数据库；当前关系表与有界遍历已能表达这些关系。

原文 theorem／lemma 节点和规范化 claim 是不同对象，可多对多关联。
当前可用显式 `describes` 关系连接；新关系名应按图规格和迁移程序增加。
`references`、作者声明的依赖、候选依赖、人工审核依赖必须保持不同语义。
`proof_of` 只绑定证明块的目标；`\leanok` 或 `formalizes` 都不提供 Lean 验证证书。

## 5. 可实施的目标目录

下面是扩展知识库时的目录约定，不宣称本包已经创建全部目录或对应命令。

```text
records/source_work/<id>.json
records/source_version/<id>.json
records/definition/<id>.json
records/claim/<id>.json
records/family/<id>.json
records/construction/<id>.json
records/code_instance/<id>.json
records/presentation/<id>.json
records/experiment/<id>.json
records/evidence/<id>.json
records/formalization/<id>.json
annotations/<project-id>.json
assets/original/<source-version-id>/manifest.json
assets/original/<source-version-id>/project/
assets/matrices/<asset-id>/matrix.json
assets/runs/<run-id>/
evidence/<evidence-id>/
notes/<topic-id>.md
lean/QEC/
schemas/
migrations/
tests/queries/
derived/<project-id>/CURRENT.json
derived/<project-id>/snapshots/<snapshot-id>/
```

路径是存储位置，稳定 ID 是对象身份。文件名应由安全编码器生成，不能直接拼接任意论文标签。
小型 JSON、源码、Schema 和说明进入 Git；大资产放持久目录，并将完整资产清单纳入版本记录。
大型资产可以迁移到对象存储，记录保存稳定 asset ID、哈希和受管理的存储位置。
已经发表或审核依赖的资产不原地覆盖；重命名和搬迁不应改变数学对象 ID。
原型的 `snapshots/.../sources/` 只保存实际读取的 TeX，`assets/` 保存已解析的图和 bibliography 资源。
完整原始工程仍需另存，包括未读取的 `.sty`、`.cls`、脚本和补充材料。
**`--catalog knowledge_starter/records` 仅导入 JSON 记录，不复制它们引用的矩阵、脚本和证据。**
因此备份或迁移时必须一起保存完整 `knowledge_starter/`，不能只带走生成的图。

## 6. 单机起步与升级触发条件

本地 Python + SQLite + FTS5 是起步部署方案。SQLite 适合本地应用，其写入应串行组织。[1]
每个 store 通过本地文件锁串行化写者。多个读取者各自固定 snapshot ID，避免一次任务混读两个快照。
工作区还会串行处理收件箱认领、归档和发布。
不同论文先使用各自 store；跨论文查询通过 [版本注册表](09_CORPUS.md) 固定到同一个 corpus revision。

出现持续写争用、多台服务共享写入、集中权限或远程事务需求时，再评估 PostgreSQL。
升级依据是测得的工作负载和协作需求，论文数量本身不构成阈值。
迁移后若数据库接管某类字段，必须显式转移所有权并停止该字段的文件双向编辑。
FTS5 提供分词和 BM25 工具，但中文、缩写与数学符号仍需项目自己的召回测试。[2]
先补中英术语、别名和搜索文本；关键词漏检成为实际问题后，再评估向量检索。
向量索引记录模型、维数、归一化及输入哈希；不同模型空间分开构建。
大批结果可使用 Parquet，DuckDB 可直接查询这类文件；是否采用取决于已有数据操作需求。[3]

## 7. 容器与 AI 接口

research 容器负责抽取、数值检查和索引；Lean 容器固定 Lean/Lake 环境并导出构建证据。
两者可作为 Compose 按需任务，不要求常驻服务。PDF 解析服务只在确有 PDF 工作流时添加。
本包已有 research CLI 的 `Dockerfile` 和 `compose.yaml`，未执行 Docker；Lean 镜像尚未定义。
永久资料保存在 bind mount 或持久 volume，不能只放容器可写层；缓存与成果分开。[4]
容器不是权威存储，也不会自动解决随机数、硬件、算法版本和数学语义的复现问题。
镜像 digest、依赖锁文件和 Lean toolchain 必须来自实际选定和测试的环境。

AI 可通过 CLI、Python 或 [只读 MCP stdio](12_AI_MCP.md) 调用同一查询层，结果保留快照和诊断。
精确实例条件用 `codes`；Lean 证据用 `lean-status` 和 corpus 查询。未提供 HTTP 服务。
写操作统一成为待审核的 JSON 变更；通过结构、来源和语义检查后再发布新的查询快照。
AI 读取论文和注释作为数据，不执行其中的命令，也不据此改变系统工作流程。

## 8. 实施优先级

先用十至二十个真实研究问题建立回归集，再补最影响这些问题的记录和接口。
收集级保存来源；研究级补关键定义和论断；复现级补资产及执行证据；形式化级补 Lean 映射。
不要求每篇论文一开始都具有相同深度，也不让新增技术替代缺失的来源与数学约定。
实施步骤和验收边界以 [08](08_ROADMAP_ACCEPTANCE.md) 为准。

## 主来源

1. [SQLite 官方适用场景](https://www.sqlite.org/whentouse.html)
2. [SQLite FTS5 官方文档](https://www.sqlite.org/fts5.html)
3. [DuckDB Parquet 官方文档](https://duckdb.org/docs/stable/data/parquet/overview)
4. [Docker 官方存储文档](https://docs.docker.com/engine/storage/)
5. [可参考的数据组织实例：Error Correction Zoo](https://github.com/errorcorrectionzoo/eczoo_data)
6. 本包旧设计与运行样例：`knowledge_starter/docs/`、`knowledge_starter/records/`。
