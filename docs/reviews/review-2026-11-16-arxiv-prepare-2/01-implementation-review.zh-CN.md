# 准备阶段（arXiv 包至统一输出文件）实现审查与对比修正报告

> 状态：代码审查与对比修正记录，改进建议尚未实施。日期：2026-11-16。审查范围：从 arXiv 源码包到统一输出文件（`entry.tex`、`source-map.json`、`normalization.json`、书目与引用就绪性）的准备阶段实现。

本文在首轮代码审查的基础上，与仓库内已有的四份评测/探测报告及历史审查记录进行了交叉对比，修正了部分判断并补充了遗漏的关键缺陷与架构建议。对比参照的已有材料包括：

- [2026-11-13 第一轮离线 prepare 评估与复核记录](../review-2026-11-13-arxiv-prepare-redesign/11-pre-push-review.zh-CN.md)
- `build/preparation-final/acceptance.json`（Codex 产出的 47/47 准备验收报告及 `local.log` / `accepted.log`）
- `build/review-2026-11-16/`（独立复测探针：`results.json`、`out/bib-entry`、`out/hep-ai`、`out/2111-explicit`、`nonutf8.tar.gz`）
- `build/reference-audit/corpus.json` 与 `preliminary.json`（47 包参考文献与引用解析审计，仅 11/47 通过）
- `build/tex-compiler-probe/result.json`（本地 TeX 编译器辅助探测结果）

## 目录

- [1. 与已有报告的对比及对首轮判断的修正](#1-与已有报告的对比及对首轮判断的修正)
- [2. 问题总览（修正与增补版）](#2-问题总览修正与增补版)
- [3. 架构与阶段边界问题](#3-架构与阶段边界问题)
- [4. 确定性准备阶段的缺陷](#4-确定性准备阶段的缺陷)
- [5. 参考文献与引用准备链路的断层（对比新增）](#5-参考文献与引用准备链路的断层对比新增)
- [6. 转换、编码与校验中的正确性 Bug](#6-转换编码与校验中的正确性-bug)
- [7. 统一输出文件与来源映射的一致性问题](#7-统一输出文件与来源映射的一致性问题)
- [8. 关于引入本地 TeX 编译器的评估与建议（对比新增）](#8-关于引入本地-tex-编译器的评估与建议对比新增)
- [9. 改进优先级建议](#9-改进优先级建议)

---

## 1. 与已有报告的对比及对首轮判断的修正

将首轮代码审查与 `build/preparation-final/`、`build/review-2026-11-16/`、`build/reference-audit/` 对比后，需对以下判断作出修正与补充：

1. **修正对“`acceptance.json` 中 40 篇程序处理 + 7 篇模型处理”的判断**
   - `build/preparation-final/acceptance.json` 报告 47 篇全部通过（`program: 40, model: 7`）。
   - 但对比 `build/preparation-final/local.log` 与 `build/review-2026-11-16/results.json` 可见：**默认离线模式（不带 `--ai-prepare`）实际只有 38 篇退出码为 `0`**（另有 5 篇 `exit 2`、4 篇 TeX 包 `exit 1`、1 篇 PDF 对照 `exit 1`）。
   - 差异原因在于：`hep-th/9407087v1` 和 `quant-ph/9604034v1` 虽然没有调用大模型，但它们依赖的 `load_for_preparation(repair_legacy_tar=True)` 被写在了 `if args.ai_prepare:` 分支内。更反常的是（见 `build/review-2026-11-16/out/hep-ai`），即便传入的 `qecgraph.toml` 中设置 `enabled = false`、`allow_source_upload = false`，只要命令行带了 `--ai-prepare`，程序就会跳过 AI 配置检查，先执行旧 tar 修复和 `known_format_plan` 并写出标有 `"status": "proposed"` 的 `normalization.json`。
2. **修正对非 UTF-8 编码失败原因的判断（不仅是未接入 `encoding.py`，组装子文件还会触发未捕获异常）**
   - 首轮审查指出 `prepare.py` 未接入 `encoding.py` 的 `declared_encoding`。
   - 对比 `build/review-2026-11-16/nonutf8.tar.gz` 复测案例发现更严重的两个问题：
     1. 当主文件 `main.tex` 为合法 UTF-8，而被 `\input{child}` 引入的 `child.tex` 含非 UTF-8 字节（如 `Caf\xe9`）时，`assembly.py` 第 1100 行在子文件 `_assemble_range` 中捕获了 `UnicodeDecodeError` 并试图返回 `unsupported_encoding` 诊断与原始字节 `child_data`；但返回父调用栈后，**第 1208 行立即执行 `out_chars += len(child_data.decode("utf-8"))`，直接抛出未捕获的 `UnicodeDecodeError`**，导致刚才生成的诊断和错误文件路径全部丢失。
     2. macOS 打包常见的 AppleDouble 资源分叉文件（如 `._main.tex`、`._child.tex`，以 `\x00\x05\x16\x07` 开头）会被 `package.py` 当成普通 `.tex` 文件解包进 `SourceTree.files`，在 `entrypoints()` 和 `apply_plan` 全量 UTF-8 校验（`normalization.py` 第 268 行）时直接因二进制头触发解码失败。
3. **新增：`--entry` 显式入口缺少基本文档检查，导致 `.bib` 文件被判为 `complete: true`**
   - 对比 `build/review-2026-11-16/out/bib-entry`：执行 `prepare_arxiv.py ... --entry References.bib` 时，`select_entry` 只检查文件是否存在于 `tree.files`，随后 `prepared_parser.py` 以 `allow_non_tex_entry=True` 将 `.bib` 当作无 `\begin{document}` 的 LaTeX 全文解析，把 `@article{...}` 切成普通 `paragraph` 块，最终返回 `complete: true`（退出码 `0`）。
4. **新增：`acceptance.json` 的“47/47 完整”掩盖了 36/47 篇参考文献在准备阶段丢失或未解析**
   - 对比 `build/reference-audit/corpus.json`：在 47 篇“结构完整”的产出中，**参考文献与引用检查仅 11 篇通过，36 篇失败**。其中 23 篇的根因并非原包缺文献，而是 `prepared_parser.py` 第 260 行一行过滤代码把底层 `parser.py` 已经解析出的外部 `.bib` 条目全部删光了。

---

## 2. 问题总览（修正与增补版）

| 编号 | 类别 | 优先级 | 问题简述 | 涉及位置 / 对应证据 |
| --- | --- | --- | --- | --- |
| P1 | 参考文献断层 | 高 | `prepared_parser.py` 第 260 行过滤掉所有非 `entry` 路径的块，导致 `parser.py` 已解析出的 23 篇外部 `.bib` 条目被全部丢弃 | `prepared_parser.py:255-261`、`build/reference-audit/corpus.json` |
| P2 | 参考文献断层 | 高 | 组装与准备层未将 `\bibliography{...}` 关联到包内已有的 `.bbl` 文件，且未支持 `biblatex` 的 `\entry` 格式 `.bbl` | `assembly.py`、`parser.py`、`build/reference-audit/corpus.json` |
| P3 | 引用键污染 | 高 | `\cite{...}` 内含 `%` 注释换行、RevTeX `*` 前缀或可选参数嵌套花括号时，解析出的 citation key 被污染 | `reading.py`、`build/reference-audit/preliminary.json` |
| P4 | 确定性准备 | 高 | 旧版 tar 零块尾部修复被绑定在 `--ai-prepare` 下；且 `--ai-prepare` 在配置禁用 AI 时仍静默生效 | `tools/prepare_arxiv.py:46-107`、`build/review-2026-11-16/out/hep-ai` |
| P5 | 编码与解包 | 高 | 子文件非 UTF-8 在 `assembly.py:1208` 触发未捕获崩溃丢失文件路径；macOS `._*.tex` 资源文件混入 `SourceTree`；`encoding.py` 未接入准备层 | `assembly.py:1100,1208`、`package.py`、`build/review-2026-11-16/nonutf8.tar.gz` |
| P6 | 数据保真 | 高 | 整文件 `latin1`/`cp1252` 强转把局部非 UTF-8 字节（如 `2209.05640v1` 的 GBK 破折号 `\xa8C`）或混合编码静默转成乱码 `¨C` | `normalization.py:255-263`、`output.schema.json` |
| P7 | 校验安全 | 高 | `_check_guard` 使用 `matched \|=` 汇总全文同名条件，允许篡改正文内非文档包装的条件分支（如 `2308.07915v2` 第 2 处） | `normalization.py:200-215` |
| P8 | 语义保真 | 高 | 将 `\begin{tikzpicture}` 改写为 `\begin{verbatim}` 破坏 LaTeX 语义且受 32 条编辑上限限制 | `normalization.py:136-167`、`prepared_parser.py:499-579` |
| P9 | 来源映射 | 高 | 归一化后 `source-map.json` 指向内存中改写后的派生文本偏移；`_source_projection` 用 `SequenceMatcher` 产生凑字映射 | `normalization.py:368-410`、`prepare.py:66-72` |
| P10 | 入口与契约 | 高 | `--entry References.bib` 等非 TeX 文件被当作完整正文并通过验收（`complete: true`，exit `0`） | `prepare.py:148-152`、`build/review-2026-11-16/out/bib-entry` |
| P11 | 确定性消解 | 中 | 组装器未利用 `Assembler.scopes` 静态消解跨文件 `\ifdefined`/`\ifx` 及字面 `\if 0`；入口消歧未利用 `\input` 包含关系（`2111.05176v1`） | `assembly.py:647-755`、`entry.py` |
| P12 | 阶段边界 | 中 | 开启 `--ai-prepare` 后若下游未达 `complete`，直接抛异常（exit `1`）丢弃本地已组装好的 `partial` 产物；离线与 Workspace 维护两套平行归一化代码 | `tools/prepare_arxiv.py:144-147`、`llm/normalize.py` |
| P13 | 方言与性能 | 中 | `declaration_alias_edits` 遇 `\iff`/`\input` 永久置位失败；`normalization.json` 内嵌整文件 Base64；AI 证据跳过超长行 | `dialects.py:102-109`、`normalization.py:278-284`、`llm/prepare.py:160-163` |

---

## 3. 架构与阶段边界问题

### 3.1 准备阶段的成功判据和落盘仍与下游结构解析强耦合

- **位置**：[prepare.py](../../../qecgraph/source/prepare.py) 第 33–46 行、第 335–429 行；[prepare_arxiv.py](../../../tools/prepare_arxiv.py) 第 53–81 行。
- **问题**：
  - 虽然 `prepare.py` 拆分出了 `PreparedInput`（只负责选入口和组装 `entry.tex` + `source-map.json`），但 `write_outputs` 仍强制要求传入包含下游 `document.json` / `coverage.json` 的 `PreparedSource`，无法独立输出纯准备层产物。
  - 在 `prepare_arxiv.py` 的 `_prepare` 中，程序必须先跑完一次完整的下游 `parse_prepared`（将整个源码树物化到临时目录、跑 `pylatexenc`、若报错再按顶层 `\input` 切片逐块重跑 `_salvage_ranges`），发现 `coverage["complete"]` 为 `False` 后，才去尝试确定性格式转换 `known_format_plan`。

### 3.2 开启 `--ai-prepare` 后，若未达 `complete` 会丢弃已有的本地准备结果

- **位置**：[prepare_arxiv.py](../../../tools/prepare_arxiv.py) 第 82–85 行、第 144–147 行。
- **问题**：
  - 在不带 `--ai-prepare` 时，`partial` 论文（退出码 `2`）仍会正常写出组装好的 `entry.tex` 和 `source-map.json`。
  - 一旦带上 `--ai-prepare`，如果 2 次尝试后下游解析仍未达到 `complete`，第 144 行直接抛 `ValueError("Normalized input still fails downstream parsing...")` 并以退出码 `1` 退出，**不写出任何文件**（连本地原本能组装出的 `entry.tex` 和诊断信息都不输出）。

### 3.3 离线准备与 Workspace 入库存在两套平行的归一化实现

- **位置**：[source/normalization.py](../../../qecgraph/source/normalization.py)、[llm/prepare.py](../../../qecgraph/llm/prepare.py) 与 [llm/normalize.py](../../../qecgraph/llm/normalize.py)。
- **问题**：
  - 离线准备新建了 `source/normalization.py` + `llm/prepare.py`（使用 `prepare_input` v9 skill）；而工作区入库仍在用 `llm/normalize.py`（使用 `normalize_package` v3 skill）。
  - 两套代码能力互补却互不连通：`normalize_package` 支持主文与独立 supplement/appendix 拼接（`append_appendix` / `append_body`），但不支持 `\input` 展开、编码投影和编译守卫；`prepare_input` 反过来只选单一入口，无法合并独立编译的补充材料文档。

---

## 4. 确定性准备阶段的缺陷

### 4.1 确定性的旧版 tar 零块尾部修复被绑定在 `--ai-prepare` 下，且绕过 AI 启用检查

- **位置**：[prepare_arxiv.py](../../../tools/prepare_arxiv.py) 第 46–107 行；[normalization.py](../../../qecgraph/source/normalization.py) 第 75–130 行。
- **问题**：
  - 只有传入 `--ai-prepare` 才会调用 `load_for_preparation(args.source, repair_legacy_tar=True)`，导致 `hep-th/9407087v1` 和 `quant-ph/9604034v1` 在默认离线模式下直接报错退出（exit `1`）。
  - 反过来，当用户传入 `--ai-prepare --ai-config-root cfg` 且 `cfg/qecgraph.toml` 中明确设置 `enabled = false, allow_source_upload = false` 时（见 `build/review-2026-11-16/out/hep-ai`），因为 `_prepare` 在第 46–81 行先执行了 `load_for_preparation` 和 `known_format_plan` 并直接返回，根本没有走到第 104 行的 `if not config.enabled` 检查，且产出的 `normalization.json` 仍标为 `"status": "proposed"`。
  - 此外，当 `quant-ph/9604034v1` 走第 56–62 行分支时，生成的 `normalization` 字典只有 `{"schema": ..., "status": "derived", "loading": [...]}`，缺少 `original_tree_sha256`、`normalized_tree_sha256`、`entry` 等字段，导致 [prepare.py](../../../qecgraph/source/prepare.py) 第 68–71 行在生成 `source-map.json` 时漏掉了 `normalization` 关联标记。

### 4.2 组装器（`assembly.py`）未复用自身已跟踪的宏定义来消解 `\ifdefined` / `\ifx` 与 `\if 0`

- **位置**：[assembly.py](../../../qecgraph/source/assembly.py) 第 647–755 行、第 1302–1315 行。
- **问题**：
  - **跨文件编译守卫（如 `2308.07915v2`）**：`arXiv_v2.tex` 在 `\input{supplemental_v2.tex}` 前一行明确定义了 `\newcommand{\maindocument}{}`。`Assembler.scopes` 已经按源码顺序跟踪了所有 `\newcommand`/`\def`（并且 `parser.py` 的 `_scan_structure` 也已支持静态判定 `\ifdefined`），但 `assembly.py` 的 `_scan` 是单文件静态扫描，只认字面 `\iftrue`/`\iffalse`，不查 `Assembler.scopes`，导致 `\ifdefined\maindocument` 无法在组装阶段直接消解。
  - **字面恒假分支 `\if 0`（如 `2511.01062v1`、`2511.01062v2`）**：[normalization.py](../../../qecgraph/source/normalization.py) 第 190–198 行已经写出了判断 `\if 0` 为字面恒假注释块的完整确定性规则，却不在组装或确定性归一化中直接处理，而是发请求让大模型把 `\if 0` 改成 `\iffalse`。

### 4.3 主文件识别与显式 `--entry` 校验缺陷

- **位置**：[prepare.py](../../../qecgraph/source/prepare.py) 第 86–94 行、第 148–162 行；[entry.py](../../../qecgraph/source/entry.py) 第 32–47 行、第 96–114 行。
- **问题**：
  - **显式 `--entry` 未校验文件类型或文档结构**：如 `build/review-2026-11-16/out/bib-entry` 所示，传入 `--entry References.bib` 会把 `.bib` 文件原样组装为 `entry.tex`，并因 `allow_non_tex_entry=True` 和无 `\begin{document}` 时默认全文为 body，将 BibTeX 条目解析为普通段落，最终给出 `complete: true`（退出码 `0`）。
  - **未剥离注释即匹配文档标记**：`prepare.py` 的 `looks_like_tex` 没有先去掉 `%` 注释。若子文件在注释里保留了 `%\documentclass` 和 `%\begin{document}`，会被误判为顶层候选入口。
  - **`_values` 未跳过宏名与参数间的空白**：`entry.py` 提取 `\title` 和 `\author` 时，未跳过 `\title` 与 `[`、或 `]` 与 `{` 之间的空格/换行（例如 `2111.05176v1` 中的 `cas-sc-template.tex` 使用 `\title [mode = title]{...}`，导致标题被提取为空字符串）。
  - **`_identical_context` 的目录对称性 bug 与重复组装**：`entry.py` 第 96–114 行在比较不同目录下的同字节入口时，若 `representative` 在根目录（`base = '.'`），遍历到根目录候选时 `prefix = ''`，只单向检查了子目录文件在根目录是否存在，没检查反向；反之若 `representative` 在子目录而另一候选在根目录，`base / path` 会拼出双层目录导致永远返回 `None`。
  - **未利用 `\input`/`\include` 包含树消歧（如 `2111.05176v1`）**：`build/review-2026-11-16/out/2111-explicit` 证实，只要选定 `main.tex`，`2111.05176v1` 无需任何改写即可 100% 确定性解析通过（2,022 个 block）。`main.tex` 包含了全部 16 个章节文件，而 `Per Section Compilation/error-mit-main.tex` 只包含其中 1 个章节，其余两个候选是模板文件。通过字面 include 集合的包含关系即可确定性选出 `main.tex`。

---

## 5. 参考文献与引用准备链路的断层（对比新增）

对比 `build/reference-audit/corpus.json`（47 包中仅 11 包通过参考文献审计，36 包未通过），当前准备阶段在参考文献与引用处理上存在三处直接断层：

### 5.1 `prepared_parser.py` 误删了底层解析器已提取的全部外部 `.bib` 条目（影响 23 篇）

- **位置**：[prepared_parser.py](../../../qecgraph/source/prepared_parser.py) 第 255–261 行。
- **问题**：
  ```python
  outside = sorted({
      str((block.get("source") or {}).get("path"))
      for block in blocks
      if (block.get("source") or {}).get("path") != name
      and block.get("kind") != "bib_entry"})
  blocks = [block for block in blocks
            if (block.get("source") or {}).get("path") == name]
  ```
  - 底层 `parse_project`（`parser.py` 第 1180–1198 行 `emit_bib_resources`）实际上已经读取了包内的 `.bib` 文件并生成了 `kind == "bib_entry"` 的块（其 `source.path` 为 `refs.bib` 等相对路径）。
  - `prepared_parser.py` 第 259 行特意在统计 `outside` 依赖警告时豁免了 `bib_entry`，但紧接着在**第 260–261 行**却用 `source.path == name`（即只保留来自临时组装入口 `__qecgraph_prepared_entry__.tex` 的块）把所有来自 `.bib` 文件的 `bib_entry` 块全部过滤丢弃了！
  - 这直接导致 23 篇带 `.bib` 文件的论文在 `document.json` 中 `bib_entry` 数量变成 `0`（`external_entries_omitted: 23`）。

### 5.2 `\bibliography{...}` 未自动关联或内联包内已有的 `.bbl` 文件（影响至少 9 篇）

- **位置**：[assembly.py](../../../qecgraph/source/assembly.py) 第 25–30 行；[parser.py](../../../qecgraph/source/parser.py) 第 694–695 行。
- **问题**：
  - arXiv 投稿包中极常见的情况是：作者在源码中写 `\bibliography{refs}`，但上传归档时按 arXiv 规定只附带编译好的 `main.bbl` 或 `refs.bbl`（不附带 `refs.bib`，如 `1208.2317v1` 含 `ft-def25.bbl`、`1302.3428v1` 含 `QEC04_springer.bbl`、`1804.03719v1` 含 `main.bbl`）。
  - 在 LaTeX 中，`\bibliography{...}` 在编译期的实际行为就是 `\input{\jobname.bbl}`。但当前 `assembly.py` 不处理 `\bibliography`，而 `parser.py` 第 694 行在解析 `\bibliography{foo}` 时强制将无后缀名称改为 `foo.bib`（从不查找同目录下的 `foo.bbl` 或 `<entry_stem>.bbl`），导致这些包内明明有完整的 `.bbl` 文件却报错 `missing_resource` 并丢失全部文献条目。
  - 此外，对于使用 `biblatex`/`biber` 生成的 `.bbl`（使用 `\entry{key}{type}{}` 而非 `\bibitem{key}`，如 `2609.22572v1`），当前解析器尚未支持识别。

### 5.3 `\cite{...}` 参数解析被注释、换行、RevTeX `*` 和嵌套花括号污染

- **位置**：[reading.py](../../../qecgraph/source/reading.py) 第 64–74 行；对比证据见 `build/reference-audit/preliminary.json` 第 19–32 行、第 53 行。
- **问题**：
  - 在 `1208.2317v1` 中，多行 `\cite` 内部含有行尾 `%` 注释和 `\r\n`（例如 `\cite{key1,%\r\n key2}`）。`reading.py` 的 `reading_projection` 在提取 citation keys 时未先剥离 `%` 注释，直接按逗号切分并 `strip()`，生成了形如 `"%\r\n    Delfosse-Zemor-2012"` 的脏 key。
  - RevTeX 支持在 `\cite{*key}` 前加 `*` 表示与上一条文献合并编号，当前提取未剥离前导 `*`（生成了 `"*Gottesman:PRA1998"`）。
  - 当 `\cite` 的可选参数中含有嵌套花括号（如 `\cite[{Theorem 1.2 in }]{Hofstad-2010}`）时，可选参数边界识别失败，导致产出了 `"[{Theorem 1.2 in }]Hofstad-2010"` 这样的错误引用键。

---

## 6. 转换、编码与校验中的正确性 Bug

### 6.1 子文件编码异常导致未捕获崩溃、AppleDouble 污染与整文件 `latin1` 乱码

- **位置**：[assembly.py](../../../qecgraph/source/assembly.py) 第 1100–1104 行、第 1208 行；[package.py](../../../qecgraph/source/package.py) 第 122–149 行；[normalization.py](../../../qecgraph/source/normalization.py) 第 255–269 行。
- **问题**：
  1. **子文件非 UTF-8 触发崩溃**：`assembly.py` 第 1100 行在子文件中捕获 `UnicodeDecodeError` 后返回原始非 UTF-8 字节 `child_data`，但父函数第 1208 行调用 `child_data.decode("utf-8")` 时未做异常处理，直接崩溃并丢失出错子文件路径（已在 `build/review-2026-11-16/nonutf8.tar.gz` 复现）。
  2. **macOS AppleDouble (`._*`) 文件污染**：`package.py` 未过滤或标记归档中的 `._*` AppleDouble 元数据文件（以 `\x00\x05\x16\x07` 开头）。当包内含 `._main.tex` 时，因其后缀为 `.tex`，会被 `SourceTree.entrypoints()` 和 `normalization.py` 第 268 行当作 TeX 源码做 UTF-8 解码而失败。
  3. **显式编码声明未接入准备层**：`encoding.py` 已实现 `declared_encoding`（识别 `inputenc` 等），但 `prepare.py`、`entry.py`、`assembly.py` 均未调用。
  4. **整文件 `latin1`/`cp1252` 强转造成静默乱码**：如 `2209.05640v1` 全文仅第 1506 行有一处 GBK 破折号 `\xa8C`（`—`），AI 选择整文件 `latin1` 后将其静默变成了 `7095¨C--7113`。若文件含合法 UTF-8 多字节字符且仅有一处坏字节，整文件转 `latin1` 会把全文所有合法 UTF-8 字符全部破坏为乱码。

### 6.2 `_check_guard` 的 `matched |=` 逻辑漏洞允许篡改正文中的非包装条件分支

- **位置**：[normalization.py](../../../qecgraph/source/normalization.py) 第 200–215 行。
- **问题**：
  - `_check_guard` 本意是只允许归一化包含 `\documentclass`/`\begin{document}`/`\end{document}` 的文档包装条件分支。
  - 但代码遍历全文所有同名 `old` 出现位置并用 `matched |= any(...)` 汇总：只要文件中**任意一处** `\ifdefined\maindocument` 含 `\documentclass`，文件中**所有其他位置**的 `\ifdefined\maindocument`（包括 `2308.07915v2` 正文中间控制图表排版的第 2 处分支）都能绕过检查被替换。此外 `text.find("\\fi", occurrence.end())` 未考虑嵌套 `\if...\fi`。

### 6.3 把 `\begin{tikzpicture}` 替换为 `\begin{verbatim}` 破坏了 LaTeX 语义

- **位置**：[normalization.py](../../../qecgraph/source/normalization.py) 第 136–139 行、第 160–167 行；[prepared_parser.py](../../../qecgraph/source/prepared_parser.py) 第 499–579 行。
- **问题**：
  - `2605.29137v1` 报 `conditional_body` 是因为 `tikzpicture` 内部用了 TikZ 循环中的 `\ifodd\i`。
  - 通过 AI 把 `\begin{tikzpicture}` 改写成 `\begin{verbatim}` 篡改了 `entry.tex` 的 LaTeX 语义，且受 `output.schema.json` 最多 32 条 `edits`（16 张图）限制。应在 `prepared_parser.py` 扫描条件区域时直接将 `tikzpicture` 视为绘图容器跳过，而非改写源文件。

### 6.4 `dialects.py` 中 `declaration_alias_edits` 与 `harvmac_edits` 的脆弱性

- **位置**：[dialects.py](../../../qecgraph/source/dialects.py) 第 86–133 行、第 202–227 行；[normalization.py](../../../qecgraph/source/normalization.py) 第 54–56 行。
- **问题**：
  - `dialects.py` 第 102–109 行中，`name.startswith("if")` 会把数学符号 `\iff` 也当成条件语句；且布尔变量 `conditional` 一旦变为 `True`，在文件剩余部分**永不重置回 `False`**。
  - `declaration_alias_edits` 仅在组装前按单文件独立运行，不支持跨文件定义与使用。
  - `_harvmac_equations` 会把全文所有与公式标签同名的控制序列 `\labelname` 无条件替换为 `\ref{labelname}`；同时 `normalization.py` 第 55 行过滤了 `not path.endswith(".tex")`，无法自动发现无后缀名的 Harvmac 源文件。

---

## 7. 统一输出文件与来源映射的一致性问题

1. **`source-map.json` 和 `document.json` 的坐标指向内存中改写后的派生文件，而非原始文件**
   - 经 `apply_plan` 改写文件内容后，`assemble_files` 在改写后的 `normalized.tree` 上运行，产出的 `source-map.json` 和 `document.json` 记录的是改写后文本的偏移，而改写后的单文件并未落盘。下游读取者若不自行实现 `source-map.json` 与 `normalization.json["source_projections"]` 的二次区间复合，直接按 `source-map.json` 读取原始包文件会发生偏移错位。
2. **`_source_projection` 使用字符级 `SequenceMatcher` 产生了伪造的原始字节映射**
   - [normalization.py](../../../qecgraph/source/normalization.py) 第 386–394 行对编辑块的 `old` 和 `new` 运行 `SequenceMatcher`，把 `\iftrue` 末尾的 `'e'` 映射到 `\ifdefined` 中的 `'e'`（标记为 `"original_bytes": [4, 5]`），把 `verbatim` 中的 `'i'`、`'r'` 映射到 `tikzpicture` 中的字母字节。语法替换应整体标记为 `replaces_original_bytes`，不应做字符级凑字映射。
3. **`normalization.json` 原样内嵌整文件 Base64 造成产物膨胀**
   - [normalization.py](../../../qecgraph/source/normalization.py) 第 278–284 行将被修改文件的完整原始字节以 Base64 写入 `normalization.json`，大文件单字符修改即会导致产物膨胀上兆字节。

---

## 8. 关于引入本地 TeX 编译器的评估与建议（对比新增）

针对近期讨论的“是否跳过静态准备、直接先调用本地 TeX 编译器（`pdflatex`/`bibtex`/`tex4ht`）再准备”（参考 `build/tex-compiler-probe/result.json`）：

1. **为什么不建议用“必须先编译通过”替代静态准备主路径**：
   - **历史包与宏包环境差异**：arXiv 跨度 30 年的源码包（如 1990s 的 Harvmac、旧版 `revtex`/`epsfig`、作者自定义或期刊专有 `.cls`/`.sty`）在现代 TeX Live 2026 下经常无法一次编译通过，而静态展开无需排版宏包即可毫秒级提取正文与公式。
   - **字节级来源映射保真度**：项目的核心契约是所有片段和公式保留原始 TeX 字节与精确的半开区间坐标（`[byte_start, byte_end)`）。若通过 `tex4ht`（转 HTML/MathML）或 `pdftotext` 作为主输入，宏会被完全展开、数学公式会被重写，SyncTeX 只能提供行级近似定位，无法保持现有的字节级 `source-map.json` 契约。
2. **为什么当前 36/47 的参考文献失败绝大多数根本不需要跑 `pdflatex`**：
   - 从第 5 节的对比可见：36 个失败包中，**23 个**是因为 `prepared_parser.py` 第 260 行误删了已解析的 `.bib` 条目；**约 9 个**是因为包内本来就有作者上传的 `.bbl` 文件，只是程序没把 `\bibliography{...}` 映射到同名或主文件同名的 `.bbl`；还有若干是 `\cite` 内注释/换行未清理。修复这三处纯 Python 静态逻辑后，绝大部分包的参考文献无需启动 TeX 编译器即可在静态阶段完整解决。
3. **本地 TeX 工具链的最佳定位：隔离的、按需触发的辅助补全通道（Sidecar）**
   - 当包内**只有 `.bib` 而无 `.bbl`、或者正文定义了复杂引用包装宏（如 `\citeRef0`）**时，可以在沙箱临时目录中按需调用 `bibtex`/`biber`（或 `-recorder` 生成 `.fls`/`.aux`/`.bbl`），将生成的派生 `.bbl` 和 `.aux` 引用映射作为补充产物交还给静态准备层。这样既能 100% 保持原文字节映射和毫秒级静态速度，又能补齐静态解析难以处理的动态宏引用与未预编译书目。

---

## 9. 改进优先级建议

1. **P0（立即可修的静态阻断与断层，无需 AI 也无需重架构）**：
   - 修复 `prepared_parser.py` 第 260–261 行，保留 `kind == "bib_entry"` 的外部书目块并正确映射其文件坐标；
   - 在 `assembly.py` / `parser.py` 中支持将 `\bibliography{foo}` 自动关联到包内已存在的 `foo.bbl` 或 `<entry_stem>.bbl`，并支持识别 `biblatex` 的 `\entry{...}` 书目块；
   - 在 `reading.py` 提取 `\cite` keys 前先剥离 `%` 注释、换行、RevTeX 前导 `*` 并正确跳过含嵌套花括号的可选参数 `[...]`；
   - 默认启用 `load_for_preparation` 的旧 tar 零块尾部修复（脱离 `--ai-prepare` 开关），并在 `package.py` 中过滤或忽略 macOS `._*` AppleDouble 资源文件；
   - 修复 `assembly.py` 第 1208 行对非 UTF-8 子文件返回值的二次 `.decode("utf-8")` 崩溃，接入 `encoding.py` 的 `declared_encoding`；
   - 在 `select_entry` 中校验显式 `--entry` 必须为 TeX 源文件（拒绝 `.bib` / 二进制文件直接当成正文入口）。
2. **P1（收回确定性语法消解，消除不必要的 AI 调用与语义篡改）**：
   - 在 `assembly.py` 中利用 `Assembler.scopes` 静态消解已知宏的 `\ifdefined` / `\ifx` 以及字面 `\if 0`；
   - 在 `prepared_parser.py` 中将 `tikzpicture` 识别为绘图容器（不因图内 `\ifodd`/`\ifnum` 报正文 `conditional_body`），移除把 `tikzpicture` 改写为 `verbatim` 的规则；
   - 修复 `entry.py` 中 `looks_like_tex` 注释未剥离、`_values` 空白未跳过、`_identical_context` 目录比较不对称的问题，并加入基于 `\input` 覆盖关系的入口消歧。
3. **P2（修正归一化坐标契约与可选编译辅助）**：
   - 移除 `_source_projection` 中的 `SequenceMatcher` 凑字映射，将替换区间与 `assembly.py` 的 `Segment` 直接复合，使 `source-map.json` 直接指向原始包文件字节偏移；
   - 修复 `_check_guard` 只检查当前被编辑的 `occurrence`；
   - 当 `--ai-prepare` 未能使下游完全通过时，保留并输出本地已组装出的 `entry.tex` 和 `partial` 诊断（退出码 `2`）。
