# 从这里开始：QEC Graph 的 Codex 实现包

这份包同时包含**已经实现的 LaTeX 切割工具、可运行的三视图图谱原型，以及继续开发的工程规范**。可以把整个目录放进 Git 仓库，交给 Codex 读取 `CODEX_TASK.md` 开始工作。

## 先读哪几个文件

| 顺序 | 文件 | 用途 |
|---|---|---|
| 1 | `CODEX_TASK.md` | 可直接交给 Codex 的任务书，规定目标、阅读顺序与交付方式 |
| 2 | `AGENTS.md` | Codex 修改代码和知识记录时必须保持的工程约定 |
| 3 | `docs/01_ARCHITECTURE.md` | 统一架构、权威数据与派生索引、目录和容器边界 |
| 4 | `docs/02_QEC_GRAPH_SPEC.md` | SourceGraph、LemmaGraph、DataGraph 的模型和查询契约 |
| 5 | `docs/03_SPLITTER.md` | 已实现的文件切割工具：安装、运行、输出和限制 |
| 6 | `docs/04_DATA_FORMATS.md` | 论文、定理、QEC 码、矩阵、实验与证据的保存方式 |
| 7 | `docs/05_LEAN.md` | 自然语言定理与 Lean 的映射、依赖、构建及信任检查 |
| 8 | `docs/06_MAINTENANCE.md` | 日常导入、修改、失效、迁移、备份和恢复流程 |
| 9 | `docs/07_CODEGRAPH_MAPPING.md` | 参考哪一个 CodeGraph、哪些设计可借鉴、如何落到本项目 |
| 10 | `docs/08_ROADMAP_ACCEPTANCE.md` | 后续开发顺序、验收条件和失败案例 |

`README.md` 是日常命令入口。`validation/REPORT.md` 和 `validation/results.json` 记录本交付包实际运行过的检查；它们不表示未来路线图已经完成。

## 现在就能运行

以下命令从解压后的项目根目录执行。需要 Python 3.11+，Python 自带的 SQLite 要包含 FTS5。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# 切割：原始源码、按类型存放的 TeX 片段、JSON 记录和索引
qec-latex-split examples/paper/main.tex --project-id qec-demo --out build/split

# 图谱：在相同解析流程上加入显式的数据实体与人工注释
qecgraph ingest examples/paper/main.tex --project-id qec-demo --out build/graph --annotations examples/annotations.example.json

# 验证来源与结构，然后取一个定理的上下文
qecgraph validate --store build/graph
qecgraph context thm:hgp-length --store build/graph
```

Windows PowerShell 的虚拟环境激活命令为 `.venv\Scripts\Activate.ps1`。若不激活，也可以直接调用虚拟环境里的 Python；用 `python -m qecgraph split ...` 等价执行切割。

完整复现入口：

```bash
python tools/reproduce.py --out build/reproduce
```

该脚本运行回归测试、切割、图谱导入、查询和有限 QEC 示例检查，并将真实结果写入输出目录。它不安装依赖，也不运行 Lean 或 Docker。

## 实现边界

- **已实现**：LaTeX 工程递归读取、结构块切割、来源坐标与哈希、标签和引用、三图视图、SQLite/FTS5 查询、依赖及影响查询、上下文导出、sidecar/catalog 导入、不可变快照、审核失效和诊断。
- **带在包里的独立样例**：`knowledge_starter/` 中有结构化 QEC 记录、GF(2) 矩阵、一个普通 HGP `[[13,1,3]]` 示例及有限穷举检查器。图谱导入这些记录不会替代运行这个检查器。
- **Codex 后续实现**：多论文统一注册表、严格领域 Schema 和迁移、审核工作流、真正的增量更新、可选 MCP 服务、可选语义检索、Lean 构建与实际声明导出。详见路线图。

切割结果是完整语义环境及其子块，可能嵌套和重叠；原文件保存在 `sources/`。本工具不把所有片段重新拼成原文，也不保证每个片段能单独编译成 PDF。

## 给 Codex 的第一条消息

可以直接复制：

> 请读取项目根目录的 CODEX_TASK.md、AGENTS.md 和 START_HERE.md，先复现现有工具，再按 docs/08_ROADMAP_ACCEPTANCE.md 逐阶段完善 qec-graph。保留已经工作的 LaTeX 切割工具，使用 SourceGraph、LemmaGraph、DataGraph 三个视图共用的类型化图模型。按 docs/07_CODEGRAPH_MAPPING.md 检查并参考指定 CodeGraph 的实现。请实际修改代码、运行验收并更新完成状态，不要只给实现建议；不要把待实现的功能或未执行的 Lean 构建标为完成。

如果暂时只做文件切割，可以把范围缩为：修复并完善 `docs/03_SPLITTER.md` 和路线图中对应的解析任务，其余阶段保留为待办。

## 目录内资料的优先顺序

本轮任务书和编号文档规定目标；当前代码、Schema 与实际运行报告说明现状。发现两者不一致时，应明确记录差距并按路线图修复，不能静默篡改验收条件。

`docs/reference/` 是上一版原型的细节参考，`knowledge_starter/` 是保留原 Schema 的独立示例。它们不覆盖当前任务书，也不代表未来系统必须原样保留其所有字段。
