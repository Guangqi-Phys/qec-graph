# 06｜日常运行、失效传播、迁移与恢复

工作区日常运行 `init`、`sync`、`status` 和 `validate)，见[工作区说明](rfc-002/WORKSPACE.md)。
本文件保留单论文 store 与 legacy corpus 的维护流程。
运行时先读本包 `AGENTS.md`、[架构](01_ARCHITECTURE.md) 和 [数据契约](04_DATA_FORMATS.md)。
以下命令以本包根目录为工作目录；各步骤成功后再执行下一步。

## 1. 首次安装与基线

当前需要本地 POSIX 文件系统、Python 3.11 或以上以及可用的 SQLite FTS5。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

安装步骤需要相应包源可用。记录实际 Python、SQLite、操作系统和安装依赖，不能把示例环境假设为已安装。
运行依赖固定 `pylatexenc==2.10` 和 `jsonschema==4.26.0`；升级解析器应单独提交并检查语义输出差异。
旧领域样例可以独立验证；以下调用也重新计算有限 HGP 实例，不调用 Lean：

```bash
python knowledge_starter/tools/qec_kb.py verify
```

使用 `verify --json-schema` 可显式开启旧样例的 Schema 检查。
普通 verify 的引用、资产和计算检查不应被报告为“已执行完整 JSON Schema 验证”。

## 2. 日常 ingest 与查询

先保存完整原始项目到受管理位置；本例使用仓库自带演示输入。

```bash
qecgraph ingest examples/paper/main.tex --project-id qec-demo --out build/demo --annotations examples/annotations.example.json
qecgraph validate --store build/demo
qecgraph show thm:hgp-css --store build/demo
qecgraph deps thm:hgp-css --store build/demo
qecgraph context thm:hgp-length --store build/demo
```

只需要原文切块时使用 [03](03_SPLITTER.md) 的 `qecgraph split` 流程。
接入旧领域样例时可给 ingest 增加 `--catalog knowledge_starter/records`；它只导入 JSON 记录。
旧记录引用的矩阵、验证脚本与报告依旧位于完整 `knowledge_starter/` 中，必须一起保存。
每次运行记录输入路径、命令、退出码、snapshot ID 和 diagnostics。
退出码 2 表示抽取为 partial；即使已经产生快照，也不能对外宣称完整抽取。
`validate` 检查哈希、定位、边端点与 SQLite 一致性，不检验定理、矩阵语义或 Lean 证明。
查询默认排除候选、stale、unbound 等依赖；查看候选时显式加 `--include-candidates`。
同一 AI 工作任务固定 snapshot ID；若 CURRENT 改变，先决定继续旧任务或重新取上下文。
一致读取使用 `--snapshot <id>` 或 corpus 的 `--registry-revision <revision>`，并核对返回作用域。

## 3. 每次改动的操作顺序

1. 明确字段的权威文件；编辑 JSON／sidecar／源码，不编辑生成的节点或 SQLite。
2. 取得当前 Git 提交和输入资产清单，保存原始文件；论文新版本新增 SourceVersion。
3. 修改记录，保留原文和规范化文本的区别，列明新增或改变的假设。
4. 运行相关结构检查、引用检查及有实质意义的回归；数值结果执行其专用验证器。
5. 在 staging 输出目录生成快照，读取诊断并验证；不要直接以试运行替换正式查询入口。
6. 审核语义、更新必要绑定，再在正式 store 生成相同输入的快照并发布。
7. 提交人工记录和代码，归档重要报告；将发布提交、输入清单与 snapshot ID 关联。

默认 ingest 会在完整性验证后发布 partial 快照；正式发布可用 `--strict`，partial 保存在 staging 且 CURRENT 不变。
详见 [增量和恢复](11_INCREMENTAL.md)。
同一输入、配置、工具源码和依赖指纹再次 ingest 应复用相同 snapshot ID。
已发布快照只读；发现损坏应保留现场并从输入重建到新的 store，不能修改清单掩盖损坏。

## 4. 失效传播与审核

| 发生变化 | 最少需要复核的内容 |
|---|---|
| 原文定理或定义 | 关联规范化 claim、语义审核、依赖及 Lean 映射 |
| 矩阵或列序 | 秩、对易、逻辑代表、距离证据、依赖该表示的 SEC |
| circuit／noise／decoder | 运行输入身份、结果可比性、相关统计和图表 |
| 检查器代码或配置 | 其证据适用性及需要重跑的结果 |
| Lean 类型或 imports | 构建、实际依赖、axiom 信息和语义对应 |
| 分块器或 embedding 模型 | 对应查询投影；永久来源身份不改变 |

旧 sidecar 按项目 source hash 绑定审核；corpus 按记录修订、来源版本和资产绑定。
即使只改无关段落，旧 sidecar 审核也可能保守标为 stale。
逐文件 AST 复用和 watch 已实现，语义投影每次重建；当前没有通用领域产物的增量依赖闭包。
目标任务清单应记录输入 ID＋revision＋hash、处理器版本、配置、输出及依赖边。
建立完整依赖闭包后再按变化传播；未解析依赖应显式阻止“全部仍有效”的结论。
依赖方向和反向影响查询按 [02](02_QEC_GRAPH_SPEC.md) 执行，不把普通引用一律当证明依赖。
旧证据继续属于旧输入，不因失效被删除；新结果与旧结果通过后继关系连接。
审核更新必须重新比较陈述、假设和依赖，不能仅把 expected hash 替换成新值。

## 5. 索引重建与原子发布

SQLite、FTS 和向量索引由权威记录生成。新索引在临时目录完整构建、校验，然后切换入口。
当前会先生成完整快照，再原子替换 `CURRENT.json`；本地 POSIX writer lock 拒绝跨进程并发写入。
用 `recover-store` 检查发布状态，详见 [11](11_INCREMENTAL.md)。
不要混用一个快照的关系表和另一个快照的全文或向量数据。
新增索引记录 source snapshot、Schema、模型版本、维度、归一化、配置及输入文本哈希。
中文召回、定理完整性、参数硬条件和来源定位都进入查询回归；向量相似度不决定证据等级。
使用保存的完整输入重新 ingest 到另一 store 可以重建投影。
SQLite 若以后保存不可重建的独有数据，应采用一致性快照或官方 Backup API 保存运行中数据库。[1]

## 6. Schema 迁移与回滚

迁移先确定改变的是记录结构、字段含义、哈希协议、图视图还是执行环境。
在专门分支和副本中实现单向迁移，保留旧 Schema、旧数据与转换映射。
迁移报告至少记录输入／输出版本、处理数量、被拒绝记录、ID 映射和字段含义变化。
检查必填字段、枚举、唯一 ID、引用完整性、资产哈希、审核绑定及代表性查询。
数学度量或单位改变时新增定义修订；不能只修改字段名而复用旧证据。
旧 `0.1.0` records 和 `qecgraph.graph.v1` 的迁移分别处理，不把它们当同一版本轴。
新旧 canonicalization 并存期间保存协议标识；不得批量重算哈希后宣称旧审核仍然有效。
在新输出位置完成验证后再切换读取端；写入端同时更新，避免旧写入器继续产生旧格式。

使用 [migrate / migration-import](09_CORPUS.md#显式迁移和资产) 将旧格式适配到新目录。
回退优先固定到已验证的历史快照或 registry revision，必要时恢复整套 store 和对应输入／工具版本。
若由维护者手工回退 CURRENT，先停止写者并验证目标快照，再按现有 pointer 格式原子替换。
pointer 包含 `format: qecgraph.current.v1`、目标 `snapshot_id` 和 `path: snapshots/<snapshot_id>`。
不要删除新快照来完成回退；保留故障证据与回退原因。数据库迁移不可逆时恢复备份副本。
对外记录回退的准确快照；“最新版”不是可复现引用。

## 7. 备份与恢复演练

| 必须备份 | 为什么 |
|---|---|
| Git 历史、人工 JSON、sidecar、说明、Schema 和源码 | 人工决策与可追踪修改 |
| 完整原始论文项目、PDF、上游代码和资产清单 | 抽取快照不保存所有源工程资源 |
| 矩阵、证书、人工校正和高成本结果 | 无法由 Git 远端或摘要自动恢复 |
| run 的配置、原始统计、执行环境和证据 | 能复核估计量和适用输入 |
| 已发布快照及其报告，或足够的完整重建输入 | 恢复已引用的查询状态 |
| 完整 `knowledge_starter/` | catalog 导入没有复制它的引用资产 |

备份不等于 Git push；未追踪的大文件和容器 volume 必须纳入独立清单。
建议每日保存人工变更、重要运行结束后立即保存成果，并保留至少一份独立故障域的备份。
这属于项目运维策略，具体保留周期由资料规模、重算成本和可接受数据损失决定。
加密和访问权限沿用实际资料要求；凭据不进入记录、镜像或公开归档。

恢复演练按以下顺序执行：

1. 在空目录恢复指定 Git 提交、所有资产、清单和已发布 store；不覆盖仍在工作的目录。
2. 核对原始资产字节哈希，并确认来源版本、sidecar 和 catalog 相对路径可以解析。
3. 运行 `qecgraph validate --store <恢复的store路径>`，检查诊断和完整性。
4. 使用归档输入与对应工具版本在另一目录重新 ingest，核对节点、来源定位和预期快照。
5. 重跑关键结构化查询及有界上下文；对本包旧例运行 `python knowledge_starter/tools/qec_kb.py verify`。
6. Lean 项目按 [13](13_LEAN_EXECUTION.md) 用固定工具链重建并检查证据；不可复建的记录只作为历史读取。
7. 记录恢复耗时、缺失资产、差异与修复动作，通过后再切换正式读取入口。

恢复测试失败时先补齐备份或修复流程，不能仅因为备份任务退出成功就标记“可恢复”。

## 8. 可选容器部署规范

当前提供 `Dockerfile` 和 `compose.yaml`，仅配置 research CLI；本次交付没有执行 Docker 构建或运行。
模板基镜像为 `python:3.12-slim`，可用 `QEC_PYTHON_IMAGE` 指定经实际验证的 digest；该浮动标签不构成完整环境锁。
模板把 `./examples/paper` 只读挂到 `/input`，把 `./build/container` 挂到 `/output`，默认执行 split。
运行进程的 UID/GID 由 `QEC_UID/QEC_GID` 指定，默认均为 1000；输出目录须先存在且允许该用户写入。
运行期为只读根文件系统、禁用网络，`/tmp` 使用 tmpfs；镜像构建仍需获取依赖或使用已有缓存。
后续 research 镜像应补齐系统依赖锁。Lean 本机复现固定 4.19.0，工程未配置 Lean 镜像。
需要 PDF 解析时再增加 parser 服务，保持输入资源限制和独立输出目录。

| 路径角色 | 挂载和生命周期 |
|---|---|
| 原始资产、已发布矩阵／证据 | 只读挂载 |
| 人工记录 | 查询／检查时只读；编辑时使用独立 Git 工作目录 |
| 新结果、运行报告 | 明确的持久输出挂载 |
| SQLite／索引、Lean 构建缓存 | 分离的可重建目录或 volume |
| 临时展开和解析文件 | 独立临时目录，用后清理 |

Docker 可写层随容器销毁而消失，volume 生命周期独立；永久成果必须放到受管理的持久挂载。[2]
源码需要宿主机编辑时使用 bind mount；服务数据库可使用命名 volume，并纳入备份流程。
不把 Docker socket、宿主机凭据或整个资料目录作为解析任务的默认可写挂载。
镜像选定并实际运行后才填写 digest；离线复现还需可取得的镜像或构建输入。
容器内运行同样的基线和恢复检查；容器启动成功不代表数据和数学结论正确。
多人持续写入或远程事务成为需求时再采用 PostgreSQL；SQLite 的本地定位与并发边界见官方说明。[3]

## 主来源

1. [SQLite Backup API](https://www.sqlite.org/backup.html)
2. [Docker 存储](https://docs.docker.com/engine/storage/)
3. [SQLite 适用场景](https://www.sqlite.org/whentouse.html)
4. 本包实际实现：`qecgraph/store.py`、`qecgraph/cli/`、`tests/`。
5. 旧样例运行与证据：`knowledge_starter/tools/qec_kb.py`、`knowledge_starter/docs/VALIDATION.md`。
