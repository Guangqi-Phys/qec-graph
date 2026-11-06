# 实施记录

说明包 `qec_graph_codex_handoff/` 保留为本地只读参考，Git 忽略该目录。
根目录是可独立安装、测试的工作项目；`validation/handoff/` 仅是交接时的历史证据。
不将历史报告作为本次运行结果。P0–P5 的验收条款继续以 `08_ROADMAP_ACCEPTANCE.md` 为准。

准备提交：`a96f54c`，忽略交接目录（不计入以下开发步数）。
每个编号步骤单独提交；10、20 步后推送，最终交付补推。

| 步骤 | 阶段 | 工作项 | 状态 |
|---|---|---|---|
| 01 | P0 | 将原型、规范、样例和历史证据迁入工作根目录 | 完成 |
| 02 | P0 | 安装、复现原型并保存本次证据 | 完成 |
| 03 | P0 | 核对固定版本 CodeGraph、许可证和架构映射 | 完成 |
| 04 | P1 | 多文档 work/version 注册、不可变来源绑定 | 完成 |
| 05 | P1 | 规范 claim、实体修订和多对多来源关系 | 完成 |
| 06 | P1 | 固定 corpus/snapshot 的跨文档查询 | 完成 |
| 07 | P1 | 旧图、sidecar、知识样例的显式迁移 | 完成 |
| 08 | P2 | 严格 JSON、领域信封及端点类型验证 | 完成 |
| 09 | P2 | 距离、矩阵和实验条件验证与筛选 | 待执行 |
| 10 | P2 | review 提案、身份类别与输入绑定 | 待执行 |
| 11 | P2 | 原子 apply、锁、冲突和幂等 | 待执行 |
| 12 | P2 | 状态兼容、资源失效及审核逻辑环 | 待执行 |
| 13 | P3 | 写者锁、strict staging 与发布恢复 | 待执行 |
| 14 | P3 | 输入依赖指纹及安全解析缓存 | 待执行 |
| 15 | P3 | watch 调度、变更和全量一致性 | 待执行 |
| 16 | P3 | 恢复演练和真实增量测量 | 待执行 |
| 17 | P4 | 只读工具契约、固定作用域和预算 | 待执行 |
| 18 | P4 | MCP stdio 传输及协议测试 | 待执行 |
| 19 | P4 | CLI/Python/MCP 一致性和客户端说明 | 待执行 |
| 20 | P5 | 固定 Lean 工程和边界清晰的实际结果 | 待执行 |
| 21 | P5 | 实际声明类型、依赖和公理导出 | 待执行 |
| 22 | P5 | 构建证据绑定、失效和语义映射 | 待执行 |
| 23 | P5 | Lean 重放与信任失败案例 | 待执行 |
| 24 | 全部 | 端到端验收、能力表与恢复说明 | 待执行 |

## 01 · 项目落地

复制工作源码、Schema、样例和操作规范；历史验证报告放入独立子目录。
忽略虚拟环境、缓存和可重建的 build 产物。交接包保持原样。
检查：根目录存在 pyproject.toml、qecgraph、tests、examples、knowledge_starter 和编号规范。

## 02 · 原型复现

在 .venv 安装固定依赖。运行 `.venv/bin/python tools/reproduce.py --out build/reproduce`，退出 0。24 项回归通过，3 个来源文件、26 个片段；注释图 36 节点、97 边；旧 catalog 44 节点、110 边。JSON Schema 和有限 HGP 检查实际执行。Python 3.15.2；详见 validation/p0/results.json。Docker 和 Lean 尚未执行。

## 03 · 上游核对

实际 checkout 和阅读 CodeGraph f72c9d2efb14454ff4f9fd7b8460abd82f19a287，检查 LICENSE 及提取、存储、解析、查询、上下文、watch 边界。详见 adr/0001-codegraph-reference.md。仅参考设计，无代码复制。修正环境锁文件的 editable 安装为本地路径，避免锁到早期开发提交。

## 04 · 来源注册

新增 registry.py、transactions.py、register CLI 和 09_CORPUS.md。work/version 明确身份，快照验证后归档，历史 state 内容寻址、单写者锁及原子指针发布。两个同 label 项目保持不同来源；新版本不覆盖历史；原路径删除后归档仍可查。`.venv/bin/python -m unittest discover -s tests -p test_registry.py -v`：2 项通过。

## 05 · 独立领域身份

新增 record.v2、records.py、record-add/claim-link。实体修订与原文块分离，显式 normalizes_to 保留双方版本/哈希、假设和记号域；新映射默认 proposed。相同参数不合并，新修订不覆盖旧内容。registry 回归 5 项通过；覆盖两处来源到一个 claim 和一处来源到多个 claim。

## 06 · 固定作用域查询

新增 corpus.py 的版本命名空间投影，复用 query 层；CLI search/show/deps/impact/context 支持 --corpus、--registry-revision 和 --source-version-id，原 store 支持 --snapshot。来源出现带准确版本与快照，空结果及截断可观察。全量 unittest 32 项通过；实际执行 register → record-add → claim-link → search CLI 演示。

## 07 · 显式迁移与 P1 验收

新增 migrations.py、migrate/migration-import；独立输出、字节原件、ID/修订映射与拒绝报告。旧 0.1.0 记录保留全部原字段及证据，图/sidecar 逐字节透传；资产核对旧协议后变为受管理 URI，不重验数学。全量 unittest 35 项通过；实际迁移并导入 10 条样例记录，报告见 validation/p1。P1 核心验收完成；POSIX 本地文件锁、保守 corpus 子串查询及 passthrough 边界见 09_CORPUS.md。

## 08 · 严格结构与类型

新增运行时 JSON Schema、record.v3 最低领域字段、明确 unknown_reason、引用与资产信封及关系端点规则。v2 保留可读并提供显式 v3 新修订迁移；不刷新旧审核。拒绝重复键、非有限数和指数溢出。validate-corpus 显示未解析引用与资产问题；错误 proof_of 在发布前失败。指纹覆盖子模块与 Schema。全量 unittest 40 项通过。运行依赖新增固定 jsonschema==4.26.0；见 10_VALIDATION_REVIEW.md。
