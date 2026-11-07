# QEC Graph

从 LaTeX 提取可定位的原文片段，查询 QEC 陈述、实例和证据。项目提供多文档版本注册、审核事务、增量更新、只读 MCP，以及固定工具链的 Lean 构建和声明导出。

首次使用从本页开始；阶段验收和提交记录见 [实施记录](docs/IMPLEMENTATION_LOG.md) 与 [验证报告](validation/REPORT.md)。

项目名 `qec-graph`，Python 包名 `qecgraph`，当前版本 `0.3.0`。`qecgraph` 与 `qec-graph` 是同义 CLI；独立切割入口为 `qec-latex-split`，只读 MCP 入口为 `qecgraph-mcp`。

## 安装

需要 macOS/Linux 的本地 POSIX 文件系统、Python 3.11+ 和支持 FTS5 的 SQLite。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

严格领域验证使用固定的 `jsonschema==4.26.0`，已包含在运行依赖中。
开发依赖入口也保留供已有工作流使用：

```bash
python -m pip install -r requirements-dev.txt
```

命令中的 `qecgraph` 均可替换成 `python -m qecgraph`；`qec-latex-split` 可替换成 `python -m qecgraph.splitter`。

## 1. 切割一份 LaTeX 工程

```bash
qec-latex-split examples/paper/main.tex --project-id qec-demo --out build/split
```

自己的论文可以这样运行：

```bash
qecgraph split /path/to/paper/main.tex --project-id my-paper-v1 --project-root /path/to/paper --out /path/to/output/my-paper-v1
```

`--out` 选择空目录或本工具已经管理的输出目录。`project-id` 使用稳定、唯一的工程标识。多论文和多版本查询使用下文的 corpus 注册表；同一论文的新版本须使用独立 source version ID。

返回 JSON 列出 `snapshot`、`fragment_count`、`fragments_by_kind` 和每个 `.tex`/`.json` 的准确路径。每份快照包含：

| 路径 | 用途 |
|---|---|
| `sources/` | 实际读取的 UTF-8 `.tex` 原文，保持原始换行和文件哈希 |
| `assets/` | 可解析路径的书目与图像资源 |
| `nodes/definition/`、`nodes/lemma/`、`nodes/theorem/` | 定义、引理、定理的 JSON 与 TeX 片段 |
| `nodes/proof/`、`nodes/equation/` | 证明和公式 |
| `nodes/table/`、`nodes/figure/` | 表格、图环境与 caption |
| 其他 `nodes/<kind>/` | 章节、段落、注释与其他已识别对象 |
| `graph.json` | 统一类型化图；其余三个 JSON 是视图 |
| `sourcegraph.json`、`lemmagraph.json`、`datagraph.json` | 来源、定理依赖、数据实体三个视图 |
| `graph.sqlite` | 可重建的关系与全文查询投影 |
| `report.json`、`manifest.json` | 诊断、变化、审核队列、来源与产物哈希 |

`CURRENT.json` 指向当前快照；旧快照保留。切割不是把全文按固定长度剁成互不重叠的字符串：嵌套公式可以同时在完整定理片段和自己的公式片段中出现。原文由 `sources/` 保存，片段不保证单独编译。

详细支持范围、自定义环境配置、API 和退出码见 `docs/03_SPLITTER.md`。

## 2. 加入人工/AI 增补并建立三图

纯切割已经产生可查询图。需要显式数据实体与规范化注释时，用 `ingest` 提供 sidecar：

```bash
qecgraph ingest examples/paper/main.tex --project-id qec-demo --out build/graph --annotations examples/annotations.example.json
qecgraph validate --store build/graph
qecgraph search HGP --store build/graph
qecgraph show thm:hgp-css --store build/graph
qecgraph deps thm:hgp-css --store build/graph
qecgraph deps thm:hgp-css --store build/graph --include-candidates
qecgraph impact def:gf2 --store build/graph
qecgraph context thm:hgp-length --store build/graph
qecgraph context code:qec-demo:reported-rep3 --store build/graph
```

`show` 供检查原始记录和所有关系；`deps/context` 默认排除未确认候选和 stale/unbound/unresolved 关系。返回内容仍可能含作者声明和来源报告值，不能直接读成数学证明。

一个维护中的 store 若使用了 sidecar/catalog，后续更新仍应传入它们。`split` 是 source-only，若对同一个 store 运行，会让 CURRENT 转向没有这些增补的快照；旧快照仍保留。

## 3. 连到已有 QEC 数据记录

本包保留了 `knowledge_starter/` 的 10 条 JSON 记录、6 份 GF(2) 矩阵与检查器。示例用重复码种子构造普通 HGP `[[13,1,3]]`，可以运行有限穷举检查：

```bash
python knowledge_starter/tools/qec_kb.py verify --json-schema
python knowledge_starter/tools/qec_kb.py index
python knowledge_starter/tools/qec_kb.py codes --n-min 13 --n-max 13 --distance-at-least 3 --construction ordinary_hgp
```

单独使用旧样例而未安装本项目时，可省略 `--json-schema`。该检查器只验证随包的有限示例，不能当作通用大码距离求解器。

将记录与论文来源连接：

```bash
qecgraph ingest examples/paper/main.tex --project-id qec-demo --out build/catalog --catalog knowledge_starter/records --annotations examples/catalog-links.example.json
qecgraph context code:rep3-hgp:13 --store build/catalog
```

catalog 导入保留原记录内容和历史证据。需在 corpus 内携带原始矩阵资产时，请用 [显式迁移](docs/09_CORPUS.md#显式迁移和资产)。

## 4. 注册版本与接入查询工具

```bash
qecgraph register --store build/graph --corpus build/corpus --work-id work:demo --source-version-id version:demo:1
qecgraph context 'version:demo:1::thm:hgp-length' --corpus build/corpus
qecgraph mcp-config --corpus build/corpus
```

`mcp-config` 打印绑定当前 corpus revision 的本地只读客户端配置。常用工作流：
[注册、迁移和固定版本](docs/09_CORPUS.md) · [类型检查和 review/apply](docs/10_VALIDATION_REVIEW.md) ·
[strict 发布、watch 和恢复](docs/11_INCREMENTAL.md) · [MCP 客户端](docs/12_AI_MCP.md) ·
[Lean 构建、审计和导入](docs/13_LEAN_EXECUTION.md)。

运行 `python tools/reproduce.py --out build/reproduce` 可复现 Python 回归和示例。
生成的 sidecar 演示快照位于 `build/reproduce/graph`。增量、MCP、Lean 和干净安装的
独立验收命令见 [发布复现](docs/14_RELEASE.md)。

## 5. 可选容器入口

已提供 research CLI 的 `Dockerfile` 和 `compose.yaml`；本次没有运行 Docker 构建，需在使用环境中验证。

```bash
mkdir -p build/container
docker compose build research
QEC_UID=$(id -u) QEC_GID=$(id -g) docker compose run --rm research
```

这里的 `QEC_UID/QEC_GID` 适用于 Linux/macOS shell，解决输出目录的宿主用户权限。Compose 默认只读挂载示例输入、向 `build/container` 写输出；运行期不需要网络。生产复现应先验证具体镜像，再记录实际 digest 和依赖锁。Lean 使用独立环境，详见 `docs/05_LEAN.md` 与 `docs/06_MAINTENANCE.md`。

## 6. 当前与后续的边界

| 能力 | 当前状态 |
|---|---|
| 语法切割、来源位置、引用和资源 | 已实现，支持范围和诊断见 splitter 文档 |
| 单工程三视图、全文查询、依赖、影响和上下文 | 已实现 |
| sidecar 和旧 catalog 的显式导入 | 已实现；人工审核应绑定真实哈希 |
| 多论文 registry、规范 claim 独立修订、固定 corpus 查询及旧格式迁移 | P1 已实现，命令与边界见 docs/09_CORPUS.md |
| 严格领域验证、review/apply 事务、证据条件筛选与失效 | P2 已实现，见 docs/10_VALIDATION_REVIEW.md |
| 逐文件 AST 复用、polling watch、单写者锁和 strict 发布 | P3 已实现；语义图/投影仍全量重建，见 docs/11_INCREMENTAL.md |
| 固定版本只读 AI 工具与 MCP stdio | P4 已实现；官方 2025-06-18 协议，CLI/Python/MCP 一致，见 docs/12_AI_MCP.md |
| 语义向量检索、PDF/OCR、通用代码仓库解析 | 可选扩展；当前未实现 |
| Lean 实际构建、声明/依赖导出、公理审计 | P5 已实现；固定 Lean 4.19.0，完成有限 Bool 向量点积对称性与具体校验行对易，见 docs/13_LEAN_EXECUTION.md |

本工具解析受支持的 TeX 结构，不运行 TeX 引擎或推断 PDF 页码。`\leanok` 只记录作者标注。
`validate` 检查结构和来源；数学计算、Lean 内核构建和语义审核分开报告。
普通 HGP `[[13,1,3]]` 的距离为有限 Python 计算结果，当前未形式化。

## 参考与归属

CodeGraph 的提取、存储、解析关系和上下文设计是架构参考；固定提交、许可证和查阅路径见 [ADR 0001](docs/adr/0001-codegraph-reference.md)。
Lean 与候选库的使用范围见 [ADR 0003](docs/adr/0003-lean-boundary.md)。本包没有内嵌第三方依赖源码。
