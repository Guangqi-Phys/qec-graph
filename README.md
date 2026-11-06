# QEC Graph · Codex 实现包

Python 实现的 LaTeX 文件切割工具和 QEC 知识图原型，并附上继续开发所需的架构、数据格式、维护规范、Lean 接入设计和阶段验收。

**交给 Codex：先读 `START_HERE.md` 与 `CODEX_TASK.md`。** 日常操作从本页开始。

项目名 `qec-graph`，Python 包名 `qecgraph`，交付版本 `0.2.0`。`qecgraph` 与 `qec-graph` 是同义 CLI；独立切割入口为 `qec-latex-split`。

## 安装

需要 Python 3.11+，Python 自带 SQLite 支持 FTS5。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

可选的完整 JSON Schema 验证依赖：

```bash
python -m pip install -r requirements-dev.txt
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活虚拟环境。命令中的 `qecgraph` 均可替换成 `python -m qecgraph`；`qec-latex-split` 可替换成 `python -m qecgraph.splitter`。

## 1. 切割一份 LaTeX 工程

```bash
qec-latex-split examples/paper/main.tex --project-id qec-demo --out build/split
```

自己的论文可以这样运行：

```bash
qecgraph split /path/to/paper/main.tex --project-id my-paper-v1 --project-root /path/to/paper --out /path/to/output/my-paper-v1
```

`--out` 选择空目录或本工具已经管理的输出目录。`project-id` 使用稳定、唯一的工程标识。当前原型没有跨版本注册表；如果希望两个论文版本同时独立查询，给它们不同 project-id/store，并在后续 registry 中记录它们属于同一 work。

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

不安装可选 jsonschema 时，省略 `--json-schema`。该检查器只验证随包的有限示例，不能当作通用大码距离求解器。

将记录与论文来源连接：

```bash
qecgraph ingest examples/paper/main.tex --project-id qec-demo --out build/catalog --catalog knowledge_starter/records --annotations examples/catalog-links.example.json
qecgraph context code:rep3-hgp:13 --store build/catalog
```

catalog 导入保留原记录内容，不重新执行数学验证，也不把外部矩阵资产复制到快照。请保留整个 `knowledge_starter/`，不要只拷走 `records/`。后续资产注册与来源解析见路线图。

## 4. 实际验证

```bash
python -m unittest discover -s tests -v
python tools/reproduce.py --out build/reproduce
```

本交付包完整运行了 **24 项测试**，并验证了切割、sidecar 导入、catalog 连接、查询、Schema 和有限 QEC 示例。演示工程有 3 个源文件、26 个语义片段；加入 sidecar 后为 36 个节点、97 条边。完整证据与运行边界见 `validation/REPORT.md`、`validation/results.json`。

`example_output/` 保存一份实际生成的 sidecar 演示快照，可直接运行：

```bash
qecgraph validate --store example_output
qecgraph context thm:hgp-length --store example_output
```

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
| 严格领域验证、review/apply 事务 | 后续 P2 |
| 真正增量解析、watch、多写者协调 | 后续 P3；目前每次完整重建 |
| MCP 服务与跨客户端 AI 工具接入 | 后续 P4；当前是 CLI/Python/JSON |
| 语义向量检索、PDF/OCR、通用代码仓库解析 | 可选扩展；当前未实现 |
| Lean 实际构建、声明/依赖导出、公理审计 | 后续 P5；当前未执行 |

本工具不执行 TeX、不展开任意用户宏、不计算 PDF 页码，也不自动判定定理真伪。`\leanok` 只保留作者标注。一次成功的 `validate` 表示结构、哈希和来源检查通过，不表示数学或 Lean 验证通过。

## 参考与归属

CodeGraph 的提取、存储、解析关系和上下文设计是架构参考，未在本包中复制或封装它的实现。外部参考的固定 commit 和许可证检查是 Codex 后续任务，见 `docs/07_CODEGRAPH_MAPPING.md`。运行依赖 pylatexenc 使用其自身许可；本包没有内嵌第三方依赖源码。
