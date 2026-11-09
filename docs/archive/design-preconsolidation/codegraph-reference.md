# 07｜CodeGraph 参考架构与 qec-graph 映射

> **Status: Historical.** Superseded by [the consolidated design](../../design/DESIGN.md). Keep for provenance; internal links and paths may describe the pre-consolidation layout.


## 1. 参考对象和使用范围

本文参考明确的开源项目 [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)，不把所有名为 CodeGraph 的工具视为同一实现。
它的官方 [How It Works](https://colbymchenry.github.io/codegraph/core-concepts/how-it-works/) 描述了 AST 抽取、SQLite 存储、引用解析、图查询和面向 AI 的上下文组织。
本文采用这一职责划分，具体数学语义仍由本项目规定。

CodeGraph 从源代码提取符号与关系；qec-graph 从论文源码提取来源结构，再结合显式领域记录形成研究知识图。
函数调用与证明依赖的证据标准不同。借用软件架构不能让普通引用、相邻段落或相似名字自动成为数学证明。

本包使用自己的 Python 实现。已查阅的固定 CodeGraph 提交、模块和许可证记录见
[ADR 0001](adr/0001-codegraph-reference.md)；本项目只参考架构。

## 2. 从上游流水线到本项目职责

| CodeGraph 的职责 | qec-graph 对应职责 | 原型落点 | 验收目标 |
|---|---|---|---|
| AST extraction | 提取 LaTeX 结构和准确位置，不执行 TeX | `parser.py` | 按资料语法增加受测适配器 |
| Symbol storage | 保存节点、边、来源与全文索引 | `store.py`、SQLite/FTS5 | 多文档 registry 与版本化实体 |
| Reference resolution | 解析 label、include、书目键和人工选择器 | `graph.py` | 跨文档、跨版本显式解析 |
| Graph queries | 查询依赖及其反向影响 | `query.py` | 类型、证据和作用域策略 |
| Context assembly | 选取完整原文、证明、假设和数据证据 | `query.context` | 预算内完整陈述与跨资料上下文 |
| Change monitoring | 由输入变化触发重建和失效 | `watch` 和 `ingest --incremental` 共用解析与发布流程 | [增量与恢复](../11_INCREMENTAL.md) |
| AI tools / MCP | 让 AI 调用同一查询层 | 当前为 CLI/Python/JSON | P4 的只读 MCP |

上游使用 tree-sitter 分析代码。本包使用 [pylatexenc 2.10 的 LatexWalker](https://pylatexenc.readthedocs.io/en/v2.10/latexwalker/) 取得 LaTeX 节点与位置；它不是完整 TeX 引擎。
不能把“用了 AST”解释为已处理所有宏展开、条件分支、外部包或数学语义。
每个解析适配器必须说明支持语法、诊断规则、坐标系和回归样例。

## 3. 对象映射：哪些可以借用，哪些必须重定义

| 程序代码中的概念 | 本项目的对应概念 | 必须保留的差异 |
|---|---|---|
| 文件、模块 | source file、source version、work | 论文版本和文件出现不是同一身份 |
| 函数、类、变量 | 定义、陈述块、规范化 claim、领域对象 | 原文块与数学对象分开，可多对多 |
| 符号名称 | 项目作用域内的 label 与独立实体 ID | 同名跨文档不能自动合并 |
| 调用、导入 | references、includes、依赖声明等不同关系 | `references` 不等于 `depends_on` |
| 定义位置 | 来源资产哈希和准确 source span | PDF 页码、字节和字符偏移要区分 |
| 调用影响分析 | 对已记录依赖做反向遍历 | 结果只是已知关系范围内的潜在影响 |
| 函数上下文 | 陈述、假设、定义、证明和适用证据 | 不能为省 token 删掉必要量词或假设 |
| 实际编译信息 | Lean declaration、构建与依赖导出 | 文献语义对应还需独立审核 |

SourceGraph 是来源视图；LemmaGraph 是数学陈述、证明和依赖视图；DataGraph 是实例、表示、运行和证据视图。
三者共享节点身份和边语义，不能各自复制一份 claim 并独立修改其参数。
静态代码图可以作为未来 software artifact 的来源，但 `implements`、`generated_by` 等桥接关系需要明确版本和证据。

[leanblueprint](https://github.com/PatrickMassot/leanblueprint) 提供有用的作者标注：`uses` 指定所引用的数学标签，`proves` 绑定证明目标，`lean` 指定 Lean 名称，`leanok` 表示作者认为形式化已完成。
本包分别保存这些观察或声明。它们不提供实际 proof term 依赖、构建证书或原文与 Lean 类型的语义等价证明；验收依据见 [05_LEAN.md](../05_LEAN.md)。

## 4. 模块边界与扩展路径

| 路径 | 当前职责 / 建议新增职责 | 实现约束 |
|---|---|---|
| `qecgraph/parser.py` | 已有：只读解析、位置、诊断 | 不承担领域参数推断或人工审核 |
| `qecgraph/graph.py` | 已有：节点、边、解析与视图 | 依赖提升保留证据类别与失效状态 |
| `qecgraph/store.py` | 已有：快照、归档、SQLite、完整性验证 | 输入绑定和发布顺序不能由入口绕过 |
| `qecgraph/query.py` | 已有：search/show/deps/impact/context | 所有传输层复用同一状态策略 |
| `qecgraph/splitter.py` | 已有：source-only 入口与片段清单 | 调用 ingest；不复制解析或存储逻辑 |
| `qecgraph/cli.py` | 已有：CLI 参数、JSON、退出码 | `qec-graph` 为同一 CLI 的别名 |
| `qecgraph/registry.py` | work/version/entity 注册 | P1；不得用显示标题做唯一键 |
| `qecgraph/review.py`、`validators/` | 审核事务、类型及领域验证 | P2；验证结果不能冒充人工决定 |
| `qecgraph/incremental.py`、`watch.py` | AST 复用与内容变化调度 | P3；允许保守回退全量重建 |
| `qecgraph/mcp_server.py` | 只读工具传输 | P4；复用检索和可信度逻辑 |
| `lean/` 与声明导出适配器 | 固定工具链的实际证据 | P5；字段和信任边界按 05 |

保持模块小而明确；只有当真实职责需要拆分时才引入额外层，不为模仿上游目录重写已验证的原型。
SQLite、JSON 与以后可能增加的索引通过同一快照身份关联，MCP 不成为新的权威数据库。

## 5. 固定参考版本和许可证检查

采用上游具体实现前，在 `docs/design/adr/` 或第三方清单中记录以下信息：

- 仓库准确 URL、完整 commit hash、实际检查日期，以及所参考文件与符号。
- 对应提交的许可证文件路径、文件哈希、适用范围与需要保留的声明。
- 使用方式：仅参考公开设计、独立实现算法，或实际复制／修改代码。
- 直接依赖版本、其许可证以及本项目需要附带的 notices；有多重或文件级许可证时分别检查。
- 本地修改、升级理由、受影响的语义回归和可回退的版本。

不要在没有读取对应提交的许可证前填写许可证类型或宣称可以原样复制。
`main`、网页最新版本和浮动依赖可用于发现变化，不能替代可复现实现所用的准确版本。
参考文档 URL 可保留为导航，同时把影响设计决定的版本与本地 ADR 关联。
实现前的这项检查是工程工作，不是要求先向用户请求一个抽象的采用许可。

## 6. 在 QEC 资料上评价效果

先建立少量固定研究问题及人工预期：来源定位、完整陈述、距离上下界筛选、定义变化影响、Lean 状态查询。
分别测量召回是否覆盖目标、硬条件是否误匹配、来源是否可定位、证据状态是否保留、输出是否超预算。
空查询和截断查询也需要预期结果；不能用“有答案”代替“答案有正确依据”。
若考虑 embedding、图数据库或代码图导入，先针对这些失败样例比较收益及维护成本。
不把 CodeGraph 的性能或 token 节省宣传数值移植成本项目的实测结果。

阶段验收条件见 [08](../08_ROADMAP_ACCEPTANCE.md)；实际运行证据见 [验证报告](../../validation/REPORT.md)。
