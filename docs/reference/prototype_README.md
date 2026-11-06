> 历史参考：本文保留上一版原型说明。当前入口和规范见项目根目录 `START_HERE.md` 与编号文档；本次执行结果见 `validation/REPORT.md`。文中旧相对路径、版本和测试计数按历史语境理解。

# QEC LaTeX Graph

把 LaTeX 工程整理为带来源的结构片段和可查询关系图。一个图提供 SourceGraph、LemmaGraph、DataGraph 三个视图；AI 可以按标签找原文、查作者声明的依赖、取得相关证明和数据上下文。

本版是已运行验证的 Python 原型，采用 **pylatexenc 2.10 + SQLite/FTS5 + JSON**。结构提取不需要语言模型。工具没有执行数学验证或 Lean 构建。

## 1. 安装和运行示例

要求 Python 3.11+，Python 的 SQLite 包含 FTS5。以下命令适用于 macOS/Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

qecgraph ingest examples/paper/main.tex \
  --project-id qec-demo \
  --out build/demo \
  --annotations examples/annotations.example.json

qecgraph validate --store build/demo
qecgraph search "HGP" --store build/demo
qecgraph show thm:hgp-css --store build/demo
qecgraph deps thm:hgp-css --store build/demo
qecgraph deps thm:hgp-css --store build/demo --include-candidates
qecgraph context thm:hgp-length --store build/demo
qecgraph impact def:gf2 --store build/demo --include-candidates
qecgraph context code:qec-demo:reported-rep3 --store build/demo
```

也可以使用 `python -m qecgraph` 代替 `qecgraph`。所有命令输出 JSON；无需启动数据库服务或网页服务。包内 `example_output/` 保存了演示工程的一份实际导入快照，可以直接阅读其 `CURRENT.json` 和对应快照中的 `graph.json`，也可对它运行上述只读查询。

## 2. 导入自己的 LaTeX 工程

```bash
qecgraph ingest /path/to/paper/main.tex \
  --project-id my-paper \
  --project-root /path/to/paper \
  --out /path/to/knowledge/my-paper \
  --config examples/parser-config.example.json
```

使用稳定且不重复的 `project-id`，一个输出目录对应一篇工程。原文件保持原样；输出目录应专门用于生成的索引与快照。默认 `project-root` 是入口文件的父目录，字面 include 先按工程根目录解析，再尝试当前文件目录并给出 fallback 诊断。

`--config` 可省略。主要配置如下：

```json
{
  "environment_map": {
    "lem": "lemma",
    "thm": "theorem",
    "dfn": "definition",
    "claim": "proposition"
  },
  "include_resolution": "root_first"
}
```

需要优先以当前文件为相对目录时，可设 `include_resolution` 为 `file_first`。常见 `\newtheorem`、共享计数器和星号形式可以自动识别。无法判定种类的自定义 theorem 环境保留为 remark，并在诊断中要求配置。

## 3. 自动分配到哪里？

输出的 `CURRENT.json` 指向当前快照。每个 `snapshots/<snapshot-id>/` 包含：

| 路径 | 内容 |
|---|---|
| `sources/` | 实际读取到的 UTF-8 `.tex` 原文件，保留原始换行 |
| `assets/` | 已解析路径的图像、书目等引用资产 |
| `nodes/definition/` | 定义记录及原始 `.tex` 片段 |
| `nodes/lemma/`、`nodes/theorem/` | 引理和定理 |
| `nodes/proof/` | 独立证明片段 |
| `nodes/equation/` | 公式与其标签 |
| `nodes/table/`、`nodes/figure/` | 表格、图片环境及 caption |
| 其他 `nodes/<kind>/` | 章节、段落、注释、数据实体、Lean 声明标注等 |
| `graph.json` | 完整节点、边、标签和诊断 |
| `sourcegraph.json` | 来源结构视图 |
| `lemmagraph.json` | 数学陈述、证明、依赖及形式化对应视图 |
| `datagraph.json` | 表格、资产和显式领域实体视图 |
| `graph.sqlite` | 可重新生成的字段、关系与全文查询索引 |
| `report.json` | 类型统计、诊断、审核队列和前一快照的变化摘要 |
| `manifest.json` | 输入、工具与输出文件哈希 |
| `inputs/` | 本快照使用的解析配置、sidecar、导入 catalog |

文件名由节点 ID 生成安全短名和哈希；精确路径在节点的 `record_path`、`fragment_path` 中。章节节点保存标题及紧随的标签，子节点构成章节内容。定理中的公式也会单独索引，因此父子片段可以重叠，不能按顺序拼接所有片段来重建全文；全文原样保存在 `sources/`。

每个片段记录相对路径、字符起止、起止行、原文件哈希和片段哈希。字符区间使用 Unicode codepoint 的 `[start,end)`；行号从 1 开始。源码行号不等于 PDF 页码。

## 4. 引用和依赖有不同语义

| 边类型 | 意义 |
|---|---|
| `contains` | 文档结构上的包含 |
| `references` | `\ref`、`\eqref`、`\cref` 等明确引用 |
| `cites` | 引用某个 bibliography key；本版不补全书目语义 |
| `depends_on_declared` | 作者用 `\uses` 或 sidecar 明确声明依赖 |
| `depends_on_candidate` | 从 proof 中的引用或不确定 proof 绑定推测的依赖 |
| `proof_of` | `\proves` 或 sidecar 明确指定证明目标 |
| `proof_of_candidate` | 依据同文件、同父级、仅隔空白/注释的相邻关系推测 |
| `formalizes` | `\lean` 标记的对应关系，尚未检查 Lean |
| `describes`、`has_matrix` 等 | 原文与领域数据之间的显式连接 |

默认 `deps`、`impact` 排除候选依赖，也排除已过期、未绑定的审核或未解析关系；需要时使用 `--include-candidates`。`context` 最终输出同样过滤这些关系，保留完整原文块，并补充有界的来源、引用、证明和数据上下文。`show` 会展示全部关系，以便审核。

`\leanok` 只写入 `author_claims_formalized`；实际 `verification_status` 不会升级。所有数学片段都不是该解析工具证明过的定理。没有 label 的内容使用内容与出现次数标识，不承诺跨编辑稳定；重复 label 会产生歧义节点，查询必须选择准确 ID。

## 5. 怎样加入 DataGraph？

直接切出参数表，不足以认定表里的 d 是精确码距离。使用单独的 annotations JSON 明确实体、字段和连接；源文件不需要修改。`examples/annotations.example.json` 是完整示例：

```json
{
  "schema_version": "qecgraph.annotations.v1",
  "nodes": [
    {
      "id": "code:my-hgp",
      "kind": "code_instance",
      "title": "一个 HGP 实例",
      "source_labels": ["tab:codes"],
      "data": {
        "construction": "ordinary_hgp",
        "distance": {"reported_value": 12, "evidence_kind": "source_reported"}
      }
    }
  ],
  "edges": [],
  "annotations": []
}
```

此段是填写示意，`tab:codes` 需要换成真实标签。工具不会把 `source_reported` 转为计算验证或 Lean 验证。关系和字段说明在 `docs/SCHEMA.md`；AI 可同时阅读 schema 与具体图。

### 接入此前的 QEC 知识库模板

将两个解压目录放在同一个父目录，在本目录中运行：

```bash
qecgraph ingest examples/paper/main.tex \
  --project-id qec-demo-catalog \
  --out build/catalog-demo \
  --catalog ../qec_knowledge_starter/records \
  --annotations examples/catalog-links.example.json

qecgraph context code:rep3-hgp:13 --store build/catalog-demo
```

`--catalog` 读取已有 JSON records 的 ID、kind、title、data、refs，并保留整条记录。原关系加 `catalog:` 前缀，以免与从论文提取的关系混淆。已有证据等级保存在原记录中，当前导入操作的状态是 `imported_claim_not_rechecked`，不会声称重新做过计算。跨记录的资产引用仍由原知识库管理；本工具归档的是导入记录本身，不复制整个外部资产库。

## 6. 更新、审核与快照

相同输入、配置、annotations、catalog、工具源码及解析器版本产生相同快照 ID。修改输入后，重新运行 `ingest`；旧快照保留，`CURRENT.json` 切换到新快照。当前实现按工程完整重建；文件级增量解析尚未实现。

人工补充只写入独立 sidecar。若要把一条补充标成 `reviewed`，应绑定审核时的 `expected_content_sha256` 和 `expected_project_source_hash`。前者可从 `show` 获得，后者可从 `context` 获得。源码、相关资源或解析配置变化后，绑定失效则记为 `stale`；未绑定的 reviewed 标记会成为 `unbound_review`。查询上下文排除失效补充，`show` 仍可查看历史标记。

同理，`depends_on_reviewed` 边须提供 `expected_hashes`（用两端实际 node ID 作键）及 `expected_project_source_hash`。所有这类审核都是文献/数据审核，不能代替 Lean 证明。

`validate` 检查文件哈希、片段坐标、标签、边端点和 SQLite 一致性。快照使用输出清单检查误修改；哈希清单本身不是数字签名，也不是防篡改认证。

## 7. 自动化边界

- 解析常见 LaTeX 语法，不执行 TeX、shell、网络下载或任意宏代码。
- 读取字面 `\input` / `\include`；同一文件重复包含只抽取一次并诊断。缺失、循环、越界引用会明确报告。
- 学习部分用户宏的参数形状，**不展开替换体**。藏在宏里的 theorem/ref 需要显式写出或通过 sidecar 补充。
- 不选择条件分支；条件中的内容是语法索引，诊断会提醒。`includeonly`、`graphicspath` 不应用。
- 本地 `.sty/.cls` 不自动解析；原工程应另行保留，需要的环境分类通过配置补充。
- 不恢复 PDF 页码或动态定理编号，不抽取完整 BibTeX 元数据。
- 不自动解析表格数值的 QEC 含义，不补齐隐含假设，不做数学等价判定或 Lean 证明。
- 全文查询是 FTS5 字面短语及子串回退，未实现 embedding 检索。
- 依赖和影响分析只覆盖已记录关系，不保证包含论文全部隐含依赖。
- 当前提供 CLI/Python 与 JSON 输出；MCP/HTTP 服务尚未实现。

解析错误仍会保留部分结果和诊断，并以退出码 2 标明 `partial`；命令错误退出码为 1。请先查看 `report.json`，不要把部分抽取当作完整文献理解。

## 8. 测试和进一步开发

```bash
python -m unittest discover -s tests -v
```

测试覆盖真实结构与来源风险：嵌套标签、注释/verbatim、Unicode/CRLF、include 异常、重复标签、依赖证据等级、sidecar、旧审核失效和上下文过滤。运行记录见 `docs/VALIDATION.md`。

下一步可以在生成的片段上加入 LLM enrichment：让模型提出假设、符号映射、领域实体和依赖候选，再写入 sidecar 草稿。经过审核后接入现有 QEC 验证器；Lean 声明类型和实际证明依赖应由 Lean 环境另行导出。设计依据与主要来源见 `docs/DESIGN.md`。
