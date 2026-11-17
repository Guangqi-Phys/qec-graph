# 离线 prepare 第二轮整改回复

> 对应 [05：离线 prepare 整改复评（第二轮）](05-review-of-04-remediation.zh-CN.md)。整改基线 `2b4b0939360a66fbcf5db1f70b8f9d72b72177d4`，完成提交 `6bea6d9`（本轮七个提交已推送到 `origin/main`）。状态：R1–R6 与 §4.2 的规则版本已实施；§4.1 的覆盖计数仍保留为启发式，§4.3 的三处旧链接和人工金标仍在 §6 列为未完成。

本文件只记录本轮整改；没有修改 01–05 的正文，没有修改原始论文包、`human/` 或 QEC-database。复评的九个内容反例已全部复跑，见 §4。

## 目录

- [1. 结论](#1-结论)
- [2. 逐项回应 R1–R6](#2-逐项回应-r1r6)
- [3. 复评未列、整改中发现的问题](#3-复评未列整改中发现的问题)
- [4. 复评反例复跑](#4-复评反例复跑)
- [5. 47 包回归与测试](#5-47-包回归与测试)
- [6. 仍未完成](#6-仍未完成)
- [7. 提交与复现命令](#7-提交与复现命令)

## 1. 结论

- 05 的六个 R 问题全部复现、全部修复，没有发现误报。每条都有直接检查输出内容的回归；进程中断窗口另有子进程注入回归。
- 本轮修复的重点从“原案例通过”改成“状态传播保守”：不确定的宏和条件正文一律降级，不再沿用旧值或把互斥分支当作确定正文。
- 47 包退出码保持 29/7/11；block 12003、section 1035 与 04/05 的记录一致。诊断总数从 44 降到 38（`\iff`、`iftoggle` 一类的误识别减少）。
- 全量测试 414 → 438 项；本机 2 个真实 pty 测试仍报 `out of pty devices`，与 04 记录的环境问题相同，其余全部通过。
- 05 §4.2 的版本问题已处理：manifest 新增独立 `prepare_version=prepare-rules-v2`，不提升 workspace 的 `PARSER_VERSION`（`parser.py` 未改，避免无关快照重建）。

## 2. 逐项回应 R1–R6

| 编号 | 结论 | 提交 | 主要回归 |
| --- | --- | --- | --- |
| R1 | 已修复 | `0f87304` | `test_iffalse_with_a_comment_keeps_the_else_branch`、正文 `include_not_in_entry` 降级的两级用例 |
| R4 | 已修复 | `9626b1a` | `test_child_comment_without_final_newline_keeps_parent_text` |
| R2 | 已修复 | `6366a87` | 6 个 assembly 用例 + 2 个 prepare 内容用例 |
| R5 | 已修复 | `da93fc3` | `test_document_bounds_ignore_declarations_and_inactive_branches`、两个 prepare 用例 |
| R3 | 已修复 | `71d6129` | `test_unknown_body_branches_are_marked_conditional`、非活跃正文与纯排版条件用例 |
| R6 | 已修复 | `c10b3b8` | journal 恢复用例 + 子进程终止注入用例 + `--recover` |
| §4.2 | 已修复 | `6bea6d9` | manifest `prepare_version` 断言 |

### R1 条件注释后的活跃分支

**复评判断：成立，而且是我上一轮引入的 bug。** `_conditional_bounds` 里写成了 `text.find("\\n", ...)`，查找的是反斜杠加字母 n，不是换行。含注释的 `\iffalse` 扫描直接跑到文件末尾，`\else` 分支的指令不再解析。

**实施**：

- 改为查找真实换行；含注释的 `\iffalse`、`\iftrue` 和嵌套分支都按活跃分支处理。
- `include_not_in_entry` 现在保留目标、正文/导言区归属和来源 include 位置。正文内容从 entry 外被读入时，`content_complete=false`，原因 `include_outside_entry`；导言区依赖仍是警告。
- 复评指出的“只有修正换行还不够”已落实：即使条件扫描再次漏掉分支，正文缺失也不会再被判定完整。

### R2 宏的失效与不确定状态

**复评判断：成立。** 非字面重定义被静默忽略、空字面值被当成未定义、条件内定义泄漏到 `\fi` 之后、`\gdef` 不能覆盖局部值、`\begingroup` 完全没有作用域。

**实施**：

- 宏状态改为“确定字符串（含空串）/ 未定义 / 不确定”三态。非字面重定义、带参数的 `\newcommand`、`\let` 等写入“不确定”，不再沿用旧值。
- 空字面值 `{}` 是确定值，可以解析出 `-frag.tex` 这类空前缀路径。
- 不可判定条件按分支隔离：每个分支有独立作用域，离开条件时只有各分支给出相同确定值才保留该值，否则变为不确定。`\gdef`/`\xdef` 立即覆盖当前含义；`\begingroup`/`\endgroup` 建立作用域。
- 使用不确定宏的路径报告为 `uncertain_path`，保留在 entry 中并使结果 partial，不再读旧文件。

**保留限制**：`\ifcase` 的 `\or` 分支被当成一个不确定区域整体处理（保守降级，不会选错值）；分支隔离不细分分支内的花括号层，分支内定义在离开分支前可见——两者都只会让结果更保守，不会产生“确定但错误”的路径。

### R3 条件正文

**复评判断：成立。** 原实现只把 include 作为条件不确定性，正文分支既可能被当作确定正文，也可能让非活跃正文造成 `uncovered_entry_text` 误报。

**实施**：

- 新增共享的 `condition_regions`：按与指令扫描一致的词法规则给出非活跃区间和不确定区间。
- 覆盖核对使用同一份区间信息：已知非活跃分支从“未覆盖正文”中扣除，不再误报；不可判定条件中的正文计入 `conditional_body_chars`，`structure_complete=false`，原因 `conditional_body`。
- 只含排版命令、正文计数为 0 的条件不改完整性。
- 与不确定区间相交的 block 标记 `conditional=true`；`coverage.conditional_ranges` 同时给出 entry 区间与来源区间，便于定位。
- 正文计数同时修正 `\csname ... \endcsname`：控制序列名不再算作正文，避免把纯排版条件误判为正文。

**保留限制**：block 的阅读文本仍保留 `\ifdefined`/`\else`/`\fi` 等标记（内容在、标记也在）；本轮通过 `conditional` 标记和覆盖原因表达不确定性，没有重写阅读投影。

### R4 子文件 EOF 与注释边界

**复评判断：成立。** 子文件以 `% comment` 结尾、且没有末尾换行时，拼接后的父文件正文被注释吞掉；解析副本只处理了控制词拼接，block 文本又从 entry 原文重算，修好的解析视图被覆盖。

**实施**：

- `EntryCoordinates` 在拼接点按需插入空格或换行：控制词相邻时插空格；子文件当前行有未转义 `%` 时插换行（TeX 在文件结束处结束该行）。
- block 文本改为从解析视图投影，并为每个 block 记录进入 entry 的锚点；entry 原字节和 source map 不变，`validate` 仍逐字节通过。
- `MUST_SURVIVE.` 现在出现在 `document.json`，`complete=true`；回归同时断言 entry 仍保留原始拼接字节。

### R5 文档边界中的定义与非活跃内容

**复评判断：成立。** `document_bounds` 只跳过注释、`\verb` 和字面环境，不跳过声明体和非活跃分支；定义体里的 `\end{document}` 会截断子文档，尾部无法从 entry 找回。

**实施**：文档边界扫描跳过声明体，跟随可判定分支、跳过不可判定条件；与 `_scan` 共用条件识别。

**同时修正的误识别**（复评未列，见 §3）：数学 `\iff`、`\iftoggle` 一类的带参数宏、用户自定义的 `\ifff`、`\newif` 声明不再被当作 `\fi` 终止的条件。缺少匹配 `\fi` 的条件报告 `unclosed_conditional` 并使结构 partial，而不是静默吞掉后文。

### R6 发布中断窗口

**复评判断：成立。** 两次 `os.replace` 不是原子事务；04 与 DESIGN 的“一次目录改名”说法过头。

**实施**：

- 发布改为带 journal 的事务：先写 staging 与 journal（phase=staged），再记录 backup 意图（phase=backup）并执行 `out → backup`，随后 `staging → out`，最后删除 backup 与 journal。
- journal 在 backup 改名**之前**写入，因此“已改名、尚未安装”的窗口可恢复：下一次写入或 `--recover` 会把 backup 恢复为 `out`，并清理 staging/backup/journal。
- 普通异常仍恢复旧目录；`tools/prepare_arxiv.py --recover --out <dir>` 提供显式恢复入口，不需要重新转换。
- 文档改为准确承诺：普通失败保留旧结果；进程在两次改名之间被终止时，目标路径暂时不可用，由后续写入或 `--recover` 恢复。故障注入回归使用子进程 `os._exit(77)`，验证恢复后旧 manifest 逐字节一致。

### §4.2 prepare 规则版本

**复评判断：成立。** 七个整改提交改变了离线转换语义，但产物只记录 `parser_version=0.3.6`，无法区分不同转换规则的输出。

**实施**：新增 `PREPARE_RULE_VERSION="prepare-rules-v2"`，manifest 写入 `prepare_version`，CLI 显式传入。`PARSER_VERSION` 保持不变，因为 `parser.py` 未修改，也不应让无关 workspace 快照因离线工具变化而重建。DESIGN 与中文版说明两者的区别。

## 3. 复评未列、整改中发现的问题

- **数学 `\iff` 被当作条件**：`\iff` 是数学宏。此前 `document_bounds`/`_scan` 把它当 `\if...\fi`，找不到 `\fi` 时跳过到文件末尾，`2012.04068v1` 的 body 因此延伸到 `\end{document}` 之后并产生未覆盖正文。现在排除 `iff`、`\ifthenelse`、`\ifboolexpr`、`\iftoggle` 等宏式条件，并用“后面是否紧跟 `{`”和“是否是已声明宏”辅助判断。
- **用户宏与 `\newif`**：`\newcommand{\ifff}{...}`（quant-ph/0001106）和 `\newif\ifrunningcount`（2607.00262）都会产生以 `if` 开头的名字。前者按已声明宏排除，后者在声明处跳过并对 `\ifXtrue`/`\ifXfalse` 做标记；真正使用 `\ifX ... \fi` 时仍按条件处理。
- **无匹配 `\fi` 的条件**：此前会被当作未闭合条件一直扫描到 EOF，或者静默跳过；现在报告 `unclosed_conditional` 并降级 structure。
- **`\csname` 名不是正文**：覆盖计数把 `\csname urlstyle\endcsname` 里的 `urlstyle` 算成正文，导致 2605.29554 被误判 `conditional_body`；已改为整体跳过。
- **条件区间共享**：非活跃/不确定区间只由 `condition_regions` 一处产生，覆盖核对、block 标记与 coverage 输出共用，避免复评 R3 指出的“两套扫描语义互相矛盾”。

## 4. 复评反例复跑

05 §6 的九个案例在当前代码上的结果：

| 案例 | 05 基线结果 | 当前结果 |
| --- | --- | --- |
| R1 含注释的 `\iffalse` | 缺 `ACTIVE_BODY`，complete | `ACTIVE_BODY` 进入模型，`iffalse_else_branch`，complete |
| R2 动态重定义 | 读 `STALE_ONE`，complete | `uncertain_path`，无 target，partial |
| R2 空值重定义 | 读 `STALE_OLD`，complete | 读 `-frag.tex`（`CORRECT_EMPTY.`），complete |
| R2 条件内定义 | 读 `WRONG_TWO`，complete | `uncertain_path`，partial，不再读错分支 |
| R3 未知正文分支 | 两分支同块，complete | `conditional_body`，partial，block `conditional=true` |
| R3 非活跃正文 | 误报 `uncovered_entry_text` | complete，`uncovered_entry_chars=0` |
| R4 EOF 注释 | 丢 `MUST_SURVIVE`，complete | 保留 `MUST_SURVIVE.`，complete，source_spans 跨 a/main |
| R5 定义内 `\end{document}` | 截断尾部，退出 2 | `Second`/`ACTUAL_TAIL.` 保留，complete |
| R5 非活跃分支 `\end{document}` | 截断尾部，退出 2 | 尾部保留，complete |
| R6 两次改名之间终止 | 目标消失，backup 留存 | 子进程退出 77 后 `--recover` 恢复旧 manifest 并清理遗留 |

## 5. 47 包回归与测试

**口径**：与 03–05 相同，47 个原始包、默认入口识别、未指定入口。脚本仍为一次性探针，未入库。

| 指标 | 04/05 记录 | 本轮 |
| --- | ---: | ---: |
| 退出码 0 / 2 / 1 | 29 / 7 / 11 | 29 / 7 / 11 |
| block 总数 | 12003 | 12003 |
| section 总数 | 1035 | 1035 |
| diagnostics 总数 | 44 | 38 |

诊断减少来自 `\iff`/`\iftoggle`/用户 `if` 宏的误识别；退出码与内容计数没有变化。全部 36 个产出模型都通过 `prepare_source` 内的 source-map 校验（`assembly.validate`），没有 `segment_mismatch`、`entry_tail` 等错误。

**全量测试**：438 项，2 个错误，均为 `integration.cli.test_progress` 的真实 pty 测试报 `out of pty devices`；05 的环境可以打开 pty，本轮本机不能，属于环境差异。`tools/reproduce.py` 仍在同一处中断。

## 6. 仍未完成

- **覆盖计数仍是启发式**（05 §4.1）：只统计 block 之外的连续 ASCII 字母，不覆盖中文、数学、命令参数、字面内容；`conditional_body` 也是同一计数。它现在只是“未覆盖正文”的提示与保守降级依据，不是完整内容金标。05 建议的“已建模/明确排除/保留未解析”分类尚未实现。
- **阅读文本仍保留条件标记**：`conditional=true` 与 `conditional_ranges` 已标记不确定区域，但 `text_projection` 没有删除 `\ifdefined`/`\else`/`\fi`。
- **`\ifcase`/`\or`**：按整个不确定区域处理，不区分具体 `\or` 分支；结论偏保守。
- **自定义条件宏的识别是启发式**：未在使用前声明、也不带 `{` 参数的 `\if...` 宏仍可能被当作无 `\fi` 条件；此时会报 `unclosed_conditional` 并 partial，不会静默选错。
- **人工金标与编译对照**：未建立 47 包内容金标，未执行 TeX/PDF 编译、Docker、Lean 或真实模型。
- **下游评测**：`parser.py` 未改，离线 prepare 尚未接入 workspace 发布；QEC-database machine 副本上的检索评测仍记为未验收。
- **旧链接**（05 §4.3）：02/03 中三处相对链接仍指向重命名前的文件名；本轮没有修改 01–05 的正文。
- **R6 的保证边界**：恢复依赖 journal 与 backup 目录仍然存在；断电、磁盘满和文件系统崩溃未测试。恢复是显式或下一次写入时执行，不是自动守护进程。

## 7. 提交与复现命令

本轮提交（均在 `main`）：

| 提交 | 内容 |
| --- | --- |
| `0f87304` | R1 条件注释换行与正文外部内容降级 |
| `9626b1a` | R4 EOF/注释词法边界与解析视图投影 |
| `6366a87` | R2 宏状态模型 |
| `da93fc3` | R5 文档边界与条件识别 |
| `71d6129` | R3 条件正文区间与覆盖 |
| `c10b3b8` | R6 journal 发布恢复与 `--recover` |
| `6bea6d9` | prepare 规则版本 |

本机执行：

~~~sh
# 全量测试：438 项，2 个 pty 环境错误（与 04 的环境限制相同）
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests

# 05 的九个内容反例：按 05 §6 的脚本在项目根目录运行
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python <05 的 review_probe.py>

# 中断恢复：构造目标目录后注入终止，再恢复
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/prepare_arxiv.py \
  --out /tmp/prepared/paper --recover --json
~~~

47 包对比仍使用一次性探针，基线通过 `git archive` 解出到临时目录后用同一脚本运行；这些数字是回归证据，不是长期评测或人工验收。

## 8. 文档说明

本回复为第 6 份文件，沿用 `0N-...` 的顺序；没有改动 01–05 的正文。02/03 中的三处旧链接按 05 §4.3 的建议应单独修一次，但为保持历次评审原文不变，本轮没有处理。
