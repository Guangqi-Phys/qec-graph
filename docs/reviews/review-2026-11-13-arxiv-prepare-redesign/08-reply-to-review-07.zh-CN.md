# 离线 prepare 第三轮整改回复

> 对应 [07：离线 prepare 第三轮实现复评](07-review-of-06-remediation.zh-CN.md)。整改基线 `6bea6d901d6c7176a43be7a44c2858882d3ba2d5`，完成提交 `85cd8e3`（本轮四个提交已推送到 `origin/main`）。状态：S1–S5 已实施并有内容级回归；§6 的遗留项保持未验收。

本文件只记录本轮整改；没有修改 07 及更早评审的正文，没有修改原始论文包、`human/` 或 QEC-database。07 §5 的九个反例与 S1 的恢复探针均已复跑，见 §4。

## 目录

- [1. 结论](#1-结论)
- [2. 逐项回应 S1–S5](#2-逐项回应-s1s5)
- [3. 整改中补充的修正](#3-整改中补充的修正)
- [4. 07 反例复跑](#4-07-反例复跑)
- [5. 测试与语料](#5-测试与语料)
- [6. 仍未完成](#6-仍未完成)
- [7. 提交与复现命令](#7-提交与复现命令)

## 1. 结论

- 07 的 S1–S5 全部复现、全部修复，没有发现误报。每项都有内容级回归，S1 另有目标目录被重建的冲突用例。
- 更正 06 的一个错误判断：06 说分支内作用域和 `\ifcase` 的限制“只会更保守，不会确定地选错”，这不成立。S2 的三个案例确实产生了确定的错误路径；本轮已改为按完整作用域快照合并分支，并对 `\ifcase` 的所有分支取不确定。
- 07 指出的“多个扫描器各自解释同一种语法”是准确的结构问题。本轮让条件配对、条件分析、文档边界共用 `_conditional_branches` 的词法规则，并让 prepare 的条件分析使用解析视图。
- 47 包退出码保持 29/7/11；block 12003、section 1035 不变；diagnostics 从 38 降到 36。
- 全量测试 438 → 452 项；本机仍只有 2 个 pty 环境错误，其余通过。

## 2. 逐项回应 S1–S5

| 编号 | 结论 | 提交 | 主要回归 |
| --- | --- | --- | --- |
| S1 | 已修复 | `a4744d3` | 冲突用例覆盖空目录、无关文件、另一份受管理产物；原有中断恢复用例保留 |
| S2、S3 | 已修复 | `28386b1` | 5 个 assembly 用例 + 3 个 prepare 内容用例 |
| S5 | 已修复 | `4a7b8e2` | `test_condition_after_a_spliced_comment_is_still_analysed` |
| S4 | 已修复 | `85cd8e3` | 内容检测单测 + 数学、`\textbf`、Unicode 三个 prepare 用例 |

### S1 恢复不再删除唯一旧备份

**复评判断：成立。** `recover_output` 只看 `out.is_dir()`，目标目录被重新创建（空目录、无关文件或另一份受管理产物）时会删除 backup 并报告 committed。

**实施**：

- journal 记录 `previous_manifest_sha256` 与 `new_manifest_sha256`（manifest 文件字节的 SHA-256）。
- 恢复按目标 manifest 摘要判断：
  - 等于预期新版本 → `committed`，清理 staging/backup；
  - 等于记录的旧版本 → `aborted`，保留目标、清理 staging；
  - 目标不存在 → 有 backup 则 `restored`，否则暂存完整则 `cleaned`；
  - 其他情况（空目录、无关目录、不同产物）→ `conflict`，**不删除 journal 和 backup**。
- `write_outputs` 遇到冲突直接抛错并提示 backup 位置；`--recover` 冲突时退出码 1，明确列出保留的目录。
- 新增用例覆盖三种冲突前状态；07 的“mkdir 目标目录”路径现在返回 conflict，移开目录后可再次恢复旧 manifest（逐字节一致）。

### S2 分支合并保留作用域与全部分支

**复评判断：成立。** 旧实现把分支定义写进单一字典，绕过花括号与 `global_scope`；离开条件只比较两个字典；`\ifcase` 的 `\or` 分支被顺序执行到同一个字典。

**实施**：

- 每个条件保存进入时的完整作用域栈快照；每个分支在快照副本上正常执行花括号、`\begingroup`、`\gdef` 等规则；分支切换时丢弃当前状态并回到快照。
- 离开条件时合并各分支**结束时可见**的值：所有分支都是相同确定字符串才保留；全部分支都未定义则不写入；否则写 `UNCERTAIN`。
- 全局写入单独记录；所有分支都执行相同全局写入时按全局生效（写入根作用域并清除局部遮蔽），否则结果不确定。
- `\ifcase` 用 `_conditional_branches` 按 `\or`/`\else` 拆出所有分支；没有 `\else` 时补一个隐式空分支。07 的 `ifcase` 案例现在没有 target、partial，不再选 `two`。
- 回归覆盖：局部定义退出后恢复、全局定义保留、`ifcase` 不同值不确定、`ifcase` 同值确定、无 `\else` 时不泄漏。

### S3 条件配对使用词法上下文

**复评判断：成立。** `_conditional_bounds` 直接扫描控制词，`\fi` 出现在声明体或 verbatim 中时会提前结束条件。

**实施**：新增 `_conditional_branches`，按与 `_scan` 一致的规则跳过注释、`\verb`、字面环境、声明体与 `\newif`，并在 `\ifcase` 中把深度为 1 的 `\or` 当作分支分隔。`_conditional_bounds`、`_scan`、`document_bounds`、`condition_regions` 都改用这条路径。

**验证**：07 的 `S3_definition`、`S3_verbatim` 现在都使用 `one/frag.tex`，`CORRECT_ONE.` 进入模型，complete。

### S5 条件分析改用解析视图

**复评判断：成立。** 结构解析使用补过分隔符的副本，但 `document_bounds`、`condition_regions` 与条件正文计数仍读原始 entry。

**实施**：`prepare_source` 只构造一次 `EntryCoordinates`，把解析副本传给 `_parse_entry`；文档边界与条件区间在解析副本上计算，再用 `to_entry` 映射回 entry，供 block 标记、coverage 与 source spans 使用。原始 entry 字节和 source map 不变。

**验证**：07 的 `S5_comment_then_condition` 现在 `conditional_body`、partial，`conditional_ranges` 非空，块 `conditional=true`，区间来源落在 main.tex。

### S4 条件完整性改用可见内容

**复评判断：成立。** `conditional_body` 复用 ASCII 字母计数，数学、`\textbf` 参数、Unicode 和短串都不计入，因此互斥分支仍被判完整。

**实施**：

- 新增 `_conditional_has_content`：逐 token 判断不确定条件区域是否有可见内容。
  - 注释、声明体、`\let`/`\newif`、布局命令及其参数、格式开关及其参数不计内容；
  - 数学（`$`、`\(`、`\[`）、文字、命令参数、Unicode、未知命令都算内容；
  - 条件自身的控制词与测试 token（含 `\csname...\endcsname`、`ifx` 的两个操作数）跳过，不作为内容。
- coverage 新增 `conditional_content_regions`；只要存在有内容的区域就 `structure_complete=false`，原因仍为 `conditional_body`。`conditional_body_chars` 保留为正文计数的提示指标。
- 07 的数学、`\textbf`、中文三个案例现在都 partial；纯排版条件（`\vspace`、只含定义的条件）仍 complete。
- 同时修正了 `\providecommand\name[1]{...}` 这种无花括号目标的声明跳过；它此前让 LaTeX2e 宏体里的条件被当作正文条件，造成三个误报 partial。

## 3. 整改中补充的修正

- **无 `\else` 的隐式空分支**：只有显式分支参与合并会把“未执行却有可能执行”的缺失状态漏掉。现在不可判定条件若没有 `\else`，补一个空分支参与合并；S2 的无 `\else` 泄漏用例因此通过。
- **`\providecommand\name` 的声明形式**：`_skip_definition` 与 `_LITERAL_MACRO`/`_NEWCOMMAND_NAME` 接受无花括号的目标。此前 LaTeX2e 内部的 `\providecommand\@ifx[1]{...}` 被当成正文，让条件区域出现在宏定义里。
- **`\csname` 作为条件测试 token**：`\ifx\csname urlstyle\endcsname\relax` 的两个操作数被正确跳过，避免把 `urlstyle` 计成正文。
- **多分支事件**：`_ConditionalEvent` 现在支持多个 `switch`；作用域快照与全局写入列表按分支保存，嵌套条件的全局写入会传播到外层分支记录。

## 4. 07 反例复跑

| 案例 | 07 基线 | 当前 |
| --- | --- | --- |
| S1 中断后重建空目录 | committed，backup 被删 | conflict，backup/journal 保留；移开目录后可 restored |
| S1 中断后放入无关文件 | committed，backup 被删 | conflict，backup 保留 |
| S1 中断后放入另一份受管理产物 | committed，backup 被删 | conflict，backup 保留 |
| S2 局部定义（两个分支都在花括号内） | 读 `two`，complete | 读 `one`，complete |
| S2 全局定义（两个分支都 gdef） | 读 `one`，complete | 读 `two`，complete |
| S2 `ifcase` 三分支 | 读 `two`，complete | 无 target，partial |
| S3 定义体中的 `\fi` | 读 `two`，complete | 读 `one`，complete |
| S3 verbatim 中的 `\fi` | 读 `two`，complete | 读 `one`，complete |
| S4 数学分支 | complete | `conditional_body`，partial |
| S4 `\textbf` 分支 | complete | `conditional_body`，partial |
| S4 Unicode 分支 | complete | `conditional_body`，partial |
| S5 注释后接条件 | complete，无 conditional 标记 | `conditional_body`，partial，块与区间已标记 |

## 5. 测试与语料

- 全量测试 438 → **452** 项，新增 14 项；本机 2 个错误均为 `integration.cli.test_progress` 的 pty 环境问题，其余通过。
- 47 包：退出码 **29/7/11** 不变；block **12003**、section **1035** 不变；diagnostics 38 → 36。
- 36 个产出模型仍通过 `prepare_source` 内的 source-map 校验；S5 之后条件区间还额外经过 parse → entry 映射，回归检查了 `source_spans` 落在正确文件。
- 语料仍为一次性探针，未入库；这些数字是回归证据，不是人工内容金标。

## 6. 仍未完成

- **条件标记仍留在阅读文本里**：block 的 `text` 仍包含 `\ifdefined`/`\else`/`\fi`，本轮通过 `conditional` 与 `conditional_ranges` 表达不确定性，没有改写 `text_projection`。
- **assembly 的 `_scan` 仍读原始 entry**：prepare 的条件分析与覆盖已改用解析视图，但指令展开发生在组装阶段，无法事后使用带分隔符的副本。若拼接注释把一条指令遮住，该指令不会被展开，parser 读到的外部内容会触发 R1 的 `include_outside_entry`，结果降级为 partial，但指令本身仍留在 entry 中。
- **`\ifcase` 不支持按值选择**：所有分支参与合并，值不同即不确定；这是保守处理，不是精确语义。
- **条件配对仍是启发式**：未声明、也不带参数或花括号的 `\if...` 宏可能被当作条件；缺少 `\fi` 时会报 `unclosed_conditional` 并降级，而不是静默处理。
- **覆盖计数仍是提示**：`uncovered_entry_chars` 与 `conditional_body_chars` 继续是 ASCII 字母启发式；`conditional_body` 的判定已改用可见内容，但“已建模/明确排除/保留”分类仍未实现。
- **恢复依赖 journal 与 backup 仍存在**：外部删除 backup 或 journal 后无法恢复；断电、磁盘满、文件系统损坏未测试。
- **人工金标与编译对照**：未建立 47 包内容金标，未执行 TeX/PDF 编译、Docker、Lean 或真实模型；下游 QEC-database 检索评测仍记为未验收。
- **旧链接**：02/03 的三处相对链接仍指向重命名前的文件名；本轮没有修改历次评审正文。

## 7. 提交与复现命令

| 提交 | 内容 |
| --- | --- |
| `a4744d3` | S1 恢复冲突检测与备份保留 |
| `28386b1` | S2/S3 分支作用域快照与词法条件配对 |
| `4a7b8e2` | S5 条件分析使用解析视图 |
| `85cd8e3` | S4 可见内容门槛 |

本机执行：

~~~sh
# 全量测试：452 项，2 个 pty 环境错误（环境限制，见 05/06 记录）
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests

# 07 §5 的九个内容反例：按 07 §5 的脚本运行
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python <07 的 review07.py>

# 中断后冲突与恢复：构造旧产物 -> 注入终止 -> 重建目录 -> --recover
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/prepare_arxiv.py \
  --out /tmp/prepared/paper --recover --json
~~~

47 包对比仍使用一次性探针，基线通过 `git archive` 解出到临时目录后用同一脚本运行；数字只用于回归。

## 8. 文档说明

本回复为第 8 份文件，沿用 `0N-...` 的顺序；没有改动 01–07 的正文。02/03 的三处旧链接仍按 05 §4.3 的建议留待一次只改链接的提交。
