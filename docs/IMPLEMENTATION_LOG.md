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
| 09 | P2 | 距离、矩阵和实验条件验证与筛选 | 完成 |
| 10 | P2 | review 提案、身份类别与输入绑定 | 完成 |
| 11 | P2 | 原子 apply、锁、冲突和幂等 | 完成 |
| 12 | P2 | 状态兼容、资源失效及审核逻辑环 | 完成 |
| 13 | P3 | 写者锁、strict staging 与发布恢复 | 完成 |
| 14 | P3 | 输入依赖指纹及安全解析缓存 | 完成 |
| 15 | P3 | watch 调度、变更和全量一致性 | 完成 |
| 16 | P3 | 恢复演练和真实增量测量 | 完成 |
| 17 | P4 | 只读工具契约、固定作用域和预算 | 完成 |
| 18 | P4 | MCP stdio 传输及协议测试 | 完成 |
| 19 | P4 | CLI/Python/MCP 一致性和客户端说明 | 完成 |
| 20 | P5 | 固定 Lean 工程和边界清晰的实际结果 | 完成 |
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

## 09 · 数学插件与精确筛选

新增 validators/qec.py、domain_query.py 和 check-css/check-experiment/codes。上界、未知下界、度量/sector 不符、无当前绑定证据或资产变化不会匹配下界硬条件。GF(2) 秩、CSS 对易、逻辑配对和受预算限制的完整穷举独立报告；实验区分采样、分母与可比性。全量 unittest 44 项通过；实际 check-css 输出 n=13、k=1、dX=dZ=3，保存在 validation/p2/css-check.json，未执行 Lean。

## 10 · 可审阅提案与决定

新增 review.py、proposal/review v1 Schema、review/review-decide 命令和示例。绑定 corpus 身份、差异、输入修订、来源及实际资产；明确区分 human/ai/program。AI/program 接受只为 machine_accepted，不提升人工或 Lean 状态；复制旧审核、过期输入、跨 corpus 和变化资产均拒绝。全量 unittest 49 项通过；实际示例提案和 AI 决定保存在 validation/p2。按计划在本步提交后执行首次 push。

## 11 · 原子 apply

第 10 步 0ff466e 已成功推送 origin/main；HTTPS 默认凭据缺失，通过现有 gh keyring 认证临时 helper 完成，无全局配置修改。新增 apply CAS、整批验证、不可变 receipt 和单指针发布；重复 apply 返回相同 receipt，错误/旧提案不覆盖，注入指针失败后旧状态可读且重试恢复。全量 unittest 54 项通过；实际示例连续 apply 两次一致，证据见 validation/p2/application.json。AI 决定后的记录保持 proposed。

## 12 · 状态、失效与 P2 验收

新增共享 status.py；遍历、proof/祖先补入、最终边和注释一致过滤候选及失效。人工审核从固定版本记录、来源和实际资产派生 freshness；历史决定保持不可变，依赖变化/资产缺失时 stale。仅审计有效 depends_on_reviewed SCC，v1 status=declared 保持兼容，引用环不报 DAG 错误。完整 reproduce-p2 退出 0、58 项回归通过；报告见 validation/p2。P2 完成，POSIX/CAS 保守范围和数值插件限制见 10_VALIDATION_REVIEW.md。

## 13 · 发布与恢复

store/split 共享目录保护和跨进程锁；增加 strict partial staging（旧默认 partial 发布和退出 2 不变）、单独 staged 验证和受控遗留构建清理。项目管理标识阻止无 CURRENT 时串用 store。跨进程争用与 os._exit 崩溃测试确认锁释放，未识别目录不会被恢复命令删除。全量 unittest 62 项通过，见 11_INCREMENTAL.md 的本地 POSIX 边界。

## 14 · 内容指纹和 AST 复用

新增 incremental.py 和 --incremental；白名单 JSON 编码逐文件 AST，绑定源字节、上下文、配置与处理器版本，继续全量语义发现/资源/审核/投影重建。宏、include 拓扑和未解析依赖保守全量回退。测试全量/增量图、三视图、来源和 context 一致，覆盖同 mtime/大小内容变化、文件增删移动、配置/宏、资产失效、损坏缓存及构建途中保存。全量 unittest 67 项通过。发布前重新核对输入，缓存状态写入问题不把已发布结果误报为构建失败。

## 15 · 内容核对 watch

新增 watch.py/CLI，轮询内容、debounce 批量保存，忽略编辑器临时文件并跟踪显式资源与外部 sidecar/config/catalog。失败不推进 accepted_signature，锁释放后同输入重试；构建中再变更继续核对。strict partial 保留 staging，恢复 include 后与显式 ingest 一致。逐行 JSON 事件与停止摘要，不启动后台服务。全量 unittest 71 项通过，包括 --once CLI/显式流程一致性。

## 16 · P3 恢复与测量验收

新增 tools/reproduce_incremental.py，实际生成 13 份源文件/96 个 lemma，交替全量/增量运行，保存 cold、unchanged、leaf_edit、asset_edit 的本机测量。每轮快照、三视图和查询一致；备份搬迁、原路径消失、输入重放、遗留清理、strict partial/恢复及故意损坏检测全部通过。完整 reproduce-p3 和 71 项回归通过；实际 watch --once 与 split 快照相同。报告见 validation/p3。P3 完成，测量仅限生成工作负载，不承诺普遍加速。

## 17 · 只读工具契约

新增 ai_tools.py、query-tool、ADR 0002 和 12_AI_MCP.md。固定 snapshot/corpus scope，复用 query 层，逐次核对固定产物；输入 Schema 限制路径、节点、深度和 JSON 字符预算。保留完整根陈述，无法容纳时拒绝而非切断假设；来源/证据/partial/空结果可观察。修复核心搜索 limit 和深度边界截断提示，以及明确 unresolved_reference 的类型兼容。全量 unittest 76 项通过，工具定向复验 5 项通过；CLI/Python envelope 一致、只读文件哈希不变。MCP 传输尚未实现。

## 18 · MCP stdio

新增 mcp_server.py、serve-mcp 和安装别名，固定官方协议 2025-06-18。握手/版本协商、五个只读工具、JSON-RPC/业务错误区分、structuredContent/text 双输出、请求字节限制与调用频率限制均实现。stdout 仅协议消息；无写工具、HTTP 或自动构建。实际 subprocess 连接及畸形 JSON/UTF-8/帧大小/错误范围/只读与 TeX 命令不执行测试通过。全量 unittest 80 项通过。

## 19 · P4 实际客户端验收

新增 tools/reproduce_mcp.py、mcp-config 和客户端样例。真实交互 subprocess 客户端完成 22 项断言：全部工具跨入口同 envelope、固定旧 store/corpus、空结果、重复 label、scope 拒绝、节点/根文本预算、候选过滤及 partial。固定 corpus 的原件损坏也逐次拒绝，未更改外部客户端配置。完整 reproduce-p4-final 和 81 项回归通过；报告、协议 transcript 与本机可审阅配置保存在 validation/p4。P4 完成。

## 20 · 实际 Lean 工程

官方 Lean 4.19.0 已在忽略的 .tools 中安装；固定 commit 6caaee842e9495688c1567e78c0e68dbb96942aa，实际下载 hash 与许可证核对见 ADR 0003。静态检查固定 mathlib/QECert/QECLean 定义，不采用或声称构建候选库。新增 core-only lean 工程、固定 n 的 Bool 向量/dot 对称性与具体二元行对易实例；lake clean/build 实际通过，81 项 Python 回归通过。新增显式构建报告工具，保存源码/依赖/工具/日志与 dirty patch 绑定。step20 初次证据准确标为未提交工作树，提交后将复验固定提交并执行第二次 push；声明导出与公理审计仍未执行，旧 HGP 距离不提升。
