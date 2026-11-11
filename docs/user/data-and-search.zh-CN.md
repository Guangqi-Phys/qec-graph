# 数据与检索

> **状态：当前（0.6.x）。** 研究记录、证据策略和查询契约。

> **中文** · [English](data-and-search.md)

QEC Graph 保存原始来源、从来源抽取的图，以及带版本的研究记录。搜索结果指向
实际提供查询的机器 release，因此之后可以把结果追溯到同一份数据。

## 本页目录

- [工作区保存什么](#工作区保存什么)
- [研究记录类型](#研究记录类型)
- [按关键词、来源或结构化字段检索](#按关键词来源或结构化字段检索)
- [AI proposals](#ai-proposals)
- [读取和复现查询结果](#读取和复现查询结果)

> [!IMPORTANT]
> 字段标记为 `known` 只表示已绑定证据，不表示论文定理已获数学验证。
> 距离界、审核状态和 Lean（延期）是彼此独立的证据维度。

## 工作区保存什么

| 层 | 内容 |
| --- | --- |
| 原始来源 | `archive/` 按 SHA-256 保存提交包字节，并保存带原始文件名和认领时间的收据。registry 跟踪来源树、选定入口、处理结果，以及已知时上游 work/version。抽取失败仍可有已登记的 `source_artifact`。 |
| 来源图 | 解析后的 LaTeX 文件与块，如定义、定理、证明、公式、表格和图片。节点带来源路径、行/字符区间和内容哈希。边表示结构、引用，以及明确限定的证明或依赖关系。 |
| 研究记录和资产 | QEC 对象、实验和软件的类型化记录，以及精确修订链接和字段级证据。矩阵、电路或数据文件等登记资产带字节长度和内容哈希。查询只暴露绑定到合格记录的资产。 |
| Release 和状态 | `machine/` 保存不可变 release、来源快照、记录和查询索引。运行状态报告包计数及生成视图是否最新。 |
| 人类视图 | `human/Index.md` 和 `human/generated/` 是派生的 Obsidian 页面。个人笔记在 `human/notes/`。工作区 MCP 从 `machine/` 读取。 |

导入论文会为受支持 TeX 创建来源图，并可对识别出的参数记法生成
`code_parameters_mention` 提案。提案带来源位置和未解决字段。结构化码参数、距离界、
实验条件和性能点依赖显式记录和证据。来源链接保留论文实际报告的内容。
数学检查和语义审核携带独立证据。Lean 在 0.6.x 中延期；任何实验 Lean fixture
都不是验证结论。[图语义和数据契约](../design/DESIGN.zh-CN.md#4-数据契约)

## 研究记录类型

代码示例使用自带的 13-qubit hypergraph-product（HGP）示例说明
`qecgraph.research` 记录。下面的实验使用假设设置和计数。
[自带 HGP 示例](../../examples/paper/sections/hgp.tex)

### 论文和码

| 记录 kind | 示例 |
| --- | --- |
| `paper_version` | 保存 `work_id`、`upstream_version` 和 `source_snapshot_id`。arXiv 论文的 `v2` 和 `v3` 可以在同一 work ID 下有不同来源快照。 |
| `code_parameters_mention` | 在受支持段落如“A CSS quantum code has parameters `[[13,1,3]]`”中，导入可提议 `n: 13` 和 `k: 1`，保留完整记法和来源区间，并让 `code_ref` 和 `distance_interpretation` 保持未解决。 |
| `classical_code` | 描述经典输入，如带 `2 × 3` 校验矩阵的二元长度三重复码。 |
| `code_family` | 描述普通 hypergraph-product 码这一类。一个 family 可包含许多不同 seed 选择的实例。 |
| `construction` | 指定从两个 repetition seed 构建 HGP checks 的配方。可重建的 `matrix_recipe` 包含域、形状、索引、bit order、公式、recipe 版本和精确 seed 修订。 |
| `quantum_code` | 标识由这些 seed 构建的特定量子码，带 `n: 13`、`k: 1`，并链接其 construction、check-matrix representations 和 distance estimates。 |
| `check_matrix` | 记录实例的具体表示，如 `H_X`/`H_Z` 校验矩阵资产和 qubit 顺序。check-weight 统计指定 check 集、sector 和范围，如 X stabilizers。 |
| `distance_estimate` | 绑定对象和度量。联合 CSS 距离 3 时，`relation: "exact"` 有 `lower_bound: 3` 和 `upper_bound: 3`。weight-3 逻辑 witness 支持 `relation: "upper_bound"` 且 `lower_bound: null`。 |

这些记录让你在 `code_ref` 解析后，从论文记法追到具体实例，再检查矩阵和
距离证据。历史 HGP 示例包含有限枚举检查。

### 电路、实验和结果

假设论文描述该码在三轮 syndrome 下的模拟，并报告 `p = 0.005` 处的逻辑失败率。

| 记录 kind | 示例 |
| --- | --- |
| `syndrome_measurement_circuit` | 把码表示链接到三轮 syndrome 电路，提供时带电路资产和边界条件。深度测量给出计数规则和单位，如 `layers` 中的 `two_qubit_layers`。 |
| `noise_model` | 描述错误发生位置，如每个 CNOT 后的两 qubit depolarizing noise。来源明确时记录是否包含 idle errors、loss、erasure 和 leakage。未解决 channel 字段保持 `null`。 |
| `noise_model_instance` | 把模型绑定到电路并保存 `reported_coordinates`，如 `{"p": 0.005}`。来源明确该轴值对门或其他 channel 的含义时，填写 `resolved_channel_parameters`。 |
| `decoder` | 绑定解码算法和本实验设置，如带指定加权规则的 minimum-weight perfect matching。 |
| `hardware_model` | 记录论文明确说明的假设，如哪些 qubit 可交互、所有 CNOT 是否同时长。 |
| `experiment` | 链接论文修订、码、表示、电路、噪声模型和解码器。精确链接标识报告结果属于哪个电路和解码器。 |
| `metric` | 定义事件、分母和单位，如每个 accepted shot 的错误最终逻辑 parity，以分数表示。每轮速率有自己的 metric 定义。 |
| `performance_curve` | 把同一 performance curve 上的 data points 分组，如三轮实验的逻辑失败率对 `p`。它链接精确实验和 metric 修订。 |
| `performance_data_point` | 链接实验、噪声实例、metric，可选 performance curve。10,000 shots 中 20 次失败、零丢弃时值为 `0.002`。真实记录中，报告值、计数和置信区间在提供时都需精确来源定位。 |
| `execution_environment` | 描述实际运行环境，如操作系统、CPU 架构、解释器和依赖版本。 |
| `execution_run` | 把具体执行绑定到环境和执行证据，如保存的日志和输出哈希。本地复现可用 `experiment_ref` 链接回报告实验。 |

合成 fixture 展示部分数据如何保存。`demo:noise-point` 有轴坐标，但 channel
映射未解决。链接的 `demo:point` 的 `value: null`，因为 fixture 未提供逻辑
失败率。[链接的合成 fixture](../../tests/fixtures/performance_context.synthetic.json)

### 软件和算法

| 记录 kind | 示例 |
| --- | --- |
| `algorithm` | Minimum-weight perfect matching（`MWPM`）标识 `decoder` 可引用的方法。 |
| `software_project` | `software:stim` 标识 Stim 项目及其仓库。 |
| `software_distribution` | `pypi` 生态中的 `stim` 包通过 `project_ref` 链接回项目。 |
| `software_release` | 保存精确包版本，如 manifest 固定该版本时 `version: "1.2.3"`。其 `distribution_ref` 标识所属包。 |
| `software_usage` | 引用可用 `usage_kind: "citation"`。若方法节明确说明 Stim 模拟了某实验，`source_reported_use` 绑定该论文和实验；`locally_observed_use` 绑定真实运行。版本未知时 `release_ref: null`。 |
| `software_catalog_observation` | 记录带日期的观察，如元数据刷新得到仓库的 `archived` 和 `disabled` 标志。字段证据链接记录 API URL 和响应哈希的 catalog 来源。 |
| `catalog_source` | 标识 catalog 或上游元数据来源及其检查范围，例如自带 seed 记录其覆盖并非穷尽。 |

导入自带 catalog 会创建 catalog、project、distribution 和 algorithm 记录。
usage 记录需要论文或运行实际使用内容的证据，包括已知版本。
[自带软件 catalog](../../qecgraph/catalog/software_catalog.seed.json)

### 字段、修订和证据

每条 `qecgraph.research` 记录有 `schema`、稳定 `id`、精确
`revision`、`kind`、`data`、`field_evidence` 和 `is_synthetic` 标志。
引用如 `{"id": "demo:source", "revision": "r1"}` 指定精确来源修订。证据也可
指定来源位置及抽取/检查限制。下面的合成代码示例中，fixture 提供 qubit 数，
construction 仍未知。

```json
{
  "data": {"n": 13, "construction_ref": null},
  "field_evidence": {
    "/data/n": {
      "status": "known",
      "source_ref": {"id": "demo:source", "revision": "r1"},
      "method": "synthetic_fixture"
    },
    "/data/construction_ref": {"status": "not_extracted"}
  }
}
```

未知字段用 `null`。`not_extracted` 表示抽取未完成；`unresolved` 表示链接有
歧义；`not_reported` 要求对来源指定部分做带日期检查；`not_applicable` 和
`conflicting` 记录字段为何没有单一值。默认工作区查询过滤 synthetic 记录和
过期 provider 批准；proposed/draft 记录仍可见并携带 `review_status`，但绝不当作已验证。
旧 `qecgraph.record` 记录也可携带 claims、证据和实验性
Lean 映射字段。Lean 延期，不属于受支持 0.6.x 流程；见
[设计说明](../design/DESIGN.zh-CN.md#10-lean延期不支持)。
research schema 列出受支持 kinds、每种 kind 必填字段，以及可空 `{id, revision}`
链接形状。`x-qec-target-kinds` 注解描述允许的目标 kind。JSON Schema 校验器还
检查证据元数据、受管理资产 ID，以及矩阵 recipe、码参数、界方向、测量单位和
速率等可移植值约束。QEC Graph 检查相关值的一致性、精确目标修订是否存在、
指针是否解析到该值，以及记录是否一致。

[研究记录 schema](../../qecgraph/validators/schemas/research.schema.json) · [corpus 记录 schema](../../qecgraph/validators/schemas/record.schema.json)

## 按关键词、来源或结构化字段检索

CLI 和 MCP 使用同一套只读工作区工具。在 MCP 客户端中使用这些名称，或把 JSON
参数传给 `qec-graph query-tool`。

| 目标 | 工具 | 如何开始 |
| --- | --- | --- |
| 查找术语、标签、来源或记录 | `qecgraph_search` | 传 `query`，可选 `kind`、`limit`、`offset`。工作区搜索大小写无关。用 `kind: "code_parameters_mention"` 聚焦记法提案。 |
| 搜索阅读视图 | `qecgraph_search` | 设置 `view: "reading"`，或运行 `qec-graph search TERM --workspace . --view reading`。结果带有界摘录和原文 occurrence。 |
| 读取记录并跟踪链接 | `qec_get_entity`、`qec_get_context` | 把结果 `id` 作为 `identifier`。有多个修订时传 `revision` 选择精确研究记录。 |
| 读取原始段落或资产 | `qec_get_source`、`qec_get_asset` | 用已登记来源 occurrence ID 或记录的 asset ID。来源区间用半开 Unicode codepoint 偏移，资产区间用字节偏移。 |
| 检查图节点和依赖 | `qecgraph_show`、`qecgraph_context`、`qecgraph_deps`、`qecgraph_impact` | 用图节点 ID 或唯一标签。`deps` 跟随结果依赖什么，`impact` 跟随什么依赖它。依赖 candidate 或历史链接前检查边状态。 |
| 过滤码实例 | `qec_find_codes` | 用 `n_min`/`n_max` 过滤码大小。硬距离界需指定 metric ID 和 sector（默认 `joint`）。默认 `verified` 策略要求当前界证据，并接受精确 `metric_revision`。`source_reported` 策略的硬距离过滤要求 `metric_revision`。 工作区的 `source_reported` 硬筛选还要求距离估计绑定该码的校验矩阵表示，并引用当前来源投影中的区间。 |
| 查找性能点 | `qec_find_performance` | 按 `code_id`、`decoder_id`、`noise_model_id` 或 `metric_id` 过滤。`complete_only: true` 只取满足必需上下文的点。坐标选择支持精确或最近报告点，并返回实际报告坐标。 |
| 查找软件或算法 | `qec_find_software` | 按 `query` 或 `role` 搜索。项目条目描述 catalog；沿 usage 记录查论文或运行使用证据。 |
| 检查工作区状态 | `qec_workspace_status` | 传 `{}`，读取最新运行状态及连接的固定知识 release。运行报告缺失或格式错误时 `operational_status` 为 `null`，固定 release 及其覆盖仍返回。 |

例如，导入自带论文后搜索 HGP。

```sh
qec-graph query-tool qecgraph_search --workspace . --arguments /dev/stdin <<'JSON'
{"query":"HGP","limit":5}
JSON
```

把结果 `id` 复制到 `qec_get_entity`。图命中带来源区间时，把 occurrence ID 传给
`qec_get_source` 取精确 LaTeX。MCP 客户端还可按 `qec://source/` resource URI
列出和读取已登记段落。CLI 中用 `--revision` 配合工作区 `query show` 或
`query context` 选择精确研究记录修订。CLI 也提供结构化查询的直接命令。

```sh
qec-graph query codes --workspace . --n-min 10 --n-max 100 --limit 5
qec-graph query performance --workspace . --coordinate-name p --coordinate 0.01 --selection exact
qec-graph query software --workspace . --query Stim --limit 5
```

传 `--release RELEASE_ID` 可对同一工作区 release 重复查询。用 `--machine`
直接查询挂载的 machine 目录。

只导入论文的工作区可以有记法提案和来源段落，而结构化实例或性能查询为空。
距离过滤前检查 metric、sector、界方向和证据策略。性能比较前，先比较返回的
metric 定义、实验和曲线修订、噪声、解码器及未解决条件。
[导入和审核记录](advanced-usage.zh-CN.md#管理-obsidian-vault-和研究记录)

## AI proposals

AI 抽取会把 `qecgraph.ai.proposal` 写入 `machine/ai/proposals/`。它们保持
`proposed`，不会被默认的 verified 证据策略选中。用 `qec-graph ai proposals`
列出，用 `qec-graph ai decide` 记录显式决定。决定绑定已发布提案的哈希和来源快照。
任一绑定变化时保留原决定，并显示为失效。提案引文使用
`projection_path:first-last`，行号从 1 开始并包含两端，投影可映射回归档来源。
旧版未绑定的提案保留在磁盘。配置 AI 后运行 `sync`，可从归档生成已绑定的提案。

## 读取和复现查询结果

用 `scope` 和 `knowledge_snapshot` 标识 release，用 `coverage` 查看已登记或
索引内容。结果 `truncated` 时，在工具支持分页时把 `continuation` 作为下一个
`offset`。响应预算会缩短一页，continuation 从下一个完整结果开始。来源段落
超过响应预算时，请求更小的字符区间。空结果描述你查询的搜索和 release。

MCP 连接在启动时固定知识 release。`sync` 后重新连接以读取新发布 release。
客户端配置来自 `mcp-config` 时，重新生成以更新显式 release ID。CLI 也接受
`--release`，对特定 release 重复查询。
[MCP 配置](../../README.zh-CN.md#mcp)

### 文档阅读 profiles

默认 MCP profile 保留原有 13 个工具。为 `mcp serve`、`mcp config` 或
`query-tool` 指定 `--profile research`，使用七个任务工具，包括 `qec_fetch`
与 `qec_search`。`qec_fetch` 接受精确 `identifier`，以及 `view: "outline"`、
`"raw"` 或 `"reading"`。目录用 `limit`/`offset` 分页，来源范围用原始 Unicode
`char_start`/`char_end`。论文分别返回登记源文件，保留 include 边界；章节返回
到下一个章节边界的连续文本，包括子章节。精确 `source_version_id` 不回退版本。

`--profile compatible` 只暴露 `search(query)` 和 `fetch(id)`，返回可引用证据单元。
在 `[sources."<source-tree-hash>"]` 中与 `work_id` 一起登记版本对应的公开
`canonical_url`，再 rebuild。不会为本地来源捏造 URL；它们仍可用研究 profile 访问。
通用 fetch 超预算返回 `BUDGET_TOO_SMALL`，可改用研究范围读取或增加会话预算。
`qec_status` 报告全文与仅元数据的覆盖情况。

### 可选混合检索

在 `qecgraph.toml` 启用本地投影，然后 sync 或 rebuild。本地模型对词法特征做哈希，
是离线检索基线，不是预训练语义模型。索引含 BM25 词频和分块向量，不包含私人笔记。
没有索引仍能检索原文。

```toml
[retrieval]
enabled = true
provider = "local"
model = "qecgraph-word-char-hash"
model_revision = "1"
dimensions = 512
chunk_chars = 2048
allow_source_upload = false
```

语义 embedding 使用 OpenAI-compatible endpoint：设置 `provider` 为
`"openai_compatible"`，填入真实 `model`、由操作者固定的 `model_revision`、
`base_url`、支持的 `dimensions`、`api_key_env` 和 `allow_source_upload = true`。
表内不存 key。入库与查询必须使用同一个模型/版本空间，仅维度相同不够。

`qec_search` 支持 `mode: "keyword"`、`"vector"` 或 `"hybrid"`（默认）。
`kind` 和精确 `source_version_id` 在排序前过滤。结果报告索引身份与覆盖。
embedding 不可用时 hybrid 明确报告关键词回退，纯向量模式返回错误。
原文和记录搜索结果都是发现候选，不证明硬条件成立。显式导入研究记录后用 sync 刷新投影。
写事务发布前检查 `max_chunks` 与 `max_total_chars`，失败保留旧 release；rebuild 能恢复损坏的派生索引。
