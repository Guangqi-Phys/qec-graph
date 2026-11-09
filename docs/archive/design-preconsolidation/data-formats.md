# 04｜记录、资产、数学约定与哈希契约

> **Status: Historical.** Superseded by [the consolidated design](../../design/DESIGN.md). Keep for provenance; internal links and paths may describe the pre-consolidation layout.


本文定义目标领域契约，并说明当前原型和旧样例的兼容边界。
除明确标注的现有字段、格式和命令外，新增字段须在领域 Schema、迁移器和校验器中实现后启用。
图的实际边语义和状态枚举以 [02](graph-contract.md) 及对应版本 Schema 为准。

## 1. 文件角色与身份

| 格式 | 保存内容 | 是否权威 |
|---|---|---|
| JSON | 人工实体记录、显式关系、审核 sidecar、清单 | 是；目标只设这一种人工结构化真本 |
| YAML | 填写模板、外部资料导入 | 导入后以 JSON 为准，不维持双写 |
| Markdown | 研究笔记、动机、决策、操作说明 | 对说明文字权威，不重复维护参数 |
| 原始 `.tex`／PDF | 固定版本的原文 | 是；保留原始字节 |
| 规范化 LaTeX | 经审阅的数学陈述及符号映射 | 由 claim 记录关联，不能覆盖原文 |
| `.lean` | 实际定义、定理和证明实现 | 对该源码版本的形式化内容权威 |
| `.json`／稀疏数组 | 矩阵、逻辑代表、明确格式的数据 | 由 asset ID、格式和哈希定位 |
| CSV／Parquet | 原始或充分统计实验结果 | 明确列 Schema、单位、估计方法和 run |
| SQLite／向量索引 | 查询投影 | 可重建；不直接修改知识事实 |

`work_id` 标识一篇工作，`source_version_id` 标识它的特定版本，`id` 标识领域对象。
`revision` 标识对象的一次内容状态，`snapshot_id` 标识一次完整处理输入与工具配置。
哈希识别准确内容；标题、路径、检索 chunk ID 和 `[[n,k,d]]` 都不是对象唯一身份。
不同来源对同一对象的冲突论断分别保存，使用支持、反对或后继关系，不覆盖争议值。

## 2. 目标记录信封与字段所有权

当前旧记录具有 `schema_version,id,kind,title,review_status,refs,assets,data`。
目标保留这些职责，并补齐下表；具体 Schema 通过路线图 P1/P2 形成，不要求旧记录直接满足新字段。

| 字段／字段组 | 类型与规则 | 权威来源 |
|---|---|---|
| `schema_version` | 明确格式版本，未知版本拒绝静默解释 | Schema 发布 |
| `id`,`kind` | 稳定命名空间 ID；类型变更需迁移 | 实体登记 |
| `revision` | 可定位的修订标识，不复用为其他内容 | 记录版本历史 |
| `title`,`aliases` | 人类可读名称及中英别名，不作身份键 | 记录；书目字段可定向导入 |
| `data` | 按 kind 校验的领域数据 | 对应领域记录 |
| `refs` | 关系类型、目标 ID；必要时绑定目标 revision | 该关系的显式记录 |
| `assets` | asset ID、角色、相对位置、格式、长度和字节哈希 | 资产清单 |
| `provenance` | source version、定位、创建方法、处理器及时间 | 来源或生成任务 |
| `review` | 审核范围、审核者、结论、绑定输入、时间 | 审核记录 |
| `evidence_ids` | 支持该论断的独立证据 ID | 论断及证据记录 |

人工审核、计算检查、来源可用性和 Lean 完成状态分别建模；不使用一个 `verified: true` 表达所有含义。
原型 `verification_status` 不替代领域证据。catalog 的 `computed_exact` 只是导入记录原有声明。
只有再次执行对应检查并保存新证据，才可以说本次导入已重验。

未知值写 `null`，另存 `unknown_reason`，例如 `not_reported/not_computed/not_applicable/source_unavailable`。
零是已知数值；`[]` 表示已知为空；字段缺失只用于 Schema 明确允许的“不存在该字段”。
比率注明概率范围或百分数单位，时长注明单位；不能靠列名猜测数量纲。
图中读取的数值保存 `plot_digitized`、来源图号、坐标轴及读数误差，不能标成原始实验数据。

## 3. QEC 对象最低字段

以下概念沿用小写 kind：`family/construction/code_instance/presentation`。
经典种子、软件实现、度量和运行等独立类型是目标模型；旧 Schema 的类型集合并不完整。

| 对象 | 最低领域字段 | 不能混同 |
|---|---|---|
| CodeFamily | 定义、构造类别、适用域、别名、来源 | 一整个码族与某个参数实例 |
| Construction | 输入类型、公式、域、约定、输入修订、生成配置 | 数学构造与某个程序版本 |
| ClassicalSeed | 域、校验表示、长度、GF(2) 秩、维数及距离论断 | 同一经典码的不同检查矩阵 |
| CodeInstance | 构造 ID、固定输入、`n,k` 及其论断、表示 ID | 相同参数的不同码 |
| Presentation | 实例 ID、检查矩阵、符号、行列序、逻辑基 | 稳定子空间与具体生成元 |
| Implementation | 仓库、提交、入口、配置、依赖锁及平台 | 代码实现与其声称实现的数学对象 |
| Claim | 主体、定义、陈述、量词、假设、结论、证据 | 原文段落与规范化论断 |
| Evidence | 方法、精确输入、检查器、输出、适用域和限制 | 程序通过与数学定理成立 |
| Formalization | claim 映射、Lean 声明、提交、构建证据、语义关系 | 待实现名称与实际声明 |
| Circuit | 表示、调度、辅助比特、轮数、边界、observables、资产 | 码距离与电路故障距离 |
| Noise／Decoder | 明确模型、概率含义、算法变体和版本 | 名称相同但配置不同的实验 |
| Experiment | 输入快照、完整配置、估计量、统计、运行环境 | 一组配置与一次实际执行 |

`parameters.n/k` 的整理值由 instance 负责；来源声称的值是独立 claim，二者显式记录支持或冲突。
距离值由具体 metric claim 负责，实例保存 claim ID；展示用 d 只能是附出处的派生值。
ordinary HGP 与 ring lifted product 使用不同构造类别。
QC 种子额外保存 protograph／多项式块、提升尺寸、循环移位方向和展开规则，以及展开后的矩阵。
BB 等构造保存周期、多项式、平移约定和量子比特编号，不能只保存一个可视化图。
检查权重、列度数、Tanner 图及 SEC 与 presentation 绑定；行变换后需要重新计算。
一般稳定子码保存辛表示与相位；子系统码另建 gauge/stabilizer 约定，不套用 CSS 公式。

## 4. 二元矩阵与逻辑代表

本包示例采用：`H_X` 行为 X 稳定子，`H_Z` 行为 Z 稳定子，列为数据量子比特。
X 误差 syndrome 是 `H_Z x`，Z 误差 syndrome 是 `H_X z`；运算在 GF(2) 上进行。
所有示例稳定子使用 +1 相位；更一般的相位信息必须显式记录。

\[
H_XH_Z^T=0,\qquad k=n-\operatorname{rank}_{\mathbb F_2}H_X-\operatorname{rank}_{\mathbb F_2}H_Z.
\]

\[
H_ZL_X^T=0,\quad H_XL_Z^T=0,\quad L_XL_Z^T=I_k.
\]

除了这些关系，检查器应验证形状、秩和逻辑代表数目；不得用浮点实数秩替代 GF(2) 秩。
旧样例实际使用下面的 `coordinate-ones-v1`，示例为长度三重复码种子：

```json
{
  "field": "GF(2)",
  "format": "coordinate-ones-v1",
  "shape": [2, 3],
  "index_base": 0,
  "ones": [[0, 0], [0, 1], [1, 1], [1, 2]]
}
```

坐标必须是整数、在 shape 范围内、按字典序排列且无重复；不通过重复坐标隐含模二消去。
显式 shape 保留全零行列；行列顺序和量子比特标签不能在序列化时擅自排序。
大矩阵可采用稀疏数组格式，但保存 dtype、shape、索引约定、格式版本和可移植导出。
矩阵标准化哈希只消除存储歧义，不判断量子码等价。
固定比特标号下的行空间哈希最多提示候选等价；置换、局域 Clifford 等价另需证据。

`knowledge_starter` 的 HGP 示例取两个上述种子，使用原始 HGP 张量构造背景 [1]：

\[
H_X=[H_1\otimes I_3\mid I_2\otimes H_2^T],\qquad
H_Z=[I_3\otimes H_2\mid H_1^T\otimes I_2].
\]

列序为 `VV(i,j)=3*i+j`、`CC(a,b)=9+2*a+b`，均从 0 开始。
其两检查矩阵为 `6×13`、GF(2) 秩均为 6；样例检查器穷举有限向量得到 `d_X=d_Z=3`。
逻辑代表支撑分别为 X 的 `[0,1,2]` 与 Z 的 `[0,3,6]`；详见旧记录、矩阵和证据报告。
这是 locally generated、`computed_exact` 的小例子，未声称来自论文参数表，也没有 Lean 证明。
原始论文在旧包里只有书目指针；`source_version_id` 和下载文件仍为空。

## 5. 距离与证据

对本包定义域内 `k>0` 的二元 CSS 码：

\[
d_X=\min\{\operatorname{wt}(e):e\in\ker H_Z\setminus\operatorname{row}H_X\},\qquad d=\min(d_X,d_Z).
\]

`d_Z` 交换 X、Z；`k=0` 不在该定义域内，必须引用另一明确约定。

| 字段 | 要求 |
|---|---|
| `subject_id`,`presentation_id` | 指定准确实例、表示及输入修订 |
| `metric_definition_id` | 码距、电路距离、graphlike、残余距离分别定义 |
| `sector`,`relation` | X／Z／联合；exact／lower_bound／upper_bound／interval 等 |
| `lower_bound`,`upper_bound` | 未知端为 null，不用同一数值伪造精确性 |
| `assumptions`,`method` | 定理适用条件、穷举范围或搜索算法限制 |
| `evidence_ids` | 上界 witness、下界证明／证书／完整有限检查 |

找到重量 w 的合法非平凡逻辑代表给出上界；启发式搜索未发现更小代表通常不能给出下界。
相同实例、同一度量下可靠上下界相等，才支持精确值；证据类型仍需保留。
`source_reported`、`heuristic`、`computed_exact`、`certificate_checked`、形式化构建证据分别保存。
模拟曲线或有限样本不能替代一般定理，Schema 校验也不能替代数值检查。
Stim 中不同距离搜索有不同保证；graphlike 搜索、DEM 分解和真实电路故障之间必须说明映射。[2]
残余距离记录 `exactly_r/at_most_r`、图邻接定义、半径、锚点、对称性约化与搜索截断。
图上的局部邻域与物理几何邻域使用不同定义 ID。

## 6. 实验和 LER

一个 run 固定 code、presentation、circuit、noise、decoder、sampling 和 metric 的准确修订。
LER 必须定义：错误事件、observable 集合、X/Z 扇区、轮数、初末边界、后选择和解码超时策略。
任一逻辑量出错、单个逻辑量出错、每次运行和每轮错误率是不同指标；不能直接除以 k 或轮数换算。
噪声记录 code-capacity／phenomenological／circuit-level、各通道、位置规则、概率和时长。

| 采样方式 | 必存内容 | 估计约束 |
|---|---|---|
| IID Monte Carlo | shots、discarded、accepted、failures、停止规则、随机流、区间方法 | 后选择错误率同时报告接受率 |
| Importance sampling | 目标及提议分布、权重、估计公式、有效统计和原始输出 | 不统一套用 errors/shots |
| MCMC | 转移核、burn-in、链与批次、相关性诊断、估计方法 | 不能假定样本独立 |

零次失败不是零概率；保留置信水平、区间方法和停止规则，说明所报告的上界含义。
Sinter 的原始 shots/errors/discards 等统计可以作为资产保存，再增加领域元数据。[3]
BP-OSD 保存 BP 更新式、调度、阻尼、收敛判据、迭代上限、OSD 阶数、候选枚举变体和预处理。
实际输入 decoder 的矩阵单独保存；其自由变量数是列数减 GF(2) 秩，不是量子 k。
神经 decoder 另保存模型、权重哈希及训练／评估划分。
运行环境包含提交、依赖锁、实际镜像 digest、软件版本、硬件/ISA、并行度、批次策略和耗时。
仅固定 seed 不保证跨版本逐样本重现；Stim 官方也明确版本及执行方式相关限制。[4]
优先保留足以重算估计量的数据；需要重新解码时再按成本保存完整 samples。

电路资产包括 noiseless/noisy `.stim`、`.dem`、配置、交互顺序、辅助比特、detector 和 observable 定义。
记录实际 DEM 转换选项，尤其分解和近似参数；DEM 的 `^` 表示分解提示，不代表独立物理故障。[5]
电路距离另外声明可用故障集合、计数方式、轮数和边界，不能复用裸码距离字段。

## 7. 来源定位与审核绑定

目标 SourceVersion 保存 work ID、上游版本号、取得时间、URL、资产清单和可用性。
SourceSpan 绑定 source version、文件字节哈希、坐标系、片段位置及内容哈希。
PDF 同时区分物理页序和印刷页码；TeX 保存相对文件、label、章节和字符范围。
当前原型采用 Unicode codepoint 的 `[char_start,char_end)`，行号从 1 起且包含两端。
片段取自保留原换行的原始 UTF-8 文本；字节偏移与字符偏移不能混用。
父定理片段可能包含子公式，片段可重叠；完整原文从 sources 读取，不能拼接片段还原。
原文、OCR／解析结果、人工校正和规范化 claim 分别保存；符号映射带作用域。

当前 sidecar 审核绑定 `expected_content_sha256` 和 `expected_project_source_hash`。
审核依赖边还要绑定实际端点 ID 及 `expected_hashes`，重复 label 必须先解决歧义。
输入变化后审核为 stale；未完整绑定为 unbound，不能继续提供已审核依赖。
原型项目级哈希会使无关文件变化也导致审核失效，这是保守的已知限制。
未来可按完整依赖闭包缩小失效范围，不能在闭包缺失时直接取消项目绑定。

## 8. Canonicalization 与哈希

字节哈希统一定义为原始文件字节的 SHA-256 小写十六进制；换行、空格和 Unicode 编码变化均可改变它。
原始资产绝不先格式化再计算“原始哈希”。文本片段哈希为准确片段重新编码 UTF-8 后的 SHA-256。
哈希用于内容一致性检查，不认证作者身份、审核者身份或命题真假；签名和信任策略需另行设计。

| 已有协议 | 准确算法 | 适用范围 |
|---|---|---|
| 旧样例 `canonical_sha256` | `json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')` 后 SHA-256 | `knowledge_starter` 的矩阵对象 |
| 原型 JSON canonical | 同上但 `ensure_ascii=False` | graph、sidecar 输入及快照指纹中的 JSON |
| 原型 node `content_sha256` | 有 LaTeX 时哈希准确片段，否则哈希 canonical data | 节点内容及审核绑定 |

旧协议已经参与证据绑定，不能静默改用另一协议或把它们宣称为 RFC 8785/JCS。
RFC 8785 定义了另一套包含数值及属性排序规则的 JSON canonicalization；采用它需要显式迁移。[6]
目标哈希描述应增加 `algorithm`、`serialization_version`、`payload_scope`，旧值保留原协议标签。
数组保持语义顺序；只有 Schema 定义为集合的数组才能按规定排序。Unicode 不做隐式归一化。
新导入器拒绝重复 JSON key、NaN/Infinity 与未约定的数值转换；这些是待实现的严格输入门槛。
跨语言大整数或精确小数使用 Schema 指定的十进制字符串／有理数表示，避免隐式精度损失。
记录的语义内容哈希应由 Schema 指定的内容字段生成，不纳入哈希自身或仅用于显示的路径。
revision 和审核记录另绑定内容哈希、来源及依赖修订；格式整理不应自动等价于数学内容变化。
更换 canonicalization 时保留旧、新哈希及迁移映射，并重新验证引用与审核绑定。

## 主来源与本地证据

1. [HGP 原始论文](https://arxiv.org/abs/0903.0566)
2. [Stim 固定旧版本 API](https://github.com/quantumlib/Stim/wiki/Stim-v1.12-Python-API-Reference)（复现时换成实际版本）
3. [Sinter 官方说明](https://github.com/quantumlib/Stim/blob/main/glue/sample/README.md)
4. [Stim 复现限制](https://github.com/quantumlib/Stim/blob/main/doc/developer_documentation.md)
5. [DEM 格式](https://github.com/quantumlib/Stim/blob/main/doc/file_format_dem_detector_error_model.md)
6. [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785)
7. 有限实例的实际记录、输入和报告均位于 `knowledge_starter/` 下的 `records/`、`assets/matrices/`、`evidence/demo_validation.json`。
