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

Review/apply 的命令、事务和失效语义在后续步骤补入本页。
