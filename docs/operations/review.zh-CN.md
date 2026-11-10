# 类型验证、证据与审核

> **状态：当前，适用于 corpus 审核接口。** Workspace review/apply semantics are in the [system design](../design/DESIGN.zh-CN.md#6-审核证据和查询资格).

> [English](review.md) · **中文**

## On this page

- [记录与 Schema](#记录与-schema)
- [验证范围](#验证范围)
- [数学插件和硬条件](#数学插件和硬条件)
- [提案和决定](#提案和决定)
- [Apply 事务与恢复](#apply-事务与恢复)
- [派生失效与逻辑环](#派生失效与逻辑环)

> [!IMPORTANT]
> Schema/type validation is not mathematical verification. A passed check,
> a bound distance witness, and a human review are separate evidence states.

## 记录与 Schema

记录使用唯一的当前 `qecgraph.record` 格式。权威 Schema 随 Python 包发布于
[`qecgraph/validators/schemas/`](../../qecgraph/validators/schemas)，直接使用打包路径。
未知 Schema 被拒绝，绝不用当前字段重新解释。可选的
`legacy/knowledge_starter` 导入器只是历史样例的一次性开发适配器，不是运行时兼容层；
新写入始终产生当前格式。

`qecgraph.record` 还包含实验性的 `lean_declaration` kind 与关系字段；Lean 在 0.4.x
中延期，不属于受支持工作流，也不是验证结论。见
[系统设计 §10](../design/DESIGN.zh-CN.md#10-lean延期不支持)。

`jsonschema==4.26.0` 从可选验证依赖提升为固定运行依赖，保证所有写入入口执行相同结构验证。
JSON 输入拒绝重复 key、NaN、Infinity 和溢出为非有限数的十进制指数。
顶层未知字段必须放在 extensions；data 的领域扩展允许保留，已规定的字段按类型验证。
null 需要 unknown_reason；n/k 不得为负数或布尔值，k 不得大于 n。

## 验证范围

```bash
qecgraph validate --store build/demo
qecgraph validate-corpus --corpus build/corpus
```

单 store 验证增加关系端点类型，例如 proof_of 只能由 proof 指向陈述；
错误类型会在发布前失败并保留旧 CURRENT。旧 catalog: 关系保留旧语义，不冒充审核依赖。
Corpus 验证还检查悬空引用、修订绑定、受管理资产字节和来源完整性。
草稿可保存未解析引用，但查询诊断和严格验收会明确报告，不能静默忽略。
结构/类型通过不代表矩阵有效、距离已证明、有人审核或实验性 Lean 已构建。

工具指纹包含所有 Python 子模块、打包 Schema 及解析/验证依赖版本；
修改验证器或 Schema 会产生新构建身份，不复用旧快照作为新规则的验收证据。

## 数学插件和硬条件

```bash
qecgraph check-css --hx legacy/knowledge_starter/assets/matrices/HX.gf2.json --hz legacy/knowledge_starter/assets/matrices/HZ.gf2.json --lx legacy/knowledge_starter/assets/matrices/LX.gf2.json --lz legacy/knowledge_starter/assets/matrices/LZ.gf2.json --enumerate-distance
qecgraph codes --corpus build/corpus --n-min 13 --n-max 13 --distance-at-least 3 --metric-id definition:css-distance
```

默认 `verified` 策略只接受 computed/certificate 证据；显式选择来源报告界时加上
`--evidence-policy source_reported --metric-revision REV`。CSS 插件只支持 +1 相位的
二元 CSS 约定；校验显式形状、坐标、GF(2) 秩、对易及逻辑配对。
有限距离检查必须显式开启，默认 n≤20，绝对上限 22；k=0 返回定义域外，不补造距离。
普通 HGP 示例实际得到 n=13、k=1、dX=dZ=3（validation/review/css-check.json），仍是 Python computed_exact。
非对易矩阵不会获得 CSS 有效结果。此接口不运行 Lean，不写审核记录。

硬筛选先匹配明确 metric_id 和 sector（joint/X/Z），再检查 exact/lower_bound/interval 的已知下界；
upper_bound、未知下界、缺失表示或无当前证据都不匹配。Evidence 的 `data.inputs` 必须绑定距离论断、
实例、表示和度量各自的当前 ID、revision 与内容哈希。相关资产也必须可读且哈希一致。
已有证据缺少论断绑定时仍可查阅。要在硬筛选中使用，需检查确切论断后登记新证据修订。
输出保留来源报告、计算、证书等证据类别；Lean 不参与受支持流程。
历史样例的部分输入绑定和 sector 未说明，故默认不满足此严格筛选；应登记准确证据，不能只刷新哈希。
`evidence_ids` 唯一保存在记录信封中。

实验插件 `validators.qec.check_experiment(record, metric)` 或 `check-experiment <JSON>`
验证错误事件、分母、sector、轮数、边界、后选择、超时和输入绑定结构。
IID 仅对明确的 accepted_shots 度量计算 failures/accepted，并独立返回接受率；
importance/MCMC 必须提供估计器和采样信息，不套用 errors/shots。零次失败不能带零概率上界。
`comparable_experiments` 保守比较精确输入、配置、度量和采样。空配置、未知配置和含 null 的配置均不能通过可比性检查。
该插件的输入版本检查是结构检查，调用方需另外解析并核对引用的实际记录；返回明确标示此范围。

## 提案和决定

```bash
qecgraph review examples/proposal.example.json --corpus build/review-demo --actor-id codex --actor-kind ai
qecgraph review-decide <返回的proposal_id> --corpus build/review-demo --actor-id codex --actor-kind ai --decision approve --rationale '结构检查接受，保持未人工审核'
```

review 只保存 proposed 提案和差异，不应用记录。新 ID 的 expected_revision/hash 都为 null；
改动已有 ID 时必须填写准确旧 revision/hash，并指定新 revision。差异包含完整陈述、假设和依赖。
提案绑定 corpus_id、被改动记录及其显式引用闭包、来源快照及实际读取的资产字节；
无关记录的变化不会使决定 stale，但依赖记录变化会。相同内容的不同 corpus 不互借提案。
Corpus 搬迁保留 marker 中的身份，不以路径作为身份。

review-decide 保存执行者 ID/类别、时间、范围、理由、决定和准确提案哈希。
AI/program approve 只产生 machine_accepted，最终记录保持 draft/proposed。
人工 approve 必须明确核对 statement、hypotheses、dependencies 三个 scope（重复使用 --checked-scope），
不能只刷新 expected hash。身份是本地操作者显式声明，不是身份认证；自动化不得冒充 human。
人工审核绑定其完整提案和精确最终记录，改变陈述、假设、依赖或 revision 后不能复制旧审核。
资产缺失或变化、输入 revision/hash 不符、另一个 corpus 或过期 registry 均拒绝决定。

`depends_on_reviewed` 按原关系名和哈希绑定解释；领域 refs 无人工绑定时标为 unbound_review，
不会因 declared 状态或 include-candidates 而进入确认上下文。原始记录仍可 show 供审核。

## Apply 事务与恢复

```bash
qecgraph apply <proposal_id> --review-id <review_id> --corpus build/review-demo
```

apply 在同一写者锁内核对 corpus、整个 registry 基线、review 提案哈希、当前记录内容和实际资产，
再写入完整新修订，执行端点／跨记录检查，最后原子发布一个 registry state。
保守的整个 registry CAS 会拒绝并行的无关改动；需要重新取差异和创建提案，不自动刷新 expected hash。
缺失目标或类型错误使整个批次失败；历史证据过期保留为可见 warning，不删除或重绑旧证据。

已发布状态记录 application；不可变 receipt 绑定 proposal、review、全部结果哈希和发布 revision。
相同 proposal/review 重复 apply 返回同一 receipt；即使后来有其他更新，也不重复覆盖记录。
不同 review 不能覆盖已经应用的同一 proposal。

失败或崩溃可留下未引用的完整记录/receipt，不能仅凭 receipt 文件判断已应用；
只有 CURRENT 指向包含 application 的完整 state 才算发布。指针写入失败保留旧状态，
对相同有效输入重试可恢复。回滚查看历史 state/record revisions，不删除新证据或改旧哈希。
POSIX flock 冲突明确报错，不破坏正在执行的写者。

## 派生失效与逻辑环

所有遍历、证明补入、结构补入、最终边集合及注释输出共用同一个状态策略。
stale/unbound_review/unresolved 始终排除；include-candidates 只增加仍有效的候选。
`depends_on_reviewed` 的有效 status 可以是 declared，不错误要求数据必须写 reviewed。

人工决定保持不可变；查询根据其绑定的实际记录、来源和资产派生 review_binding。
任何已绑定依赖 revision/hash 或资产变化，审核为 stale 并列出具体原因；
不直接修改旧审核、旧 hash 或旧 evidence。读取历史 registry revision 使用其原来的记录版本；
实物资产缺失仍会明确报告，不能宣称其证据可重放。
当前失效绑定覆盖审核时已知的整个 corpus，较保守；新增无关 ID 不改写旧决定。

```bash
qecgraph audit-dependencies --corpus build/corpus
qecgraph audit-dependencies --store build/demo
```

只对仍有效的 depends_on_reviewed 子图检查强连通分量，返回节点/边 ID 和待判断问题。
文献引用环允许保留；候选、无绑定和过期依赖不进入该审计子图；不全图强制 DAG，也不自动删除问题边。
