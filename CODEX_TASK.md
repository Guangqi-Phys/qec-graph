# Codex 任务书：完善 LaTeX 切割工具与 QEC Graph

本文件保留原交接任务和验收约束。当前能力、依赖与命令以 [README](README.md)、
[实施记录](docs/IMPLEMENTATION_LOG.md) 和 [验证报告](validation/REPORT.md) 为准。

你负责在这个目录的**已运行原型**上继续开发一个长期可维护、便于 AI 查询和 Lean 构建的 QEC 知识工具。请实际读代码、修改代码、运行验证和更新文档，不要只输出设计建议。

## A. 用户目标

用户整理量子纠错论文、代码、矩阵、定理、实验和形式化证据，希望 AI 能回答：

1. 某条引理在哪里提出，准确陈述、假设和证明原文是什么？
2. 它使用了哪些定义和前提？哪些是作者显式声明、人工审核或 Lean 实际证明依赖？
3. 某个码属于什么构造，有哪些具体校验呈现、矩阵、电路、译码器和实验结果？
4. 参数或距离的证据来自文献、计算、证书还是 Lean？是上界、下界还是精确值？
5. 更新一个来源版本、定义、矩阵或 Lean 声明后，哪些索引和审核需要重做？
6. 怎样只给 AI 有关且可追溯的上下文，同时保留未确定项与冲突？

交付的产品由两部分组成，共用底层模型：

- **文件切割工具**：Python 实现的 LaTeX 工程解析、分类片段、完整来源与清单。
- **QEC Graph**：一个类型化图，提供 SourceGraph、LemmaGraph、DataGraph 三种视图及查询接口。

这里的 SourceGraph 是论文/数据来源视图，不指同名商业代码检索产品。参考的 CodeGraph 是 `https://github.com/colbymchenry/codegraph`。

## B. 先阅读，再复现

按以下顺序工作：

1. 读 `AGENTS.md` 和 `START_HERE.md`，确认当前工具与未来目标的区别。
2. 读 `docs/01_ARCHITECTURE.md`、`docs/02_QEC_GRAPH_SPEC.md` 和 `docs/03_SPLITTER.md`。
3. 读 `docs/04_DATA_FORMATS.md`、`docs/05_LEAN.md`、`docs/06_MAINTENANCE.md`。
4. 读 `docs/07_CODEGRAPH_MAPPING.md` 与 `docs/08_ROADMAP_ACCEPTANCE.md`，使用其中的 P0–P5 阶段编号。
5. 检查当前 `qecgraph/`、`schemas/`、`tests/` 和 `examples/`，不要按文档猜测函数已存在。
6. 安装并执行 `python tools/reproduce.py --out build/reproduce`。保留运行结果，失败则先修复具体问题。

现有入口：

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python tools/reproduce.py --out build/reproduce
```

开发可选依赖见 `requirements-dev.txt`；没有可选 JSON Schema 库时，复现脚本必须明确记录跳过的 Schema 检查，不能说完整检查已通过。

## C. 正确使用现有代码

| 路径 | 当前职责 | 修改原则 |
|---|---|---|
| `qecgraph/parser.py` | 使用 pylatexenc 的语法结构提取与原始 span | 保留位置、换行和诊断；不要以正则整篇切割替代 |
| `qecgraph/splitter.py` | 明确的切割 API/独立命令 | 复用解析及快照流程，不建立第二份解析真相 |
| `qecgraph/graph.py` | 节点身份、标签消歧、关系、sidecar/catalog | 保留来源块与语义事实之间的边界 |
| `qecgraph/store.py` | 快照、输入指纹、JSON/SQLite 投影与验证 | 当前单写者；并发支持需另外实现与测试 |
| `qecgraph/query.py` | search/show/deps/impact/context | 保持状态过滤、截断提示与来源绑定 |
| `qecgraph/cli.py` | 命令入口、JSON 输出与退出码 | 原命令保持可用；新命令先定义输入输出契约 |
| `knowledge_starter/` | 旧 Schema 的完整 QEC 示例 | 用显式适配和迁移接入；不要直接覆盖证据 |

当前运行依赖为 `pylatexenc==2.10` 与 `jsonschema==4.26.0`。SQLite 与 unittest 使用 Python 标准库。若升级解析器，必须记录兼容性、更新指纹与测试。

旧的 `docs/reference/` 可用于理解原型实现细节，但不是未来版本的最高规范。记录差距、修改代码和文档；不要通过删掉失败用例来让报告变绿。

## D. 参考 CodeGraph 的具体任务

按 `docs/07_CODEGRAPH_MAPPING.md` 执行：

- 读取官方仓库和架构说明，记录实际检查到的 commit、许可证与对应模块路径。
- 重点分析 extraction、storage、resolution、query/context、watch/sync 的边界和无效化策略。
- 将代码符号/调用关系替换为本项目的文献块、规范 claim、实体、来源和证据关系。
- 保留 Python 主实现；优先借鉴架构与测试模式，不因为参考项目使用另一语言就整体改写。
- 若引用代码，按实际许可证保留归属；未阅读的实现不写成“已复用”。网络受限时记录未完成的参考核对，继续实现已有明确规范的工作。

不要沿用 CodeGraph 的性能数字来描述本项目；只有对本项目实际数据运行过的测量才可写入报告。

## E. 开发顺序与阶段交付

正式任务和逐项验收以 `docs/08_ROADMAP_ACCEPTANCE.md` 为准。执行顺序如下：

| 阶段 | 目标 | 完成后应有的成果 |
|---|---|---|
| P0 | 固定原型与复现闭环 | 双切割入口、完整演示、回归与真实报告；本包已有起点 |
| P1 | 多文档注册表与规范化 claim 身份 | 稳定 work/version/entity 身份，跨文档查询，来源到 claim 的多对多映射 |
| P2 | 类型验证与 review/apply 事务 | 严格领域验证、增补提案和审核绑定、失败回滚、迁移与失效 |
| P3 | 增量重建与 watch | 输入依赖追踪、单写者锁、原子发布、可恢复更新 |
| P4 | 只读 AI 接口与 MCP | 受限且有来源的查询工具、契约测试、客户端接入说明 |
| P5 | Lean 真实声明／依赖／验证导出 | 固定构建的声明类型、真实依赖、公理与语义映射 |

P1 依赖 P0；P2 依赖 P1；P3/P4/P5 都在 P1/P2 基础上推进，可相互独立。用户若只指定某个阶段，就完成该阶段并保留其余待办；未另行限定时按此路径持续推进，分阶段报告和提交，不把整个平台一次性重写。

每阶段：先给出简短实现清单，随即实际实施；增加必要的失败案例；运行相关门禁；更新变更说明和已实现能力清单。只在真正缺失外部输入或访问权限且无可继续工作时说明阻塞。

## F. 数据和数学不变量

这些要求不可因实现方便而放宽：

1. 原始资产及其具体版本可定位；每个来源片段能回查到完全相同的原文切片。
2. 文件名、label、object ID、revision、content hash 各有含义，不互相替代。
3. 同一字段只有一个权威可编辑位置；SQLite、图视图、向量索引是可重建投影。
4. 自动语法识别不提升为数学事实；AI 生成提案默认未审核。
5. 背景引用不当作证明依赖；计划依赖不当作 Lean 证明项依赖。
6. 没有 evidence 的距离数字不作已验证硬条件；上界不能满足 `distance >= d` 的下界查询。
7. 码族、构造、码实例和校验呈现分开；构造输入与矩阵列序明确保存。
8. LER 的事件、分母、采样方案、电路、噪声、译码器和版本配置明确，不能用简单除法混用统计量。
9. 资料审核、计算验证、Lean 构建、公理审计、语义对应分别记录，旧证据不能自动作用于新版本。
10. 查询带快照/版本、可追溯来源、证据等级与截断信息；不知道时明确不知道。

## G. 文件、环境和依赖

- 起步使用 Git + 文件资产 + SQLite/FTS5。不要因“图谱”一词强制引入 Neo4j、Kubernetes 或常驻微服务。
- Python 研究环境与 Lean 构建环境分开；依赖和镜像按实际版本固定。模板里的空值不是可接受的运行证据。
- `Dockerfile`、`compose.yaml` 是可选 research 运行入口，本次交付未验证 Docker 构建。先在可用环境构建并运行后，再标为通过。
- 大型实验输出可以使用 Parquet/外部对象存储；其资产 ID、校验和、许可与路径仍进入记录。数据库升级取决于真实并发和访问需求。
- 不把临时日志、缓存或可再生索引混入人工权威记录；但发布的关键证据和可复现实验结果应持久保存。

## H. 每次交付必须说明

- 本阶段解决了哪个具体用户问题；新增/修改了哪些模块和 Schema。
- 哪些命令可直接执行，示例从输入到输出怎样走通。
- 实际执行过的测试、输出与环境；未执行项和剩余限制。
- 是否涉及身份、来源、审核状态或 Schema 迁移；怎样回滚。
- 下一阶段剩余任务，不能把“有接口名称”“有示例 JSON”“有 TODO”当作完成实现。

在没有用户明确要求部署或发布时，交付本地可复现代码、记录、测试和文档即可，不需要创建外部服务。
