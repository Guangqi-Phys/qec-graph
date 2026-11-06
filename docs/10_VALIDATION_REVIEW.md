# 类型验证、证据与审核

## 记录与 Schema 版本

P2 新记录使用 `qecgraph.record.v3`。相对 P1 v2，新增逐 kind 必填字段、显式未知原因、
严格引用和受管理资产结构。权威 Schema 随 Python 包发布于 `qecgraph/validators/schemas/`；
根目录 `schemas/record.v2.schema.json`、`record.v3.schema.json` 只是引用入口。

原 v2 记录和历史哈希仍可读取，不就地改写。用 `migrate <旧记录目录> --out <新目录>`
显式生成新 revision，完整旧对象及旧哈希保存在 `extensions.pre_validation_record`。
有资产时提供准确的 `--source-root`。迁移把未知字段记为 null 和 unknown_reason，不补造数学值，
不沿用旧审核。新写入只接受 v3。原 graph.v1、annotations.v1 与 0.1.0 适配继续保留。

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
结构/类型通过不代表矩阵有效、距离已证明、有人审核或 Lean 已构建。

工具指纹包含所有 Python 子模块、打包 Schema 及解析/验证依赖版本；
修改验证器或 Schema 会产生新构建身份，不复用旧快照作为新规则的验收证据。

## 数学插件和硬条件

```bash
qecgraph check-css --hx knowledge_starter/assets/matrices/HX.gf2.json --hz knowledge_starter/assets/matrices/HZ.gf2.json --lx knowledge_starter/assets/matrices/LX.gf2.json --lz knowledge_starter/assets/matrices/LZ.gf2.json --enumerate-distance
qecgraph codes --corpus build/corpus --n-min 13 --n-max 13 --distance-at-least 3 --metric-definition-id definition:css-distance
```

CSS 插件只支持 +1 相位的二元 CSS 约定；校验显式形状、坐标、GF(2) 秩、对易及逻辑配对。
有限距离检查必须显式开启，默认 n≤20，绝对上限 22；k=0 返回定义域外，不补造距离。
普通 HGP 示例实际得到 n=13、k=1、dX=dZ=3（validation/p2/css-check.json），仍是 Python computed_exact。
非对易矩阵不会获得 CSS 有效结果。此接口不运行 Lean，不写审核记录。

硬筛选先匹配明确 metric_definition_id 和 sector（joint/X/Z），再检查 exact/lower_bound/interval 的已知下界；
upper_bound、未知下界、缺失表示或无当前证据都不匹配。Evidence 必须绑定当前实例、表示和度量的
ID/revision/hash，且相关资产可读、哈希一致。输出保留来源报告/计算/证书/Lean 等类别，不统一提升为 verified。
旧迁移样例的部分输入绑定和 sector 未说明，故默认不满足此严格筛选；应重新执行并登记准确证据，不能只刷新哈希。
`evidence_ids` 在 v3 中唯一保存在记录信封；旧 data 中同名字段显式迁移，原值仍在历史对象中。

实验插件 `validators.qec.check_experiment(record, metric)` 或 `check-experiment <JSON>`
验证错误事件、分母、sector、轮数、边界、后选择、超时和输入绑定结构。
IID 仅对明确的 accepted_shots 度量计算 failures/accepted，并独立返回接受率；
importance/MCMC 必须提供估计器和采样信息，不套用 errors/shots。零次失败不能带零概率上界。
`comparable_experiments` 保守比较精确输入/配置/度量/采样；不做每轮、每逻辑比特换算。
该插件的输入版本检查是结构检查，调用方需另外解析并核对引用的实际记录；返回明确标示此范围。

## 提案和决定

```bash
qecgraph review examples/proposal.example.json --corpus build/review-demo --actor-id codex --actor-kind ai
qecgraph review-decide <返回的proposal_id> --corpus build/review-demo --actor-id codex --actor-kind ai --decision approve --rationale '结构检查接受，保持未人工审核'
```

review 只保存 proposed 提案和差异，不应用记录。新 ID 的 expected_revision/hash 都为 null；
改动已有 ID 时必须填写准确旧 revision/hash，并指定新 revision。差异包含完整陈述、假设和依赖。
提案绑定 corpus_id、registry revision、当前记录、来源快照及实际读取的资产字节；
相同内容的不同 corpus 不互借提案。Corpus 搬迁保留 marker 中的身份，不以路径作为身份。

review-decide 保存执行者 ID/类别、时间、范围、理由、决定和准确提案哈希。
AI/program approve 只产生 machine_accepted，最终记录保持 draft/proposed。
人工 approve 必须明确核对 statement、hypotheses、dependencies 三个 scope（重复使用 --checked-scope），
不能只刷新 expected hash。身份是本地操作者显式声明，不是身份认证；自动化不得冒充 human。
人工审核绑定其完整提案和精确最终记录，改变陈述、假设、依赖或 revision 后不能复制旧审核。
资产缺失或变化、输入 revision/hash 不符、另一个 corpus 或过期 registry 均拒绝决定。

旧 v1 depends_on_reviewed 仍按原关系名和哈希绑定解释；新增领域 refs 无人工绑定时标为 unbound_review，
不会因 declared 状态或 include-candidates 而进入确认上下文。原始记录仍可 show 供审核。

apply 事务与恢复语义在下一步骤补入本页。
