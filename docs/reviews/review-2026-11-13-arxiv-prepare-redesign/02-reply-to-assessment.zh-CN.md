# 2026-11-13 离线归一化设计回复

> 对应 [LaTeX 包离线归一化评估与实施方案](01-latex-offline-assessment.zh-CN.md)，评审基线 commit `41f9b9211a0f33a8105ed8d174e9bf3e44f8f712`。本文件是设计评审，不表示新实现已经完成。除特别注明外，文中的样本状态和数字都在本机只读复核；没有修改原始包、项目代码、正式配置或真实数据库，也没有调用真实模型。

## 总体判断

这份评估最值得肯定的地方，是把“工具跑通”和“内容读全”分开了，并且没有把 83%、90% 或编译等价包装成已经达到的能力。它列出的 00README、subfile、BBL、多文档、编码、缺失依赖等案例，基本覆盖了 arXiv 源包的主要格式；§11 的“未完成验证”也写得比多数评估诚实。这些应该保留。

我的总体结论是：**它可以继续作为问题清单和样本说明，但还不适合直接作为实施方案进入开发。** 当前最关键的四个边界没有定：

1. 与现有 source-mapped normalization 的关系；
2. 规范化的权威对象是“文档图”还是“扁平 main.tex”；
3. 什么条件可以声称 `complete`；
4. 外部转换器在不可信 TeX 上的文件边界。

这四个问题不先定，后面的 `document.json`、`paper.md`、`references.bib` 都会重复现有机制，或者把同一次漏读复制到多个产物。下面按优先级给出可执行的修改建议。每条都注明对应的评估章节、本机事实和建议验收。

| 优先级 | 条目 | 关注点 |
| --- | --- | --- |
| P0 | R1–R6 | 复用现有 normalization、文档图、coverage、外部工具沙箱、入口/归档事实、可复现评测 |
| P1 | R7–R14 | 产物权威性、source map、编码、资产、书目、多文档、阅读视图、状态分类 |
| P2 | R15–R18 | 指标、金标、测试、排期 |

## 一、实施前必须确定的边界（P0）

### R1 — 复用现有 normalization，不要新建第二套（P0）

**对应评估**：§5、§7.4、§7.5。

**事实**：现有代码已经有一套 source-mapped normalization，而且核心约束与评估的 §5 原则高度一致：

- [normalize.py](../../../qecgraph/llm/normalize.py) 的 `assemble()` 只从原始字节中复制区间，生成 `NormalizedSource` 和 `segments`；它不重写科学文本，不允许来源不明的标签重命名。
- [artifacts.py](../../../qecgraph/llm/artifacts.py) 把 `main.tex`、`plan.json`、`manifest.json`（含 `segments` 和 `source_map`）写到 `machine/derived/normalizations/<source_tree_hash>/<run_id>/`，并把 `normalization_id`、`normalization_sha256`、`normalization_manifest_sha256` 绑定进 release。
- [DESIGN §3.2](../../design/DESIGN.md) 已经把 `machine/derived/normalizations/` 定义为“original-byte projections and source maps”的位置；[§15](../../design/DESIGN.md) 也把 source-mapped normalization 标为已实现（适用于入口有歧义的包）。
- `validate` 会重新计算 source map；旧 release 的 normalization 仍可离线读取。

**问题**：评估 §5 提出的 `normalized/` 目录（`main.tex`、`manifest.json`、`source-map.json`）与现有 artifact 的 `main.tex`、`manifest.json` 同名不同义，`source-map.json` 还会成为第二份 source map。如果并行实现，会出现两个 `main.tex`、两套 source map、两个 validator，以及“release 绑定哪一个”的歧义。这违反 AGENTS 的“同一字段只有一个可编辑权威来源”，也会让旧 release 和新 release 的证据无法比较。

**建议**：

1. 不新增顶层 `normalized/`；把现有 artifact schema 升到 `qecgraph.normalization/2`，增加 `documents`、`coverage`、`references`、`diagnostics`。现有 `qecgraph.normalization` manifest 作为 v1 只读兼容，不迁移历史 release。
2. 把 plan 生成从 AI 解耦。现在 `workspace.py` 只在“多个候选入口且没有编码映射且有 AI client 或旧 normalization”时调用 `_resolve_normalization`；默认离线流程根本不会走到这里。新增确定性的 `deterministic_plan(tree, metadata, limits)`，AI 只处理规则确实无法消歧的情况；两种 plan 都走同一个 `assemble()` 和同一套校验。
3. 明确 terminology：`normalization` 指“字节忠实的 entry + source map”，`prepare` 或 `offline prepare` 指整个离线流程。不要让两个词都指同一产物。
4. 在实施顺序上，把“接入现有归档、stage、validate、发布”提前，而不是留到阶段五。否则格式会在脱离真实 release 约束的情况下设计。

**版本**：解析语义变化（subfile/import、未知环境透明递归、编码别名）提升 `PARSER_VERSION`；规范化格式或 schema 变化单独提升 `NORMALIZER_VERSION`；回放来源，不刷新旧审核哈希，不因无关代码重建快照。

**验收**：同一输入、同一 plan、同一工具版本生成的 `main.tex` 和 source map 字节相同；现有 v1 artifact 仍可读；新 release 的 manifest 覆盖新增字段；不出现第二套 `normalized/` 目录约定。

### R2 — 权威对象是文档图，不是扁平 main.tex（P0）

**对应评估**：§5、§4.3。

**问题**：评估的目录同时有 `normalized/main.tex` 和 `documents/<document-id>/main.tex`，但没有说明哪个是权威、哪个是派生；多个文档都用 `main.tex` 命名，也很容易把补充材料误当成主文。现有 assembler 的 `main.tex` 是“按 plan 选择原始区间并顺序拼接”的视图，不是“展开 include 后重写”的新源文件；评估把它写成“主文的规范化来源表示”，语义不清。

**建议**：

1. 权威模型改为 `documents[]`：每项至少包含 `document_id`、`role`（`main`/`supplement`/`appendix`/`unknown`）+ `role_evidence`、`root_path`、`preamble_ref`、`body_ranges`、`dependency_refs`、`bibliography_scopes`。`main` 是角色，不是文件名。
2. 每个 document 都保留原始文件的 bytes、hash 和逐文件 source map。扁平 `main.tex` 只作为 `views/` 下的派生视图，标 `synthetic: true`，不承诺可重新编译。
3. 如果下游工具必须吃单个 TeX，生成 `views/<document-id>.tex` 或 `views/reading.tex`，不要复用 `main.tex` 作为唯一副本。
4. 多文档不要合并前言区；不要重命名 label；跨文档引用保留带 document scope 的 key，编号留给渲染层。

**对抽取的契约**：`document.json` 至少应给出 `document_id`、`role`、`sections[]`（level/title/source）、`blocks[]`（kind/environment/heading/labels/citations/source ranges/原始 `latex` + 派生 `reading_text`）、`bibliography_scopes`、`diagnostics`。定理/证明只记录边界和 label，不推断证明有效；公式只记录原文、编号和标签，不把公式转写当作等价。这样抽取只消费结构化结果和原始 span，不需要再从 Markdown 猜结构。

**验收**：`2408.13687v1`、`2412.14256v1` 能给出两个独立 scope；`2308.07915v2` 能区分“被 main include 的 fragment”和独立文档；`main`/`supplement` 的 role 有证据字段；不重复计正文，不合并 preamble；theorem/proof/equation 的边界可由 block 模型表达。

### R3 — 用“覆盖账本”定义 complete，而不是转换器退出码（P0）

**对应评估**：§4.1、§8.1、§8.2。

**事实**：评估已经发现 QEC 教程 `2605.29137v1` 的 14 个 subfile 章节没有读入；本机复核为 362 个 block、其中 319 个是 `bib_entry`，正文只有 14 个 section 节点，`includes` 只有 `supporting-files/macros`。这是一个典型的“状态成功、正文缺失”。而当前 `processing_completed` 只是 `ingest` 成功发布的交易标志（[workspace.py](../../../qecgraph/workspace.py) 中 `result.update(status='processing_completed', ...)`），与内容覆盖无关。

本机还确认了另一个更隐蔽的例子：`2607.00222v1`（评估里的 bibunit 样本）状态是 `processing_completed`，但解析结果是 129 个 block 中 `section` 为 0、只有 2 个 `paragraph`，第一个 paragraph 从第 108 行覆盖到第 1111 行。原因是 `bibunit` 不在 environment map，解析器把整个环境当成一个段落，内部的 `\section` 没有 emit。这不是“少了一章”，而是状态显示完成、章节结构为空。

**建议**：新增 `coverage`，至少包含以下字段：

```json
{
  "documents": [
    {"document_id": "...", "role": "main", "status": "identified"}
  ],
  "directives": [
    {
      "kind": "subfile",
      "literal": "chapters/...",
      "source": {"path": "main.tex", "char_start": 0, "char_end": 0},
      "active": true,
      "outcome": "resolved",
      "target": "chapters/...tex",
      "evidence": "source directive"
    }
  ],
  "counts": {"active": 15, "resolved": 15, "missing": 0, "dynamic": 0, "inactive": 2},
  "bibliography": {"scopes": 2, "keys": 120, "resolved": 118, "ambiguous": 2, "unresolved": 0},
  "assets": {"referenced": 30, "bundled": 28, "missing": 2, "generated": 0},
  "structure": {"sections": 14, "expected_sections": 14, "verdict": "match"}
}
```

规则建议：

1. 每个 active 的 `input`/`include`/`subfile`/`import`/`subimport` 必须有一条 outcome。
2. `complete` = 所有 active body 依赖 resolved + 所有 document 已识别 + 结构化覆盖通过。引用和资产可以是 `partial`，但必须列出。
3. `validate` 增加 coverage gate：active 依赖未解析时，不得把 `coverage_status` 标为 complete；发布可以是 partial，但不能静默。
4. 未知环境单独记 `opaque_container`；未知环境不能直接算“读完了”。
5. 增加“源区间覆盖”不变量：选中的正文范围必须被 block 覆盖，未被任何 block 覆盖的非空白字符记 `unassigned`。现有 [structure.py](../../../qecgraph/source/structure.py) 的 `validate_plan` 已经要求 body 恰好覆盖一次，可以把同样的思路用于 document model。

**一个低成本的独立核对**：把 Pandoc 从“另一个转换器”改成“独立覆盖核对器”。在沙箱里对同一 entry 统计 `Header`、`DisplayMath`、`Cite`、`Table`/`Figure` 数量；如果权威 parser 的 `section` 是 14 而 Pandoc 的 `Header` 是 162（`2605.29137v1`），或 `section` 是 0 而 Pandoc 有 6 个 header（`2607.00222v1`），就标 `coverage_suspect` 并列出差异。这不是金标，Pandoc 的计数也可能因样式不同而偏高或偏低，但它成本低，能抓住“静默漏读”。本机对完成包做了同样比较，大多数 section 数与 Pandoc 的 Header 数一致，说明这个信号在明显漏读时有区分度。

**验收**：QEC 教程的 ledger 出现 14 条 subfile 且全部 resolved；如果回归到漏读，coverage 立即 fail。`2607.00222v1` 不得在 `section=0` 的情况下标 complete。

### R4 — 外部转换器必须隔离（P0）

**对应评估**：§6.4、§7.5。

**本机事实**：在 `/tmp` 的临时树中做了一个只读安全探测（pandoc 3.13、latexpand 1.7.2）：源文件写 `\input{/tmp/qec-secret}`，其中 `/tmp/qec-secret.tex` 的内容是 `TOP_SECRET_MARKER`。`latexpand --keep-comments --fatal` 的 stdout 直接包含该 marker，退出码 0；`pandoc -f latex -t plain` 的输出也包含该 marker，退出码 0。这里没有修改项目文件，但它说明外部工具会按 TeX 语义跟随绝对路径读取主机文件。

**风险**：如果归一化产物稍后被送去语义抽取或上传，主机上的其他 `.tex`（包括同一 workspace 中其他论文的来源树）会进入派生文本。现有 [parser.py](../../../qecgraph/source/parser.py) 的 `path_outside_project` 保护只覆盖内置解析器，不覆盖 Pandoc 和 latexpand；评估 §6.4 只提到“将来为了编译核对而执行 TeX”要沙箱，但没有把外部转换器本身纳入边界。

**建议**：

1. 外部工具一律在只含该包树的临时根目录中运行：固定 `cwd`、清除环境变量、禁网、设 CPU/内存/输出字节/时间上限；优先容器或 OS sandbox。没有沙箱时，默认不把外部工具作为权威来源。
2. 预处理拒绝或标记绝对路径、`..`、`~`、反斜杠路径、动态路径宏；后处理扫描输出中的主机 canary 和包外路径。
3. 外部工具的输出只进 `views/` 或 `diagnostics`，不得直接成为 `document.json`/`references.json` 的权威内容。
4. 测试用例：包内放 `\input{/etc/...}`、`\input{../../other/main}`、`\includegraphics{/tmp/secret}`、symlink 逃逸；断言输出不含 canary，且产生明确诊断。

**验收**：安全测试通过之前，不把 Pandoc/latexpand 接入默认离线流程。把它们作为“独立核对后端”，而不是“权威归一化器”。

### R5 — 先修正入口、归档和未知环境的事实（P0）

**对应评估**：§4.4、§6.1、§9。

这一节有六个本机可复核的问题，会直接影响成功率和 `complete` 判定。

**1. 旧 tar 不是 damaged。** `hep-th/9407087v1` 和 `quant-ph/9604034v1` 被当前 reader 以 `Tar missing a valid zero-block trailer` 拒绝；Python `tarfile` 能正常读出 3/2 个成员。前者最后一个成员后还有 7680 字节填充，后者有 6144 字节填充且末 2048 字节非零；这是 1996 年 tar 的块填充，不是坏档。建议接受“最后一个成员之后到 EOF 的填充”，记录 `trailing_bytes` 和首个零块位置，限制总长度；只有成员头/长度矛盾或截断才标 damaged。至少不要永久把 `quant-ph/9604034v1`（A Theory of Quantum Error-Correcting Codes）标成 damaged。

**2. 入口识别过窄。** [package.py](../../../qecgraph/source/package.py) 的 `SourceTree.entrypoints()` 只认 `.tex` + `\documentclass` + `\begin{document}`；`\documentstyle`、扩展名缺失的 Plain TeX、旧式 `00README.XXX` 都不认。先加 `\documentstyle` 和 `00README`（JSON + 旧式 `.XXX`）两种证据，并区分“没有元数据”和“元数据冲突”。`usage: ignore` 只表示不参与编译，不等于可删除；多个 `usage: toplevel` 有顺序，不要用“最长文件”或“叫 main.tex”消歧。

**3. subfile/import 的语义要写清。** `\subfile` 不是普通 `\input`：要剥离 `\documentclass[...]{subfiles}` 和 `\begin{document}`/`\end{document}`，只取 body；`\import`/`\subimport` 是两参数，按第一个参数目录解析；`\includeonly` 是“存在但未选中”，不是删除。当前解析器只在 `if name in {"input", "include"}` 时建立 include 关系（[parser.py](../../../qecgraph/source/parser.py) 的 `discover`/`metadata` 等发现逻辑），QEC 教程的 14 个 subfile 因此完全没进依赖图。

**4. 未知环境不能整块变成段落。** 见 R3 的 `2607.00222v1`。建议把未知环境当作透明容器递归，记录 wrapper；已知 literal/verbatim 环境保持不透明。把该包加入回归，期望至少 8 个 section。

**5. 状态分类需要拆开。** 本机的失败原因并不相同：

| 来源包 | 当前状态 | 实际主要错误 | 建议归类 |
| --- | --- | --- | --- |
| `0903.0566v1` | `parse_failed` | `latex_parse_error`（proposition 闭合） | 解析器 bug，Pandoc 可读；先修 |
| `2201.08309v1` | `parse_failed` | 4 处 `latex_parse_error`（`$`、brace、`exam`） | 解析器 bug/容错问题；先修 |
| `2511.01062v1` | `parse_failed` | `latex_parse_error`（`now` 闭合） | 解析器 bug；不是“commented appendix”导致 |
| `2607.29382v2` | `parse_failed` | `structural_scan_incomplete` + `latex_parse_error` | 可能确实不支持；标 partial |
| `quant-ph/0001106v1` | `parse_failed` | `missing_include: BoxedEPS` | 缺支持文件，正文可能可读；标 partial_missing_dependency |
| `2607.00262v1` | `unsupported_encoding` | `utf8x` 不在白名单 | 加 UTF-8 别名可先消除这个编码错误 |
| `hep-th/9407087v1`、`quant-ph/9604034v1` | `damaged_archive` | 旧 tar 填充 | 见第 1 条 |

其中 `0903.0566v1`、`2201.08309v1`、`2511.01062v1` 的 Pandoc 路径都能生成 Markdown，说明它们不是“格式不支持”，而是当前 parser 的健壮性问题。建议在归一化之前先做一个 parser robustness 工作流：对 `latex_parse_error` 尝试 `tolerant_parsing=True` 的降级解析，保留错误前后可用的 block，标 `parse_partial`，不要把整个文件丢弃。`quant-ph/0001106v1` 的 `missing_include` 也应区分“正文 include 缺失”和“宏包/支持文件缺失”的严重性；后者不应单独导致整篇 `parse_failed`。

**6. PDF-only 要有明确产品决定。** 样本里 `1208.0928v1` 是 PDF；评估把它排除出分母是对的，但生产 arXiv 存在 PDF-only 投稿。v1 可以明确 `unsupported_format=pdf_only` 并保留；若要做，另立 `pdf_text` 路径，坐标是 page/bbox，不能伪装成 TeX source span，也不与 LaTeX 归一化混在一个成功指标里。

**验收**：给出状态迁移表（旧状态 → 新状态 → 原因），每个迁移有测试；`processing_completed` 不能与“正文完整”混用。

### R6 — 评测要可复现，并留出独立样本（P0）

**对应评估**：§2.3、§3.2、§10。

**问题**：

- 探测脚本在 `/tmp`，会消失；`test-sources/` 在 `.gitignore` 里，干净 clone 无法复现 83%/74.5%。
- 47 个包是刻意覆盖格式的开发集，且包含两篇论文的 v1/v2（`2308.07915`、`2511.01062`）；用同一批包调适配器再报告 90% 会过拟合。
- 26/47 与 39/47 的分母并不完全相同：Pandoc 侧的探测基于已解压的 `sources/`，两个旧 tar 也在分母内；而 qec-graph 侧在严格 reader 处就失败了。表里并排比较会被误读为“改造前后”。
- 当前 qec-graph 的入口选择没有使用 00README 元数据，而 Pandoc 侧有 15 个包用了元数据。这等于在入口选择上给了 Pandoc 额外信息。

**建议**：

1. 固化 `tools/eval_prepare.py`（或 `tools/eval_normalization.py`），输入 manifest，输出固定 JSON；记录 pandoc/latexpand 版本、完整命令、耗时、退出码、每包每入口结果；提供 `--check` 与冻结结果比较。没有这个脚本，后续所有“提升”都不可比较。
2. 样本获取三选一并写清：按 arXiv ID + SHA-256 的下载脚本（可选联网 job）；小规模 vendored 子集（先做许可证审查）；外部目录 + 强制 manifest。不要把论文随意提交进仓库。样本说明和 manifest 可以放在 `validation/` 或 `docs/`，不要依赖被忽略的目录。
3. 现在冻结一个 held-out 集（例如 30 篇近两年的 QEC 源包，按年代/格式分层），在适配器定稿前不查看；开发集只用于调规则。验收报告分别给 dev/held-out。
4. 做消融：当前 parser（无元数据）、当前 parser + 元数据入口、Pandoc（同入口集）、latexpand + Pandoc。这样才能判断 55.3% 与 83% 的差距来自入口选择、依赖展开还是 parser。
5. 报告 confusion matrix（converted/complete/partial/needs_entrypoint/unsupported/damaged），而不是单一成功率；明确“Pandoc 生成了 Markdown”不等于“内容完整”。
6. 统计上，47 个包的 83% 置信区间很宽；90% 可以作为工程目标，但不要用这 47 个包证明“达到 90%”。验收至少给分母、样本来源、区间和失败类型。

## 二、格式与来源（P1）

### R7 — 每个产物都要有权威性和生命周期（P1）

**对应评估**：§5。

评估列出的产物很多，但没有说明谁是权威、谁可重建、谁进 release、谁可以手改。建议补一张与 DESIGN §3.1 同构的表：

| 产物 | 权威 | 可重建 | 消费者 | 是否进 release | 备注 |
| --- | --- | --- | --- | --- | --- |
| `main.tex` / `document.json` / `source-map.json` / `coverage` / `diagnostics` | 原始包 + 解析器 | 是 | 查询、抽取、审计 | 是（绑定 hash） | 派生，不得手改 |
| `references.json` | 包内 BIB/BBL/bibitem | 是 | 引用解析、检索 | 是 | 保留原始片段和缺失 |
| `references.bib` | 上述派生的导出视图 | 是 | 外部工具 | 否，或不作为权威 | 不是可编辑事实源 |
| `paper.md` | `document.json` 的视图 | 是 | 人读、阅读视图 | 可选 | 检索/抽取不应以它为输入 |
| `assets/` | 包内字节 | 否（原字节） | 阅读、核对 | 是 | 只放包内资产 |
| `support/` | 依赖清单 | 是 | 构建/诊断 | 可选 | 系统 TeX 只记引用，不复制 |

这张表能直接避免两个常见问题：`references.bib` 和 `references.json` 长期双维护；`paper.md` 变成事实源。`paper.md` 可以给人看，但检索应该消费结构化 block 和 span，否则又会从 Markdown 猜回原结构。

### R8 — source map 的粒度与身份（P1）

**对应评估**：§5 原则 4–6。

现有 `source_map` 是“有序 segment，每个 segment 映射到一个原始区间”；这对单文件整段复制够用，但对以下情况不够：

1. **多文件节点**：一个段落被 `\input` 切开，或一个 theorem 跨文件拼接。建议 `ranges: [{path, byte_start, byte_end, char_start, char_end, file_sha256}]`，不要用一个 range 表示拼接结果。
2. **生成文本**：`origin: null` + `kind: generated`；不要给拼接文本编造原始 span。
3. **编码投影**：记录 `declared`、`detected`、`used`、`confidence`；多字节编码的 char 偏移不能直接当原始 byte 偏移；单字节 codec 的 1:1 假设要写清楚。
4. **身份**：`document_id` 用内容/路径/tree hash 的稳定哈希，`run_id` 单独；block key 只在一个快照内稳定，引用证据用 span + hash，不要跨版本复用 block 编号。
5. **确定性**：排序、无时间戳/绝对路径/hostname；同一输入 + 配置 + 工具版本 → 字节相同；加测试。

### R9 — 编码要显式，不猜（P1）

**对应评估**：§4.4。

- `utf8x` 可以按 UTF-8 解码（`utf8x` 是 `ucs` 的接口，实际字节多数是 UTF-8）；这能解 `2607.00262v1` 的 `Unsupported declared TeX encoding`。建议在 `source/encoding.py` 的 codec 表加别名，并在 manifest 记录“这是 UTF-8 近似，不建模 ucs 的全部语义”。
- `2209.05640v1` 没有明确声明；保持 `needs_encoding`/`unsupported_encoding`，不要用 Latin-1 回退并宣称正确。评估 §4.4 已经说了这一点，建议把它写成状态规则，而不是只写成注意事项。
- 编码冲突（声明 vs 探测 vs 显式 override）要报错，不能静默选一个。
- CRLF/非 UTF-8：保留原始 bytes；投影映射要能回原字节；parser、AI、locator、MCP 共用同一映射。

### R10 — assets/support 与许可证（P1）

**对应评估**：§5、§4.4。

- `includegraphics` 的扩展名补全、`graphicspath`、同名多格式、大小写冲突：记录候选和选择规则；不要静默选第一个。
- TikZ/`filecontents` 生成图：记 `generated_by_tex` / `embedded_source`，不声称资产完整。
- 系统 TeX 的 `.sty/.cls/.bst` 不复制进 `support/`，只记解析到的路径/hash/来源；复制需要 license/attribution 审查。这样也控制体积和再分发风险。
- `filecontents` 中内嵌的 BIB/EPS 要保留原始字节和区间；同名文件与包内文件冲突时，不能无条件覆盖（`2606.30447v1` 就是这种案例）。

### R11 — 书目的 scope 与导出质量（P1）

**对应评估**：§4.2、§6.3。

评估对 BBL 的边界写得很好；建议再补四条可执行规则：

1. **先 scope，再 key**：document + refsection/bibunit/multibib 名称构成 scope；同 scope 重复 key 保持 ambiguous；跨 scope 用限定 key；不静默覆盖。
2. **来源优先级**：包内 `.bib`（可多个）→ `filecontents` 内嵌 → BBL（传统/Biber）→ 内联 bibitem/mcite。保留所有来源主张；冲突不合并，不因新来源覆盖旧主张。
3. **导出校验**：`references.bib` 导出后必须能被 BibTeX/BibLaTeX reader 重新解析，key 在 scope 内唯一（或导出前缀），brace 平衡；否则标 `export_quality=invalid/partial`，不得作为权威。缺失字段保持 `null`，不补标题。
4. **具体案例**：`2607.00222v1` 的 bibunit、`2606.00045v1` 的 multibib、`2606.30447v1` 的 filecontents + 同名 BIB 各自要有回归；`1208.2317v1` 的 BBL-only 只保留原文和字面字段。

不做联网 DOI/Crossref 补全；离线只允许包内证据。若将来要联网补全，应作为显式 opt-in，并记录外部来源，不与包内证据混在一起。

### R12 — 多文档与交叉引用（P1）

**对应评估**：§4.3。

- 角色证据：00README、documentclass、实际 include、文件内容；没有证据 = `unknown`，不猜主次。
- 独立 supplement（`2408.13687v1`）与“被 main include 的 fragment”（`2308.07915v2`）分开；同一文件不能既算 fragment 又算独立文档。
- 跨文档 `\externaldocument`/`xr`：记录目标 document + label；只在包内解析；不重写 label；编号留给视图。
- 独立 preamble 保留；不删除第二份 preamble 后拼接。
- 入口消歧可以使用 include 图：如果 root B 被 root A include，B 更可能是 fragment；这比“最长文件”或“叫 main.tex”有依据。把它写成规则并记录证据。

### R13 — 阅读视图（P1）

**对应评估**：§5、§7.4。

- `paper.md` 从 `document.json` 生成，不从 Pandoc 直接生成；保留章节顺序、数学、定理/证明边界、cite key、source anchor。
- 定义 markdown 方言和版本；不丢 cite key；截断必须显式标记。
- Pandoc 的 LaTeX reader 没有 `sourcepos`（本机 3.13 的 `--list-extensions=latex` 没有该项），所以不能声称逐字符回溯。若要用 Pandoc 视图，只能做到 section/page 级匹配，并明确限制。
- 检索与抽取消费结构化 block + span，不消费 `paper.md`。

### R14 — 状态与诊断（P1）

**对应评估**：§3.1、§8.1。

- 用维度状态（archive/entry/encoding/structure/dependencies/bibliography/assets/coverage）+ 派生的 overall，不用单一 `complete`。
- `processing_completed` 保留为交易状态；不要把它当质量状态。
- 失败分类要能区分：读者策略拒绝（旧 tar）、真正损坏、缺少材料、语法不支持、解析 bug、编码未知。现在 `damaged_archive` 把前两者混在一起；`parse_failed` 把多种不同原因混在一起。
- 诊断 code 稳定、带 stage/severity/source/blocking；metrics 按 code 汇总；未知异常不吞。

## 三、指标、验收与排期（P1/P2）

### R15 — 指标（P1）

**对应评估**：§8.1、§8.2。

评估的分层指标方向正确，建议补三条：

1. **每包/每文档双分母**：包级“至少一个文档可读”与文档级“每个应处理文档完整”不是同一件事；当前 47 个包里有多入口包，包级成功率会掩盖部分文档失败。
2. **机械判定**：每个指标要能由程序判定，不能只靠人工描述。例如“正文完整率”至少要有 coverage 和 section 计数做代理；“引用覆盖率”要有 resolved/ambiguous/unresolved 计数。
3. **complete 的阈值逐维度定义**：允许 partial，但不能静默；`complete` 不得由退出码或“生成了 Markdown”推出。

### R16 — 金标（P1）

**对应评估**：§7.1、§8.3。

- 给 `gold.json` schema：documents/roles/roots、section counts（按级别）、equation/theorem counts（允许合理容差）、cite key set、bib scopes、asset set、expected coverage outcomes、expected diagnostics。
- 人工核对 12–15 个困难样本即可；其余用机械不变量（字节保真、include resolved、cite resolved、determinism、no host path）。
- 金标不能从当前输出反推；先读原文再写期望。对“原文没有该字段”用 `unknown`，不要填 0。
- 至少覆盖：QEC 教程、`2607.00222`、`2511.01062v2`、`2408.13687`、`1208.2317`、`quant-ph/9604034`、`2209.05640`。

### R17 — 测试（P1）

必测用例建议：

- 入口：00README JSON/`.XXX`、多个 toplevel、`\documentstyle`、扩展名缺失的 Plain TeX、include 图消歧、真正的多主文档。
- 依赖：`input`/`include`/`subfile`（剥离 preamble）/`import`/`subimport`/`includeonly`、注释中的 include、`00README ignore`、动态路径宏、嵌套相对路径、循环。
- 结构：未知环境透明递归（`bibunit`）、literal/verbatim 不透明、定理/证明边界、跨文件段落、`\includeonly` 下的章节。
- 编码：`utf8x`、声明 vs 实际、CRLF、无效字节、映射回原字节。
- 书目：原生 BIB（重复 key、宏、@string）、传统 BBL、biblatex BBL、内联 bibitem、multibib/bibunits、refsection、filecontents/jobname、缺字段。
- 归档：旧 tar 填充、单零块、ZIP64、路径穿越、symlink、大小写冲突。
- 安全：绝对路径 include、`..`、`\includegraphics` 包外路径、canary 不进入输出。
- 确定性：同输入同输出；无时间戳/绝对路径；旧 artifact 可读；release replay。
- 外部工具：没有安装时标 skipped，不标 passed；fake provider 离线。

现有套件在本机是 376 项；本评审复跑 376 项，2 项因本机 pty 资源不足报 `out of pty devices`，未重现完整通过。这个环境差异不影响设计结论，但说明复现记录需要写明解释器、终端和跳过项。

### R18 — 排期（P2）

把评估的五阶段重排为纵向切片，确保每个阶段都产出可验证 artifact：

1. **设计 v2 + schema + 可复现 harness + 现有 normalization 合并决策**。先写清楚 R1–R3，再动代码。
2. **P0 正确性切片**：`2605.29137`（subfile）、`2607.00222`（未知环境 + bibunit）、`2511.01062v2`（元数据）、`2408.13687`（多文档）、`1208.2317`（BBL-only）、`quant-ph/9604034`（旧 tar）。每个包覆盖 entry → coverage → normalized artifact → validate。
3. **通用化**：00README/legacy、import/subimport、includeonly、编码、assets/support、parser 容错。
4. **书目 scope + 导出校验**。
5. **paper.md + 独立后端核对**。
6. **workspace/AI 集成与迁移**。

不要把“接入工作区”留到最后；格式必须在真实 release、validate、原子发布和旧 release 读取的约束下设计。也不要在 parser 仍有 3–4 个可修 bug 的情况下先做大批量格式转换，否则新产物会把同样的漏读固化下来。

## 四、本机复核与事实修正

### 4.1 复核一致

- 样本 48 个包、47 个 TeX、1,664 个解压文件；`manifest.json` SHA-256 为 `153f4e78...`；与评估一致。
- 状态 26/12/5/2/2 与 `current-sync.json` 一致；Pandoc 39/47、latexpand 35/47 与探测结果一致。
- QEC 教程 362 个 block、319 个 `bib_entry`、14 个 subfile，正文未读入；与评估 §4.1 一致。
- 15 个包带 `00README.json`；与评估的入口选择分类一致。
- 评估的 376 项测试总数与当前套件一致；本机复跑有 2 项 pty 环境错误，原因见 R17。

### 4.2 需要修正的表述

1. **“2 damaged archive”**：更准确是“当前 reader 策略拒绝的旧 tar”；字节可由 Python tarfile 读取。建议改状态名和样本说明，不要在方案里把“兼容旧 tar”写成不可审计的宽松读取。
2. **“26 个完成现有结构处理”**：其中 `2607.00222v1` 的 section 为 0；`26` 只能说明发布成功，不能说明结构导入成功。至少在表里加一列“结构覆盖”。
3. **“47 个包”**：包含 `2308.07915` v1/v2 和 `2511.01062` v1/v2，不是 47 篇独立论文。报告要分 unique paper 和 package。
4. **“Pandoc 83%”**：Pandoc 侧的探测包含两个 qec-graph 拒绝的旧 tar（基于已解压树）；输入可用性和分母不同。要么统一 reader，要么在表里明确“不同输入集”。
5. **“main.tex”**：现有 assembler 已用这个名字表示“按 plan 拼接的视图”；评估的 `normalized/main.tex` 不要与它同名不同义。
6. **“90%”**：当前 dev set 不能证明；需要 held-out、样本量和区间。

### 4.3 本评审实际执行

```sh
# 只读复核
shasum -a 256 test-sources/arxiv-sources/manifest.json
.venv/bin/python -m unittest discover -s tests

# QEC 教程：362 blocks / 319 bib_entry / includes 只有 macros
# 2607.00222：129 blocks / 0 section / 2 paragraph（直接调用 parse_project 复核）
```

安全探测在 `/tmp` 临时目录完成：

```sh
printf 'TOP_SECRET_MARKER\n' > /tmp/qec-secret.tex
printf '\\documentclass{article}\n\\begin{document}\nA \\input{/tmp/qec-secret} B\n\\end{document}\n' > main.tex
latexpand --keep-comments --fatal main.tex   # stdout 含 marker，退出码 0
pandoc -f latex -t plain main.tex             # stdout 含 marker，退出码 0
```

上述探测没有修改项目文件，也没有访问 `human/`、私人笔记或凭据。

## 五、建议写入设计 v2 的最小决定

如果只先做一次设计收敛，建议把以下八条写成正式决定，再进入实现：

1. **权威对象**：document graph + 每文件原始 bytes；`main.tex` 只是视图。
2. **存储**：复用 `machine/derived/normalizations/<tree>/<run>/` 的 schema v2；不新增 `normalized/`。
3. **complete**：由 coverage gate（active 依赖、文档识别、结构覆盖）派生；不由转换器退出码或 `processing_completed` 派生。
4. **外部工具**：不可信、沙箱化、可选；不能作为权威归一化器。
5. **评测**：manifest + 工具版本 + held-out；不接受只在 `/tmp` 存在的数字。
6. **状态**：维度状态 + 稳定诊断 code；区分 damaged/unsupported/missing/partial/parser bug。
7. **多文档**：scoped；不合并 preamble；不重写 label；角色有证据。
8. **编码/资产/书目**：显式映射和 provenance；不静默猜。

## 六、结论

这份评估值得保留，尤其值得保留的是样本清单、失败案例、机械导入与可选 AI 的分离，以及分层成功指标。它现在的主要问题不是“方向错了”，而是**把若干尚未决定的设计选择写成了实施步骤**：与现有 normalization 重复、权威对象不清、没有 coverage 账本、外部转换器没有隔离、入口/归档/状态的事实还没有修正、评测不可复现。

我的优先级是：先 R1（合并现有 normalization）、R2（文档图）、R3（coverage），再 R4（沙箱）、R5（事实修正）、R6（可复现评测）。如果只能做三件事，就是这三件：不要把归一化做成第二套权威；不要把扁平 `main.tex` 当论文；不要让 `complete` 脱离覆盖证据。

在完成这份设计收敛之前，我不建议把本文称为“实施方案”或据此开始大规模转换。把它作为评估记录保留，另写一份 design v2，回答上面八个决定；然后用 QEC 教程等 6 个困难样本做纵向切片。这样既保留了当前评估的价值，也避免把它的数字和格式固化成下一轮的技术债。最终达成一致的协议写入 [DESIGN](../../design/DESIGN.md) 的 §3.2、§7 和 §15；评估与本回复只作为有日期的工程记录，不成为第二份设计权威。

## 七、追加修正：可编译性不是目标

实施纵向切片后，R5/R18 对 `2111.05176v1` 和 `2308.07915v2` 的“难点”表述需要收紧：它们难在“保持可编译或保留独立文档边界”，不难在“拿到正文”。

- `2111.05176v1`：`\ProjectRoot` 在包内定义为 `.`，是零参数字面宏。组装器从 `\newcommand*` 学到该值，11 个 `\input` 全部 resolved；结果 16/16、2,028 blocks、202 sections，content/structure 都完整。这里不需要猜测路径，也不需要人工映射。
- `2308.07915v2`：supplement 的 body 可以直接拼入；`packages.tex` 是 supplement preamble 的宏包依赖，缺失只影响宏和编译，不影响正文内容。结果 345 blocks、15 sections，content/structure 完整；只记 1 条 dependency warning，preamble 丢弃单独记录，不再当作内容缺失。
- 因此完成度拆成 `content_complete`、`structure_complete`、`document_complete`；`compile_ready` 不检查、不保证。编译只有在需要重新排版或运行 TeX 时才有意义，对“保留 LaTeX 结构并供抽取”没有直接价值。
- 仍会影响提取的是：宏生成的正文、条件分支、有参数或未定义的路径宏、Plain TeX 结构，以及 parser 的致命错误。这些是内容/结构问题，不是“能否编译”的问题。

本修正对应的工具和结果见 `tools/prepare_arxiv.py`、`qecgraph/source/assembly.py` 与 `build/prepare/REPORT.md`；`build/` 是可重建的实验输出，不作为长期权威。
