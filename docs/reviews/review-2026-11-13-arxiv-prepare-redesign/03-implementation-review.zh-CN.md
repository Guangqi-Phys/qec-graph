# 离线来源归一化实现评估

> 状态：代码审查与复现记录，改进建议尚未实施。日期：2026-11-13。评估基线：1d11dec5fe325ee6e65d9c147173a69636beb15c。

本文记录离线 prepare 实现完成后的审查结果，包括实际复现的问题、影响、代码位置、改进建议及验证范围。本轮审查没有修改仓库实现、原始论文材料或已有转换结果；本次只新增评估文档。测试与转换探测的输出均位于临时目录。

相关材料：

- [最初的离线归一化评估与方案](01-latex-offline-assessment.zh-CN.md)
- [后续设计回复与范围调整](02-reply-to-assessment.zh-CN.md)
- [当前系统设计](../../design/DESIGN.md)
- [测试来源清单](../../../test-sources/arxiv-sources/manifest.json)

## 目录

- [1. 评估结论与范围](#1-评估结论与范围)
- [2. 问题总览](#2-问题总览)
- [3. F1 完整状态的判定过于宽松](#3-f1-完整状态的判定过于宽松)
- [4. F2 路径宏忽略定义顺序和作用范围](#4-f2-路径宏忽略定义顺序和作用范围)
- [5. F3 嵌套 import 丢失目录上下文](#5-f3-嵌套-import-丢失目录上下文)
- [6. F4 逐文件解析丢失主文档上下文](#6-f4-逐文件解析丢失主文档上下文)
- [7. F5 重复引用只保留第一次结构化结果](#7-f5-重复引用只保留第一次结构化结果)
- [8. F6 正则截取会删除或截断正文](#8-f6-正则截取会删除或截断正文)
- [9. F7 输出目录缺少防覆盖保护](#9-f7-输出目录缺少防覆盖保护)
- [10. 实际验证结果](#10-实际验证结果)
- [11. 最小复现脚本](#11-最小复现脚本)
- [12. 建议修复顺序与验收要求](#12-建议修复顺序与验收要求)
- [13. 未验证事项](#13-未验证事项)

## 1. 评估结论与范围

最需要改进的是完整性判定和文件展开的正确性。本轮已经复现了正文遗漏、错误章节被读入、定理结构丢失以及阅读文本被删改等情况，其中多个案例仍返回 `document_complete=true`。

应优先修复这些正确性问题，再扩大支持格式或提高通过率。现有测试通过不能代替内容完整性核对。

评估针对以下两个提交形成的实现：

| 提交 | 内容 |
| --- | --- |
| 06c1e79 | Add offline TeX recognition and document conversion |
| 1d11dec | Document offline source preparation and document/2 |

按当前 DESIGN §5.4，本阶段范围是独立离线工具，生成 entry.tex、source map、document/2、coverage、diagnostics 和 manifest。它尚未接入 workspace 的 stage/validate/publish，也不包含完整书目归一化或资产复制。重新编译和排版等价不是本阶段完成条件。本评估中的问题按这一已声明范围判断。

## 2. 问题总览

本表的 P1 表示建议在把转换结果作为可靠抽取输入之前优先修复，不表示已经造成实际用户数据损失。

| 编号 | 优先级 | 问题 | 已复现的影响 |
| --- | --- | --- | --- |
| F1 | P1 | 完整状态缺少正文覆盖检查 | 文档只有标题、正文没有结构化，仍判完整 |
| F2 | P1 | 路径宏按整文件预扫描 | 前面的引用被后面的重定义改变，读错文件 |
| F3 | P1 | import 上下文未传递 | 子目录正文被根目录同名文件替代 |
| F4 | P1 | 子文件独立解析 | 主文件定义的定理变成普通段落，跨文件父子关系丢失 |
| F5 | P1 | 原始位置只映射到第一次出现 | entry.tex 有两次内容，document.json 只有一次 |
| F6 | P1 | 正则截取环境和文档正文 | 定理开头的分组内容被删除，字面示例导致后文截断 |
| F7 | P1 | 输出直接覆盖已有文件 | 非受管理目录中的 entry.tex 被覆写 |

下文代码行号均对应评估基线，后续修复可能改变行号。

## 3. F1 完整状态的判定过于宽松

**位置**：[prepare.py](../../../qecgraph/source/prepare.py)，第 192–207 行，尤其第 197 行。

目前 structure_complete 的判断是：

~~~python
not parser_errors and bool(document["blocks"])
~~~

它能确认存在块、没有被计入 fatal 的解析错误，但无法确认正文已经完整进入结构化结果。

### 3.1 无扩展名正文片段丢失

主文件包含：

~~~tex
\documentclass{article}
\begin{document}
\section{Intro}
\input{fragment}
\end{document}
~~~

包内有一个无扩展名文件 fragment，内容为：

~~~text
IMPORTANT_EXTENSIONLESS_BODY.
~~~

实际结果：

- entry.tex 正确包含该正文。
- document.json 只有 Intro 标题，没有正文块。
- missing_dependencies 为 1。
- content_complete、structure_complete、document_complete 全为 true。

原因之一是 _parse_origin_files 只接受 .tex，或“没有扩展名且本身包含完整文档声明”的文件。合法的无扩展名正文片段被跳过，覆盖检查没有发现这个差异。

### 3.2 条件分支中的活跃正文被漏掉

以下内容也已复现：

~~~tex
\documentclass{article}
\begin{document}
\section{Intro}
\iffalse
  \input{unused}
\else
  \input{active}
\fi
\end{document}
~~~

active.tex 存在且包含正文，但组装扫描跳过整个 iffalse 至 fi 范围，包括应处理的 else 分支。事件列表为空，结构化输出只剩标题，document_complete 仍为 true。诊断中只有 iffalse_skipped。

相关位置：[assembly.py](../../../qecgraph/source/assembly.py)，第 325–347 行及第 419–422 行。

### 3.3 建议改进与验收

- 对选中正文的来源区间建立覆盖核对，检查哪些内容进入了块、哪些被保留为未解析内容、哪些被明确排除。
- 不以“至少有一个 block”作为结构完整的充分条件。
- 正文依赖未处理、文件被跳过、条件分支无法确定等情况应降级为 partial，并说明原因。
- 无扩展名片段的处理不能要求它自己含 documentclass 和 begin{document}。
- 条件处理应识别受支持的活跃分支；不支持时保留不确定性，不能把整个分支跳过后声称完整。
- 将上述两个案例加入回归测试，直接断言正文存在于 document.json，而不仅检查退出码。

## 4. F2 路径宏忽略定义顺序和作用范围

**位置**：[assembly.py](../../../qecgraph/source/assembly.py)，第 524 行及第 677–689 行。

当前在处理某个文件的所有引用前，先扫描整个文件学习字面宏。后出现的重定义会提前影响前面的引用。

### 4.1 已复现案例

~~~tex
\documentclass{article}
\newcommand{\DIR}{one}
\begin{document}
\input{\DIR/frag}
\renewcommand{\DIR}{two}
\input{\DIR/frag}
\end{document}
~~~

包内：

| 文件 | 内容 |
| --- | --- |
| one/frag.tex | FIRST_BODY. |
| two/frag.tex | SECOND_BODY. |

预期依次读入 FIRST_BODY、SECOND_BODY。实际 entry.tex 两次都是 SECOND_BODY，仍判定完整。

另有两个已复现变体：

- 写在 iffalse 非活跃分支里的 renewcommand 仍会改变后续路径选择。
- 花括号分组内的局部 renewcommand 会泄漏到分组外，使后续引用继续使用局部值。

### 4.2 建议改进与验收

- 按来源中的执行顺序更新宏状态，引用只能使用在该位置已经有效的定义。
- 对支持的分组和条件维护作用范围；无法判断时返回动态或不确定路径。
- 学习宏时复用与指令扫描一致的字面环境、注释和条件边界，避免另一个全文件正则扫描拥有不同语义。
- 新增顺序重定义、局部作用域、非活跃分支定义等回归，断言实际选中的 target，而不仅断言 resolved 数量。

## 5. F3 嵌套 import 丢失目录上下文

**位置**：[assembly.py](../../../qecgraph/source/assembly.py)，第 620–675 行，尤其第 634 行。

主文件：

~~~tex
\documentclass{article}
\begin{document}
\import{chap/}{main.tex}
\end{document}
~~~

包内：

| 文件 | 内容 |
| --- | --- |
| chap/main.tex | `\input{section.tex}` |
| chap/section.tex | CORRECT_CHAPTER. |
| section.tex | UNRELATED_ROOT. |

实际 entry.tex 包含 UNRELATED_ROOT，没有 CORRECT_CHAPTER；两个引用均记录为 resolved，没有相关警告，document_complete 为 true。

根因是递归过程中没有保留 import 的有效目录上下文，普通 input 又优先在包根目录查找。

建议：

- 将有效搜索目录及 import 上下文作为递归状态传入，而不只传当前文件路径。
- 按对应指令的解析语义确定目录；同名文件不应因根目录优先规则被静默选中。
- 对确实无法判定的候选保留歧义。
- 回归必须包含“根目录与子目录同名文件内容不同”的情况，以验证没有替换成错误章节。

## 6. F4 逐文件解析丢失主文档上下文

**位置**：[prepare.py](../../../qecgraph/source/prepare.py)，第 148–189 行，尤其第 166–178 行。

当前逐个 origin file 调用 parse_project，并只保留这一次解析中属于该文件的块。主文件解析时已经正确识别的子文件块被过滤掉，随后子文件被当作独立入口重新解析。

### 6.1 定理变成普通段落

主文件：

~~~tex
\documentclass{article}
\newtheorem{specialthm}{Theorem}
\begin{document}
\input{frag}
\end{document}
~~~

frag.tex：

~~~tex
\begin{specialthm}
\label{thm:one}
IMPORTANT_THEOREM.
\end{specialthm}
~~~

本轮直接比较：

| 调用方式 | 块类型 | 环境 |
| --- | --- | --- |
| 现有 parse_project 从主文件读取 | theorem | specialthm |
| 新 prepare_source 流程 | paragraph | null |

label 仍在，但定理语义边界丢失，document_complete 仍为 true。

### 6.2 跨文件父子关系丢失

主文件中的 theorem 环境若通过 input 引入正文，实测：

- theorem 的 text 仍是原始 input 指令。
- 被读入的正文成为独立 paragraph。
- 该 paragraph 的 parent_key 为 null，没有绑定到 theorem。

### 6.3 建议改进与验收

- 优先考虑在统一上下文中解析组装结果，再通过 source map 还原来源坐标。
- 如果保留逐文件解析，需要显式传递环境声明、宏及父级上下文，并保留每次引用的上下文差异。
- 合并结果不能丢弃主文件解析已正确识别的子文件结构。
- 回归应比较主文档解析和 prepare 的定理类型、label、父子关系，而不只比较章节数和非空 text。

## 7. F5 重复引用只保留第一次结构化结果

**位置**：[assembly.py](../../../qecgraph/source/assembly.py)，第 783–789 行及 merge_blocks 的块生成逻辑。

复现主文件：

~~~tex
\documentclass{article}
\begin{document}
\section{A}
\input{frag}
\section{B}
\input{frag}
\end{document}
~~~

frag.tex 包含 REPEATED_CONTENT。

实际结果：

- entry.tex 中正文出现两次。
- 两个 input 都记录为 resolved。
- document.json 只有第一次正文块，B 节下没有对应正文。
- document_complete 为 true。

map_position 对同一个原始文件位置只返回第一个匹配 segment，块也只从每个原始文件生成一轮，因此不能表示同一内容在 entry 中出现多次的情况。

建议：

- 按每次引用实例建立映射，区分 source location 与 occurrence。
- 一个原始区间可以对应多个 entry 区间，不能用单个位置覆盖这个关系。
- 每次出现的块应有自己的身份、顺序和父级上下文。
- 验收同时检查两次正文、两组 entry 坐标以及 A/B 的章节归属。

## 8. F6 正则截取会删除或截断正文

### 8.1 定理开头的分组被当成参数删除

**位置**：[assembly.py](../../../qecgraph/source/assembly.py)，第 746–756 行，尤其第 750–752 行。

~~~tex
\documentclass{article}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}{IMPORTANT_ASSERTION} rest.\end{theorem}
\end{document}
~~~

实际 theorem.text 只剩 `rest.`，IMPORTANT_ASSERTION 被删除。

原因是环境开头的清理正则无条件允许吞掉一个紧随 begin 的花括号组。对于这里的 theorem，该组是正文分组，不是需要丢弃的环境参数。

建议依据已知环境的参数定义解析，而不是对所有环境统一吞掉一个花括号组。未知环境保留内容，避免把正文当参数删除。

### 8.2 字面示例导致整个子文档后半部分截断

**位置**：[assembly.py](../../../qecgraph/source/assembly.py)，第 453–468 行。

子文档中含有：

~~~tex
\documentclass{article}
\begin{document}
\section{First}
Before.
\begin{verbatim}
\end{document}
\end{verbatim}
\section{Second}
ACTUAL_TAIL.
\end{document}
~~~

该子文档被主文件 input 时，_document_body 通过正则选择第一次 end{document}，把 verbatim 示例中的文本当成真正文档结束。

实测 Second 章节与 ACTUAL_TAIL 都没有进入组装后的正文，结果仍返回 document_complete=true。

建议使用能识别字面环境、宏定义及注释边界的 token 扫描来定位文档范围，并对“选择的范围包含未闭合结构”进行检查。这是内容截取问题，不涉及是否要求生成可编译工程。

## 9. F7 输出目录缺少防覆盖保护

**位置**：[prepare.py](../../../qecgraph/source/prepare.py)，第 240–271 行，尤其第 242–251 行。

write_outputs 对任意已存在目录直接依次写入 entry.tex、source-map.json、document.json 等文件。

本轮在临时目录中预先放入内容为 USER_ORIGINAL_CANARY 的 entry.tex，再调用 write_outputs。原文件直接被覆盖，没有管理标记检查或拒绝覆盖。

这意味着输出目录误指向来源目录或其他用户目录时，同名文件可能被破坏。连续直接写多个文件也没有整组提交边界；写入中断或中途失败可能留下不一致产物。覆盖行为已实际复现；中途失败的恢复尚未做故障注入。

建议：

- 拒绝覆盖非受管理的非空目录。
- 检查输出与来源目录是否重叠，以及输出路径是否通过符号链接指向其他位置。
- 在临时目录生成全部产物，完成内容、source map 与 manifest 校验后整体提交。
- 失败保留上一份完整结果，不让旧 manifest 配上部分新文件。
- 增加非受管理目录、来源目录误用、符号链接和写入中断的回归。

## 10. 实际验证结果

### 10.1 代码与环境

| 项目 | 值 |
| --- | --- |
| 评估代码 | 1d11dec5fe325ee6e65d9c147173a69636beb15c |
| Python | 3.15.2，项目 .venv |
| pylatexenc | 2.10 |
| jsonschema | 4.26.0 |
| SQLite | 3.54.1，FTS5 可用 |
| 平台记录 | macOS-27.2.1-arm64-arm-64bit-Mach-O |
| 临时评估目录 | /tmp/qec-offline-review-bsp1e9nd |
| 端到端示例 release | f1a0588093e361318ddc6633e7cd0bb3dd3535b013d8002cc33b5cebb65729b4 |

本轮未调用真实 AI provider，也未执行 TeX 编译。

### 10.2 现有测试与端到端复现

执行：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reproduce.py \
  --out /tmp/qec-offline-review-bsp1e9nd/reproduce
~~~

该脚本内部运行：

~~~sh
.venv/bin/python -m unittest discover -s tests -v
~~~

结果：

- 392 项测试通过。
- 端到端复现通过，包括示例切割、工作区发布、校验、搜索与上下文读取。
- 本轮未出现先前报告中的 pty 环境错误。
- 这些检查不覆盖本报告全部反例；反例说明需要补充面向内容的回归。

### 10.3 全量原始包探测

对 test-sources 中的 47 个原始 TeX 包逐个执行新 CLI，不手工指定入口。PDF 对照不纳入该分母。

每个包使用以下命令形式，所有输出都写到临时目录：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/prepare_arxiv.py \
  "<original-package>" \
  --out "/tmp/qec-offline-review-bsp1e9nd/all-packages/<case-id>" \
  --json
~~~

探测使用三个并发子进程，每个包设 60 秒超时。本轮没有超时，总耗时约 8.33 秒；这是本机一次工具探测，不是稳定吞吐量或内容质量保证。

| CLI 结果 | 数量 | 占 47 个包的比例 |
| --- | ---: | ---: |
| 退出码 0，程序判定 document_complete | 30 | 63.8% |
| 退出码 2，部分完成 | 6 | 12.8% |
| 退出码 1，失败 | 11 | 23.4% |

11 个失败中：

| 原因 | 数量 |
| --- | ---: |
| 多入口，要求显式指定 | 8 |
| 编码问题 | 1 |
| 旧 tar 被现有 reader 策略拒绝 | 2 |

因此，当前不能表述为“所有样本已经自动统一完成”。30 个退出码 0 也只是程序判定；本报告中的反例证明该判定尚不能作为内容完整性验收。

6 个部分完成的包是：0903.0566v1、2201.08309v1、2511.01062v1、2511.01062v2、2605.29137v1 和 2607.29382v2。它们均被程序判为 content_complete，但 structure_complete 为 false。

### 10.4 逐包记录

下表只记录本轮 CLI 的实际输出。块数和章节数不是独立金标，不能据其非零推断内容完整。

| 来源包 | 退出码 | 识别入口 | 块数 | 章节数 |
| --- | ---: | --- | ---: | ---: |
| 0903.0566v1 | 2 | main.tex | 132 | 6 |
| 1208.2317v1 | 0 | ft-def25.tex | 53 | 0 |
| 1302.3428v1 | 0 | QEC04_springer.tex | 168 | 15 |
| 1804.03719v1 | 1 | — | — | — |
| 1907.02554v1 | 0 | ms.tex | 47 | 7 |
| 1907.11157v1 | 0 | cp_review_arxiv.tex | 269 | 37 |
| 2009.07851v3 | 0 | XZZX.tex | 126 | 17 |
| 2012.04068v1 | 0 | main.tex | 307 | 21 |
| 2012.09271v1 | 0 | balanced_product_codes.tex | 553 | 61 |
| 2102.06132v1 | 0 | main.tex | 229 | 24 |
| 2103.02202v1 | 0 | main.tex | 192 | 33 |
| 2103.06309v1 | 1 | — | — | — |
| 2104.01180v1 | 0 | main.tex | 350 | 17 |
| 2111.05176v1 | 1 | — | — | — |
| 2201.08309v1 | 2 | main.tex | 1366 | 52 |
| 2202.13641v1 | 0 | main.tex | 278 | 30 |
| 2207.06431v1 | 0 | main.tex | 343 | 43 |
| 2209.01119v1 | 0 | template.tex | 313 | 32 |
| 2209.05640v1 | 1 | — | — | — |
| 2303.15933v1 | 0 | main.tex | 213 | 39 |
| 2308.02321v1 | 1 | — | — | — |
| 2308.07915v1 | 1 | — | — | — |
| 2308.07915v2 | 1 | — | — | — |
| 2408.13687v1 | 1 | — | — | — |
| 2410.02885v1 | 0 | main.tex | 159 | 23 |
| 2411.11822v1 | 0 | outline.tex | 259 | 11 |
| 2412.14256v1 | 1 | — | — | — |
| 2509.03613v1 | 0 | main.tex | 189 | 8 |
| 2510.06495v2 | 0 | main.tex | 501 | 26 |
| 2511.01062v1 | 2 | main.tex | 208 | 20 |
| 2511.01062v2 | 2 | main.tex | 210 | 21 |
| 2512.07737v1 | 0 | main.tex | 207 | 52 |
| 2605.29137v1 | 2 | main.tex | 1940 | 149 |
| 2605.29554v1 | 0 | swemed1_concentration_transport_springer.tex | 303 | 28 |
| 2605.29774v1 | 0 | qdft.tex | 165 | 22 |
| 2605.30298v1 | 0 | cohomology-moduli-stack-real-bundles.tex | 183 | 10 |
| 2606.00045v1 | 0 | main__1_.tex | 93 | 9 |
| 2606.30447v1 | 0 | StokesSpectralQuantum.tex | 322 | 31 |
| 2607.00222v1 | 0 | main.tex | 296 | 24 |
| 2607.00262v1 | 0 | main.tex | 284 | 25 |
| 2607.29382v2 | 2 | main.tex | 573 | 34 |
| 2609.22572v1 | 0 | arxiv.tex | 197 | 29 |
| hep-th/9407087v1 | 1 | — | — | — |
| quant-ph/0001106v1 | 0 | FarhiAdiabatic.tex | 133 | 20 |
| quant-ph/0110143v1 | 0 | toric.tex | 540 | 42 |
| quant-ph/9604034v1 | 1 | — | — | — |
| quant-ph/9605021v1 | 0 | main.tex | 152 | 4 |

### 10.5 证据文件

临时目录下保留：

| 文件 | 内容 |
| --- | --- |
| all-packages.json | 47 个原始包的退出码、耗时、stderr 与 CLI summary |
| all-packages/ | 成功或部分完成包生成的离线产物 |
| reproduce/results.json | 392 项测试和端到端复现的汇总 |
| reproduce/unit_tests.stderr.txt | 单元测试执行日志 |

临时目录在 macOS 上对应 /private/tmp/qec-offline-review-bsp1e9nd，可能被系统清理。本文件保留关键数字、版本、命令与反例，不能假定临时证据永久存在。

## 11. 最小复现脚本

以下脚本整理了审查中实际使用的最小案例，可从项目根目录交给项目解释器运行。所有来源都在内存中构造；prepare 内部使用临时树；覆盖探测也只操作新建的临时目录。

这是一份诊断脚本，不是新增到项目中的正式测试。修复后应将相应预期转为持久的回归断言。

~~~python
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from qecgraph.source.package import SourceTree
from qecgraph.source.prepare import prepare_source, write_outputs

cases = {
    "F1_extensionless_fragment": {
        "main.tex": (
            r"\documentclass{article}\begin{document}"
            r"\section{Intro}\input{fragment}\end{document}"
        ),
        "fragment": "IMPORTANT_EXTENSIONLESS_BODY.\n",
    },
    "F1_false_else": {
        "main.tex": (
            r"\documentclass{article}\begin{document}\section{Intro}"
            r"\iffalse\input{unused}\else\input{active}\fi\end{document}"
        ),
        "unused.tex": "NOT_ACTIVE.\n",
        "active.tex": "ACTIVE_BODY.\n",
    },
    "F2_path_redefinition": {
        "main.tex": (
            r"\documentclass{article}\newcommand{\DIR}{one}"
            r"\begin{document}\input{\DIR/frag}"
            r"\renewcommand{\DIR}{two}\input{\DIR/frag}\end{document}"
        ),
        "one/frag.tex": "FIRST_BODY.\n",
        "two/frag.tex": "SECOND_BODY.\n",
    },
    "F3_import_context": {
        "main.tex": (
            r"\documentclass{article}\begin{document}"
            r"\import{chap/}{main.tex}\end{document}"
        ),
        "chap/main.tex": r"\input{section.tex}",
        "chap/section.tex": "CORRECT_CHAPTER.\n",
        "section.tex": "UNRELATED_ROOT.\n",
    },
    "F4_parent_declaration": {
        "main.tex": (
            r"\documentclass{article}\newtheorem{specialthm}{Theorem}"
            r"\begin{document}\input{frag}\end{document}"
        ),
        "frag.tex": (
            r"\begin{specialthm}\label{thm:one}"
            r"IMPORTANT_THEOREM.\end{specialthm}"
        ),
    },
    "F5_repeated_include": {
        "main.tex": (
            r"\documentclass{article}\begin{document}"
            r"\section{A}\input{frag}\section{B}\input{frag}\end{document}"
        ),
        "frag.tex": "REPEATED_CONTENT.\n",
    },
    "F6_initial_group": {
        "main.tex": (
            r"\documentclass{article}\newtheorem{theorem}{Theorem}"
            r"\begin{document}\begin{theorem}"
            r"{IMPORTANT_ASSERTION} rest.\end{theorem}\end{document}"
        ),
    },
    "F6_literal_document_end": {
        "main.tex": (
            r"\documentclass{article}\begin{document}"
            r"\input{supp}\end{document}"
        ),
        "supp.tex": "\n".join([
            r"\documentclass{article}",
            r"\begin{document}",
            r"\section{First}",
            "Before.",
            r"\begin{verbatim}",
            r"\end{document}",
            r"\end{verbatim}",
            r"\section{Second}",
            "ACTUAL_TAIL.",
            r"\end{document}",
            "",
        ]),
    },
}

for name, files in cases.items():
    tree = SourceTree(
        "review",
        {path: text.encode("utf-8") for path, text in files.items()},
    )
    result = prepare_source(tree, "main.tex")
    print(json.dumps({
        "case": name,
        "coverage": result.coverage,
        "entry": result.assembly.text,
        "diagnostics": result.diagnostics,
        "blocks": [
            {
                key: block.get(key)
                for key in (
                    "kind", "environment", "text", "parent_key",
                    "source", "entry",
                )
            }
            for block in result.document["blocks"]
        ],
    }, ensure_ascii=False))

with TemporaryDirectory(prefix="qec-review-output-") as directory:
    out = Path(directory)
    existing = out / "entry.tex"
    existing.write_text("USER_ORIGINAL_CANARY", encoding="utf-8")
    tree = SourceTree("review", {
        "main.tex": (
            rb"\documentclass{article}\begin{document}"
            rb"New text.\end{document}"
        ),
    })
    write_outputs(prepare_source(tree), out)
    print(json.dumps({
        "case": "F7_unmanaged_output",
        "overwritten": (
            existing.read_text(encoding="utf-8") != "USER_ORIGINAL_CANARY"
        ),
    }))
~~~

在评估基线上，前八个案例均返回 document_complete=true，但输出存在对应章节描述的问题；最后一个覆盖探测返回 overwritten=true。

## 12. 建议修复顺序与验收要求

建议按以下顺序推进：

1. 先修 F7，保证后续批量实验不会覆盖非受管理文件。
2. 修 F2、F3，确保被展开的是正确来源内容。
3. 修 F4、F5、F6，确保结构、重复出现和正文范围得到保留。
4. 强化 F1 的覆盖判定，使剩余不支持情况可靠降级为 partial。
5. 将本报告的反例纳入回归，再运行全部 47 个原始包及独立的新样本。

每项修复应有能直接检查内容的断言：

| 范围 | 必须验证 |
| --- | --- |
| 路径选择 | 实际 target 正确，非活跃或后续定义不能污染当前引用 |
| 文档结构 | 定理、证明及跨文件父子关系保留 |
| 重复引用 | 每次出现都有块、entry 坐标和正确上下文 |
| 正文提取 | 首个分组不被删除，字面示例不截断后文 |
| 完整状态 | 存在未处理正文时不能标 complete |
| 输出管理 | 非受管理文件不被覆盖，失败不留下混合版本 |
| 全量评测 | 固定代码与样本版本，逐包记录失败，不只挑选成功入口 |

本报告的 47 包探测使用原始包和默认入口识别，与手工指定入口、从已解压目录开始的试验口径不同，不能混合计算通过率。若采用人工入口配置，应在报告中单独列明。

对已经标 complete 的结果，仍需独立抽查正文、补充材料、结构和来源映射。退出码、块数、章节数与 source-map 字节校验分别证明不同事项，不能相互替代。

## 13. 未验证事项

- 未实施本报告中的任何代码修复。
- 未对全部 47 个包建立独立人工内容金标。
- 未对全部公式、书目或资产执行完整性验收。
- 未执行写入中断等故障注入；F7 的直接覆盖行为已实际复现。
- 未执行 TeX/PDF 编译、Docker 或 Lean。
- 未调用真实 AI provider。
- 未执行 QEC-database machine 副本上的下游检索评测；本轮没有导入或解析代码修改。
- 未将本轮临时探针宣称为科学验收或长期维护的评测工具。

本轮仓库中原有的文档修改与评审目录整理保持原状；没有替用户回滚或提交这些修改。
