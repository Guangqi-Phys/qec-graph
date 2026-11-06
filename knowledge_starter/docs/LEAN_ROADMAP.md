# 从 QEC 资料库走向 Lean

本文件是形式化工作的规划指南。**本模板未安装或运行 Lean，未验证任何 Lean 定理，也不把示例记录标为形式化完成。**

## 1. 先固定数学表示

建议先围绕有限二元 CSS 码建立一个小而稳定的数学接口，再逐步增加一般稳定子码、SEC 和噪声语义。先检查现有 QEC Lean 库是否已经提供兼容定义，避免重新定义一整套基础。

固定以下约定：所有校验矩阵在 GF(2) 上运算；行表示校验、列表示物理比特；记录矩阵形状、比特顺序、X/Z 约定及逻辑算符表示。对 CSS 码保存 `HX * transpose(HZ) = 0` 的条件。允许冗余校验，量子维数必须由秩计算，不能直接用校验行数相减。

依次安排形式化目标：

1. 二元向量、Hamming weight、矩阵核与行空间。
2. CSS 对易条件、逻辑商空间和量子维数。
3. 具体构造的正确性，例如普通 HGP 的块矩阵满足对易条件。
4. 具体实例的逻辑算符、距离上界与下界。
5. 码族的一般参数定理，再考虑电路传播、故障模型及 circuit-level distance。

有限实例验证与一般定理应使用不同记录。证明某个矩阵满足对易条件，不等于证明所有构造参数都满足；证明码距离，也不等于证明某条 SEC 的线路距离。对 `k = 0` 时的距离、空最小值等边界情形，须明确采用什么定义。

## 2. 一条定理需要两个陈述和一个映射

文献记录保存原始陈述、论文版本及定位信息；数学记录保存标准化陈述、量词、全部假设和所引用定义。保留原论文符号与本项目符号之间的映射，禁止 AI 在整理时默默删除“满秩”“独立”“有限”“渐近”等条件。

最小映射字段建议如下；它们是设计建议，并不代表本模板已经实现 Lean 导出器。

| 字段 | 内容 |
|---|---|
| `theorem_id` | 不随文件名或 Lean 名称变化的稳定标识 |
| `source_refs` | 论文版本、定理编号、页码或 TeX 标签 |
| `statement`、`hypotheses` | 标准化陈述和逐项列出的假设 |
| `definition_refs` | 所使用定义及其版本 |
| `statement_relation` | 与原文等价、加强、弱化、特例或附加条件版本 |
| `formalization_id` | 一次具体形式化表示的稳定标识 |
| `lean_project`、`commit` | 项目及固定提交 |
| `module`、`declaration` | 精确 import 和全限定声明名 |
| `statement_hash` | 对实际导出的形式化陈述及相关版本进行绑定 |
| `build_evidence_ref` | 构建记录、工具链、依赖和公理检查结果 |
| `semantic_review` | 谁审核了自然语言与形式化陈述的对应关系 |

同一定理可以对应多个 Lean 声明。已编译声明的类型、直接依赖和公理依赖应从 Lean 环境导出；不要同时人工维护两份。尚未实现的证明计划可以人工记录，但要与实际证明依赖区分。文献引用、等价关系也不必构成 DAG。

## 3. 分开记录几种状态

不要只使用一个 `verified: true`。至少区分：

- **资料审核**：机器抽取、已核对来源、存在争议。
- **语义审核**：未审核、对应原定理、存在额外条件。
- **证明进度**：规划、陈述已表达、证明进行中、构建通过。
- **信任范围**：实际公理依赖、是否采用 native evaluation、是否满足项目的公理策略。

状态应绑定具体提交、输入数据和构建记录。修改定义、矩阵或依赖后，旧构建仍是旧版本的证据，不能自动成为新版本的完成标记。

`lake build` 成功不能独自表示证明完成；依赖中可能有 `sorryAx` 或自定义公理。使用 `#print axioms` 或从环境导出的同等审计检查传递依赖。常见基线允许 `propext`、`Classical.choice`、`Quot.sound`，但应保存真实输出，而不是手写固定结果。

无 `sorry` 也不保证语义正确：把待证结论直接加入假设，会产生合法但不解决原问题的定理。因此，假设审查与公理审查必须分开。[Lean 官方验证指南](https://lean-lang.org/doc/reference/latest/ValidatingProofs/) 明确区分证明有效性与陈述含义。

## 4. 将计算结果变成可复用的证明证据

Python 检查、求解器返回 `optimal` 和 Lean 证明是不同证据。对距离计算，非平凡逻辑算符通常提供上界；下界需要排除所有更低权重的非平凡逻辑算符。只有相匹配的上下界才能形成精确距离结论。

若使用 SAT、SMT 或 ILP，保存输入矩阵、编码版本、求解器版本；工具支持时，还保存证书、检查器及其结果。不能假设任意求解器都能输出可导入 Lean 的证书。要进入 Lean 证明链，还需要：

1. 证明编码确实表达目标 QEC 性质，包括逻辑非平凡条件。
2. 证明证书检查器的正确性。
3. 对准确绑定的实例与证书运行该检查器。

文件哈希能够绑定数据，不能证明编码正确。外部求解器可以只负责搜索；如果证书检查和编码桥接都在 Lean 中完成，求解器本身可不进入数学信任基础。

`proof_method` 与 `trust_profile` 应分字段：证书是一种证明方法，不必然扩大信任范围；`native_decide` 则会依赖原生编译求值。当前 Lean 文档说明其生成可审计的原生计算公理，具体名称与行为须按固定工具链判断。[公理文档](https://lean-lang.org/doc/reference/latest/Axioms/)

## 5. 版本、容器和 CI

把 `.lean`、`lean-toolchain`、`lakefile.toml` 或 `lakefile.lean`、`lake-manifest.json` 纳入 Git。Lake manifest 记录具体依赖版本；日常验证不要顺手执行会升级依赖的 `lake update`。[Lake 文档](https://lean-lang.org/doc/reference/latest/Build-Tools-and-Distribution/Lake/)

Lean 使用独立构建环境，与论文解析和 Python 仿真环境分开。镜像、工具链、mathlib 提交和平台信息进入构建记录；`.lake` 是可重建缓存，缓存按工具链和依赖版本隔离。

CI 应检查映射引用存在、目标模块构建、公理策略，以及导出索引是否对应当前代码。重要版本再执行完整构建与复查。人工审核负责陈述和假设的语义对应。`leanblueprint checkdecls` 只检查声明名称存在；`\leanok` 是作者标注，不是独立证明证据。[leanblueprint 官方项目](https://github.com/PatrickMassot/leanblueprint)

## 6. 可参考的现有项目

[QECert 论文](https://arxiv.org/abs/2611.05047v1) 于 2026 年 11 月 3 日提交。[官方仓库](https://github.com/QudeLeap/Lean-QECert) 的 `MAIN_RESULTS.json` 提供定理名、精确模块、源文件和文献索引，并强调导航标题不能代替完整定理及假设。它是设计 AI 查询接口的具体参考。[MAIN_RESULTS.json](https://github.com/QudeLeap/Lean-QECert/blob/main/MAIN_RESULTS.json)

[QECLean](https://github.com/Stavan-Jain/QECLean) 也是需要评估的候选，其项目文档介绍稳定子和同调框架及公理审计策略。采用任何库前，选择固定提交，阅读所需定义与全部假设，检查与本项目表示是否兼容，并实际构建相关定理。这里对项目的介绍不代表已经复现或审计其全部结果。
