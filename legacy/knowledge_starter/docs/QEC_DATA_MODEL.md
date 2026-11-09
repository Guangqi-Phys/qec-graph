# QEC 知识库的数据模型

本文件约定面向 CSS/qLDPC、syndrome extraction circuit（SEC）、解码与 Lean 形式化的核心记录。它是一套可扩展的起点；示例中的计算验证不等于 Lean 证明。Error Correction Zoo 已采用可读、可审查的 YAML 维护码资料，可借鉴其组织方式，但研究实例还需要矩阵、程序与证据记录。[1]

## 1. 先分清对象，再存参数

每个对象具有稳定 `id`、`schema_version`、不可混淆的 `revision`、来源引用与创建方式。修改内容产生新修订；别名、标题、文件路径都不能充当唯一身份。一个 `[[n,k,d]]` 参数组不能唯一确定一个码。

| 对象 | 最低应保存的字段 | 必须区分的内容 |
|---|---|---|
| 论文与版本 | `work_id, version_id, title, authors, doi, arxiv_id, version, source_uri, sha256` | 论文身份与具体 PDF/TeX 版本 |
| 原文片段 | `version_id, locator, text, extraction_method` | PDF 页序、印刷页码、定理/公式号、TeX 文件与位置；OCR 文本与人工校正 |
| 定义与术语 | `definition_id, notation, domain, assumptions, meaning, aliases` | 同名术语在不同论文中的含义 |
| 原子论断/定理 | `subject, predicate, value_or_statement, qualifiers, assumptions, evidence_ids` | 定理、猜想、实验观察、数值界、作者自己的推导 |
| 码族与构造 | `family_id, construction_id, input_types, formula, conventions` | ordinary HGP、BB、lifted product 等不同构造 |
| 经典种子 | `field, check_matrix, n, rank, dimension, distance_claims` | 同一经典码的不同校验矩阵；转置码也依赖矩阵表示 |
| 码实例 | `construction_id, input_revisions, parameters, presentation_ids` | 固定构造输入产生的实例与整个码族 |
| 校验表示 | `field, H_X, H_Z, signs, qubit_order, check_order, logical_basis` | 同一稳定子空间的不同生成元集合、冗余检查与排序 |
| 软件实现 | `repository, commit, entrypoint, config, lockfile, image_digest` | 数学对象与生成它的某个程序版本 |
| SEC 电路 | `presentation_id, circuit_artifact, schedule, ancillas, rounds, observables` | 码距、实际测量电路及其边界条件 |
| 噪声配置 | `model_kind, channels, location_rules, parameters, durations` | code-capacity、phenomenological、circuit-level；每种概率的定义 |
| 解码配置 | `algorithm, implementation_revision, hyperparameters, input_representation` | BP/OSD 具体变体、迭代上限、停止规则、预处理 |
| 实验运行 | `code, circuit, noise, decoder, sampling, metric, counts, environment` | 算法配置与一次实际执行 |
| 验证与形式化 | `claim_id, inputs_hashes, method, result, checker_revision, artifacts` | 论文声称、程序检查、证书检查、Lean 检查 |

关系使用显式 ID，例如 `constructed_from`、`uses_presentation`、`supports`、`contradicts`、`formalizes`。保留相冲突的来源论断，不通过覆盖旧数值消除冲突。人工审阅、证据类型与 Lean 完成状态应是三个字段，不能压成一个含义模糊的 `verified: true`。

未知量写 `null` 并说明原因；“未知”“尚未计算”“不适用”分开。来源图中读取的数值记录为 `plot_digitized`，附图号、坐标轴类型与读取精度，不能冒充作者发布的原始数据。

对 QC 种子，额外保存 protograph/多项式块、提升尺寸、循环移位方向及展开规则，并保存展开后的二元矩阵。`ordinary_hgp` 应表示对普通二元种子矩阵执行上述类型的张量构造，不能只因代码也使用环或循环移位，就与 ring lifted product 混为一类。BB 构造则记录两个周期、多项式、平移及量子比特标号约定。

## 2. 矩阵存储必须写明数学约定

本起点采用二元 CSS 约定：`H_X` 的行是 X 稳定子，`H_Z` 的行是 Z 稳定子；因此 X 误差由 `H_Z` 检测。示例所有稳定子取 +1 本征值。计算均在 GF(2) 上进行：

\[
H_XH_Z^T=0,\qquad k=n-\operatorname{rank}_{\mathbb F_2}H_X-\operatorname{rank}_{\mathbb F_2}H_Z.
\]

逻辑代表矩阵 `L_X,L_Z` 各有 `k` 行，应检查

\[
H_ZL_X^T=0,\quad H_XL_Z^T=0,\quad L_XL_Z^T=I_k.
\]

不得用浮点线性代数的实数秩代替 GF(2) 秩。一般稳定子码还须保存相位/符号与辛表示约定；二元矩阵本身不包含完整相位信息。

小矩阵可用 JSON 行支撑列表；本模板实际采用 `coordinate-ones-v1` 坐标列表：明确 `field: GF(2)`、`shape`、`index_base: 0`，`ones` 中每项为 `[row, column]`，按字典序排列、无重复；保留全零行、列及原始行列顺序。大矩阵可存稀疏数组文件，同时保存格式说明与可移植导出。数组文件的字节哈希和标准化矩阵哈希分别记录；标准化哈希包含域、形状、行顺序、索引规则与序列化版本。

这里的“标准化”只消除存储歧义，不自动把等价码合并。行变换保持稳定子空间，却可能改变检查权重、Tanner 图和 SEC。故 `max_check_weight`、行权重分布、列度数属于特定 `presentation`。若另存固定量子比特标号下的行空间哈希，只用于提示潜在等价，不能取代原始表示身份。

## 3. 可复核的小 ordinary HGP 实例

取两个经典重复码种子

\[
H_1=H_2=\begin{pmatrix}1&1&0\\0&1&1\end{pmatrix},
\]

按普通二元 HGP 公式构造 [2]

\[
H_X=[H_1\otimes I_3\mid I_2\otimes H_2^T],\quad
H_Z=[I_3\otimes H_2\mid H_1^T\otimes I_2].
\]

列顺序约定为 `VV(i,j)=3*i+j`，之后 `CC(a,b)=9+2*a+b`，所有编号从 0 开始。直接检查得到：

| 项目 | 结果 |
|---|---|
| 矩阵形状 | `H_X,H_Z` 均为 `6 × 13` |
| GF(2) 秩 | 各为 6，故 `k=1` |
| 对易性 | `H_X H_Z^T=0` |
| X、Z 距离 | `d_X=d_Z=3` |
| X 逻辑代表支撑 | `[0,1,2]` |
| Z 逻辑代表支撑 | `[0,3,6]` |
| X 检查权重 | `[3,4,3,3,4,3]` |
| Z 检查权重 | `[3,3,4,4,3,3]` |

该实例为 `[[13,1,3]]`。示例的精确距离检查遍历全部 `2^13` 个向量，排除稳定子行空间，再求合法逻辑代表的最小重量。这是 `computed_exact`：它依赖实际运行的检查程序及环境，应附输入哈希、代码和结果日志；不能据此标记为 `lean_verified`。

## 4. 距离要保存上下界及其证据

沿用上面的约定，

\[
d_X=\min\{\operatorname{wt}(e):e\in\ker H_Z\setminus\operatorname{row}H_X\},
\]

`d_Z` 交换 X、Z。零逻辑维数时的距离约定应另行声明。

距离论断至少包含 `metric_definition_id, sector, lower_bound, upper_bound, method, evidence_ids`。找到重量 12 的非平凡逻辑算符，只证明上界 12；未搜索到重量小于 12 的算符，一般不证明下界 12。只有同一实例、同一定义下可靠的上下界相等，才可记录精确值；证据强度仍应保留。论文给出的精确值可登记为“原文声称”，不要自动升级为独立复现。

上界证据保存具体逻辑算符或 fault witness；下界保存定理适用条件、穷举检查记录或可检查的无解证书。Stim 的启发式搜索与 `shortest_graphlike_error` 有不同保证，图状距离也不可直接冒充一般电路距离。尤其经过分解的 DEM 边需要检查是否能映回真实电路故障。[3]

## 5. LER 是完整实验条件下的量

保存 `event_definition`、被监测的逻辑 observable 集合、X/Z 扇区、轮数、终边界、是否后选择、解码失败/超时处理。区分“任一被监测 observable 出错”“单个逻辑量出错”“每次运行”和“每轮”；一般不能通过除以 `k` 或轮数互相换算。

BP-OSD 还应记录 BP 更新式、消息调度、阻尼/缩放、收敛判据、OSD 阶数与候选枚举变体。保存实际送入解码器的矩阵，而不只保存码的原始检查矩阵；相应自由变量数是该矩阵列数减 GF(2) 秩，不能与量子逻辑比特数 `k` 混用。神经解码器则增加模型结构、权重哈希及训练/评估数据划分。

IID Monte Carlo 保存总样本、保留样本、discard、失败数、停止规则及置信区间方法；后选择条件错误率还必须同时报告接受率。Sinter 原生统计已包含 shots、errors、discards 等字段，可保留其原始输出并增加领域元数据。[4]

重要性采样还应保存目标/提议分布、权重与估计公式；MCMC 保存转移核、burn-in、链/批次及相关性诊断。它们不能一概使用 `errors/shots` 或普通二项区间。先保存足以复算估计量的数据，再生成图；重跑解码需要的全量样本可按成本另存。

随机种子不足以保证跨版本逐样本复现。记录软件提交、锁文件、容器镜像摘要、硬件/指令集以及批次方式；Stim 明确说明随机种子行为不保证跨小版本不变。[5]

## 6. 电路与自定义度量也需要版本

保存 noiseless 电路、带噪电路、生成配置、`.stim`、`.dem`、detector/observable 定义及 DEM 转换选项。DEM 的 detector 与 observable 是不同目标；`^` 标记建议分解，不表示独立物理故障。[6] 保存 `decompose_errors`、`approximate_disjoint_errors` 等设置，因为转换可能引入近似。[7]

电路距离还须注明 admissible fault 集合、故障计数方式、轮数与边界。残余距离、ordered residual profile、DEM-proximity 各有独立 `metric_definition_id`；保存“恰好 r 阶”或“至多 r 阶”、图的邻接定义、半径、锚点、对称性约化依据和搜索截断参数。图局部邻域与物理几何邻域不可共用含糊的 `local` 标签。

## 来源

1. [Error Correction Zoo 数据仓库](https://github.com/errorcorrectionzoo/eczoo_data)：结构化 YAML 与来源组织。
2. [Tillich–Zémor 原始 HGP 论文](https://arxiv.org/abs/0903.0566)：普通 HGP 构造；上面的具体参数另由有限实例枚举核验。
3. [Stim v1.12 官方 API 文档](https://github.com/quantumlib/Stim/wiki/Stim-v1.12-Python-API-Reference)：搜索保证、graphlike error 与原始电路故障映射的限制。复现时应换成实际锁定版本的文档。
4. [Sinter 官方说明](https://github.com/quantumlib/Stim/blob/main/glue/sample/README.md)：采样统计与 CSV 字段。
5. [Stim 开发者文档](https://github.com/quantumlib/Stim/blob/main/doc/developer_documentation.md)：随机种子行为与版本。
6. [Stim DEM 文件格式](https://github.com/quantumlib/Stim/blob/main/doc/file_format_dem_detector_error_model.md)：detector、observable 与分解标记。
7. [Stim 命令行文档](https://github.com/quantumlib/Stim/blob/main/doc/usage_command_line.md)：DEM 转换近似及分解选项。
