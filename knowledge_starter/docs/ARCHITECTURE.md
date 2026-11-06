# 推荐架构与实施边界

## 1. 先围绕你希望回答的问题设计

同一知识库需要支持三类任务：阅读研究、筛选数值对象、构造形式化证明。它们共享来源和稳定 ID，但需要不同查询方法。

| 问题 | 所需信息 | 查询方法 |
|---|---|---|
| 某论文如何证明距离下界？ | 固定版本、定理、完整假设、证明与依赖 | 词法/语义检索后返回完整定理上下文 |
| 哪些 ordinary HGP 码满足 n 范围和距离下界？ | 明确构造类别、整数参数、下界证据 | SQL 过滤，再附证据与矩阵 |
| 如何让 Lean 使用这条定理？ | 定义类型、量词、假设、声明名、imports、依赖和版本 | 精确声明索引及依赖闭包 |
| 哪条 SEC 在给定条件下 LER 更好？ | 码表示、线路、噪声、decoder、指标、采样和区间 | 先验证实验可比，再查询结果表 |

向量搜索解决的是语义接近，不能代替硬条件校验或证明。证据应位于具体论断上；只在长笔记末尾列参考文献，无法让 AI 判断每个数值从哪里来。

## 2. 四层结构

1. **原始资产**：按版本保存 PDF、完整 TeX、补充材料、上游代码快照。每件资产有字节哈希、格式、来源和取得日期。
2. **经整理记录**：一个对象一个记录，使用稳定 ID；保存定理、定义、构造、实例、表示及实验关系。说明文字可以单独用 Markdown/LaTeX。
3. **计算和形式化证据**：矩阵、生成配置、逻辑 witness、求解证书、实验结果、Lean 源码及构建记录。重要结果本身也要持久保存。
4. **查询投影**：从前几层生成 SQLite、全文、向量和依赖索引。任何投影都能追溯输入版本并重新构建。

每一字段有一个权威来源。若书目由 Zotero 管理，只同步约定的书目字段；定理假设和矩阵参数由知识记录管理；已实现的形式化类型和证明依赖由 Lean 源码导出。人工说明不是第二份可独立编辑的参数数据库。

## 3. 版本与来源

区分 `work_id`（一篇工作）、`source_version_id`（特定版本）、`entity_id`（数学或实验对象）、`revision`（对象的一次状态）、`sha256`（准确文件内容）。论文更新时保留旧版本；某次查询结果可以固定到一个 Git 提交和资产清单。

原文定位包含论文版本，以及至少一种足以找回原文的位置：PDF 物理页序、印刷页码、节路径、定理号、公式号、TeX 文件与标签、PDF 坐标。明确坐标和页序的起点。检索 chunk 编号由分块器决定，不作为永久文献定位。

符号表采用带作用域的记录，例如同一个 k 在量子参数、经典码维数和 OSD 自由变量数中可能含义不同。保留原文表示和规范化表示，人工修订不得覆盖原始抽取。

## 4. 推荐技术选择

| 职责 | 第一阶段 | 扩展条件 |
|---|---|---|
| 阅读和引用 | Zotero 或现有阅读器 | 保持引用键稳定，书目能导出 |
| 记录与代码 | Git + JSON/YAML + Markdown/LaTeX + .lean | Schema 随版本迁移 |
| 大资产 | 独立持久目录 + 哈希清单 | 多机共享时采用对象存储；可选一种大文件版本工具 |
| 精确查询 | SQLite | 并发写入或统一服务时 PostgreSQL |
| 全文查询 | SQLite FTS5 + 中英术语别名 | 增加中文分词和符号索引 |
| 语义查询 | 暂不强制 | 确认关键词漏检后加入 embedding；统一服务可用 pgvector |
| 批量仿真表 | CSV 起步，较大规模用 Parquet | DuckDB 直接查询 Parquet |
| 定理规划 | 结构化映射 + Markdown/LaTeX | 需要证明依赖展示时加入 leanblueprint |
| 环境 | Python 环境和独立 Lean/Lake 项目 | Docker/Compose 固定任务环境，不承担数据唯一存储 |

每项新技术应解决已经观察到的问题。文件中的有类型关系即可构成初步知识图谱；先用关系表和依赖遍历，复杂图查询成为实际瓶颈后再评估图数据库。

## 5. 面向 AI 的稳定接口

建议逐步实现这些函数或 CLI，再按需要包装为 HTTP/MCP：

```text
search_sources(query, filters)
query_code_instances(construction, n_range, distance_lower_bound, evidence_policy)
get_claim(id, revision)
get_source_context(source_version_id, locator)
get_dependencies(id, relation_types, depth)
get_formalization(claim_id, project_revision)
```

返回对象包含结果、来源、约定、证据级别和快照 ID。一次定理查询至少补齐陈述、所有假设和所用定义；一次实验查询补齐线路、噪声、decoder 和错误事件。不要将孤立的半条定理当作完整上下文。

写操作统一提交结构化变更，再进行 Schema、引用和数学检查。AI 提议的内容保留为 draft；人工语义审核与自动计算结果各自记录，不假造审核身份。

## 6. 分级录入，控制维护成本

- **收集级**：所有相关论文先保存来源、版本和少量主题标签。
- **研究级**：正在使用的论文再抽取少量重要定理、构造、数据表及准确位置。
- **复现级**：需要比较性能或参数的对象补矩阵、程序配置、运行数据和验证证据。
- **形式化级**：优先选择复用率高、表示稳定的定义与引理，准备 Lean 映射和依赖。

每次提交检查变化的记录和受影响依赖；较重的距离搜索、全量仿真与整个 Lean 项目构建按里程碑运行。升级依赖使用专门提交，记录旧、新结果差异。保留一小组真实研究问题作为查询回归集，检验是否找对对象、满足硬条件、带全假设和来源。

## 参考

- [Error Correction Zoo 数据组织](https://github.com/errorcorrectionzoo/eczoo_data)
- [SQLite 适用场景](https://www.sqlite.org/whentouse.html)
- [SQLite FTS5](https://www.sqlite.org/fts5.html)
- [pgvector 混合检索](https://github.com/pgvector/pgvector#hybrid-search)
- [DuckDB Parquet](https://duckdb.org/docs/stable/data/parquet/overview)
- [Lean 证明验证](https://lean-lang.org/doc/reference/latest/ValidatingProofs/)
