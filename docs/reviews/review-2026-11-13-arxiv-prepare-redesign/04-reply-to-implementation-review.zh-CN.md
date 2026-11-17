# 离线 prepare 整改回复

> 对应 [离线来源归一化实现评估](03-implementation-review.zh-CN.md)。整改基线 `1d11dec5fe325ee6e65d9c147173a69636beb15c`，完成提交 `2b4b0939360a66fbcf5db1f70b8f9d72b72177d4`（已推送到 `origin/main`）。状态：F1–F7 已实施，逐项有直接检查内容的回归；没有独立人工金标的部分在 §6 保留为未验收。

本目录的文档链：

1. [LaTeX 包离线归一化评估与实施方案](01-latex-offline-assessment.zh-CN.md)
2. [离线归一化设计回复](02-reply-to-assessment.zh-CN.md)
3. [离线来源归一化实现评估](03-implementation-review.zh-CN.md)
4. 本文件，对第 3 份的整改回复

本次只修改实现、测试和设计文档；没有改动第 1–3 份文件的内容，没有修改原始论文包、已有转换结果或 `human/`。报告 §3–§9 与 §11 的最小案例已全部在本机复跑，结果见 §4。除特别注明外，本文数字来自本机一次固定基线复现，不是长期评测工具，也不替代人工内容金标。

## 目录

- [1. 结论](#1-结论)
- [2. 逐项回应 F1–F7](#2-逐项回应-f1f7)
- [3. 报告之外的补充发现](#3-报告之外的补充发现)
- [4. 最小案例复跑](#4-最小案例复跑)
- [5. 47 包语料回归](#5-47-包语料回归)
- [6. 仍未验证](#6-仍未验证)
- [7. 已知遗留与后续项](#7-已知遗留与后续项)
- [8. 提交与复现命令](#8-提交与复现命令)
- [9. 文档说明](#9-文档说明)

## 1. 结论

- 报告 F1–F7 全部复现，没有发现误报。七个问题都已修复，每项至少有一个直接检查输出内容（而不只是退出码或计数）的回归。
- 修复顺序按“静默产生错误内容或破坏用户文件的代价”调整为：F6.2、F3、F7、F6.1、F4+F5、F2、F1。报告把 F7 排第一，在“先防止数据破坏”上是对的；实际实施把同样廉价、但会截断整节正文的 F6.2 放在最前，F7 紧随。
- 47 包语料退出码从 30/6/11 变为 29/7/11；block 总数 11853 → 12003，section 总数 1022 → 1035。唯一新增的 partial 是条件分支被明确标为不确定的结果，不是新增失败。
- 实施中发现两个报告未列、但同样会破坏“内容完整”判定的问题：引入拼接把控制词和正文粘成一个词（§3.1），以及单次解析把一处畸形内容扩散到整篇（§3.2）。两者都已处理并写入设计。
- 未建立 47 包的人工内容金标，未执行 TeX/PDF 编译对照，未调用真实模型；这些仍是 §6 的未验收项。`qecgraph/source/parser.py` 未改动，离线 prepare 仍未接入 workspace 发布，因此没有在 `~/Workspace/QEC-database` 上做下游检索评测，按仓库约定记为未验收。

## 2. 逐项回应 F1–F7

| 编号 | 结论 | 主要提交 | 回归 |
| --- | --- | --- | --- |
| F6.2 | 已修复 | `efcc08f` | `test_literal_document_end_does_not_truncate_included_tail`（assembly 与 prepare 两级） |
| F3 | 已修复 | `45b9e42` | `test_import_context_applies_to_nested_inputs`、`test_subimport_resolves_relative_to_the_imported_directory`、`test_import_keeps_the_imported_directory_context` |
| F7 | 已修复 | `c320151` | 4 个 `write_outputs` 用例 |
| F6.1 | 已修复 | `d28ca7c` | `test_theorem_body_group_is_not_stripped_as_an_environment_argument` |
| F4、F5 | 已修复 | `a1f9580` | `test_theorem_declared_in_the_entry_applies_to_an_included_file`、`test_included_theorem_body_stays_inside_its_theorem`、`test_repeated_include_yields_one_block_per_occurrence` |
| F2 | 已修复 | `4bd8353` | 4 个 assembly 用例 + `test_path_macro_redefinition_keeps_source_order` |
| F1 | 已修复 | `2b4b093` | `test_extensionless_fragment_reaches_the_document_model`、`test_iffalse_else_branch_is_assembled`、`test_include_inside_an_undecidable_conditional_is_partial`、`test_uncovered_body_prose_breaks_structure_completeness` |

### F1 完整状态的判定过于宽松

**报告判断：成立。** `not parser_errors and bool(document["blocks"])` 确实只能证明“有块、没有 fatal 解析错误”，不能证明正文进入了结构化结果。

**实施**（[prepare.py](../../../qecgraph/source/prepare.py) 的 `_coverage`、`_uncovered_entry_prose`，[assembly.py](../../../qecgraph/source/assembly.py) 的 `_scan`）：

- 新增正文覆盖核对：统计正文区间内没有被任何 block 的 `entry` 区间覆盖的连续 ASCII 字母（至少 2 个字母）总长度，记为 `uncovered_entry_chars`。注释、控制词及其参数、字面环境（`verbatim`、`lstlisting`、`comment` 等）不计入。大于 0 时 `structure_complete=false`，原因记为 `uncovered_entry_text`。
- `bool(blocks)` 保留为必要条件，另外空文档会得到显式原因 `no_blocks`。
- 无扩展名正文片段：改为解析组装后的 entry 后，片段已在 entry 内，不再要求它自己带 `\documentclass`。`missing_dependencies` 也降为 0。
- `\iffalse ... \else ... \fi`：扫描器现在识别静态可判定的活跃分支；`\iftrue` 同理，非活跃分支的指令不再解析。
- 无法判定的条件（`\ifdefined`、`\ifx`、`\ifnum` 等）：两个分支都保留并解析，但其中解析出的 include 记为 `conditional_directives`，`structure_complete=false`。这是报告 F1.3“无法判断时降级为 partial”的落地。
- `\iffalse` 无 `\else` 时仍记录 `iffalse_skipped`，但不影响完整性——被跳过的分支本来就不活跃。

**与报告建议的微调**：

- 报告建议“正文依赖未处理、文件被跳过、条件分支无法确定等都降级”。正文依赖未处理已经通过 `content_complete=false` 降级；文件被跳过会表现为解析错误或缺失依赖，没有另加重复原因。`missing_dependencies` 本身仍不直接降级，因为 preamble 缺失不是正文缺失，这与 DESIGN §5.4 一致。
- 条件分支的 downgrade 只覆盖“条件内出现 include”的情况，避免把只含宏定义或排版的普通 `\ifdefined` 全部打成 partial。

### F2 路径宏忽略定义顺序和作用范围

**报告判断：成立。** 原实现先整文件预扫描宏，再处理指令；`renewcommand` 会提前影响前面的引用，分组内的定义会泄漏，`\iffalse` 里的定义仍会被学习。

**实施**（[assembly.py](../../../qecgraph/source/assembly.py) 的 `_scan` 与宏作用域状态）：

- 扫描器改为输出有序的“作用域事件、宏定义、指令”事件流；解析指令时只使用该位置可见的宏状态。
- 花括号建立作用域；`\gdef`/`\xdef` 写入根作用域；`\providecommand` 仅在名称未定义时生效；`\iffalse` 非活跃分支中的定义不学习。
- 定义出现在引用之后、或定义所在分组已关闭时，不再展开，指令保持 `dynamic_path`，`content_complete=false`。

**验证**：顺序重定义现在实际选中 `one/frag.tex` 再 `two/frag.tex`；分组内局部定义只影响组内；非活跃分支的定义不再改变后续路径；先使用后定义会降级为 partial。

**保留限制**：无法判定的条件分支内的宏定义仍会被学习（两个分支都扫描，后出现的定义生效）。这项修改前后 47 包的退出码与诊断没有变化，未观察到依赖该行为的包；但它与“不支持时保留不确定性”不完全一致，列入 §7。

### F3 嵌套 import 丢失目录上下文

**报告判断：成立。** 根因是两个：递归时没有携带 import 建立的目录；普通 `\input` 的候选顺序是根目录优先。

**实施**：`_assemble_range` 增加 `context` 参数。多参数 include 解析出的目标目录成为其内容内引用的首选搜索目录；普通 `\input`/`\include` 继承外层上下文，无 import 上下文时仍保持根目录优先，因此不改变旧行为；`\subfile` 也继承上下文（报告未要求，但同属该问题）。嵌套 `\subimport` 继续相对当前 import 目录解析。

**验证**：报告的同名文件案例现在选中 `chap/section.tex`，entry 与 document.json 都只有 `CORRECT_CHAPTER.`，不再静默选中根目录同名文件。

### F4 逐文件解析丢失主文档上下文

**报告判断：成立。** 报告建议优先“在统一上下文中解析组装结果，再通过 source map 还原坐标”。本轮按这个方向实现，正常路径不再逐文件解析。

**实施**（[prepare.py](../../../qecgraph/source/prepare.py) 的 `_parse_entry`、[assembly.py](../../../qecgraph/source/assembly.py) 的 `merge_blocks`）：

- 把组装后的 entry 写入临时目录，作为单个文档解析一次；entry 的 preamble 声明、`\newtheorem`、`\newenvironment` 对全部被引入片段生效。
- 每个 block 的 entry 区间通过 source map 投影回原始文件：`source` 锚定 block 首个非空白字符；`source_spans` 按 entry 顺序列出该 block 覆盖的每个来源区间；`spans_include` 标记跨越 include 边界的 block。
- 单个 block 跨多个来源文件时，`source` 取锚点区间，完整来源在 `source_spans` 中，不再把 `\input{...}` 当成 theorem 正文。

**验证**：主文件声明的 `specialthm` 在 included 文件中仍是 `theorem/specialthm`；跨文件 theorem 的正文成为该 theorem 的 `text`，不再是孤立的兄弟段落。

**补充**：常规路径没有保留逐文件解析。替代路径是按顶层 include 分块重解析，只在畸形 entry 上启用，见 §3.2。

### F5 重复引用只保留第一次结构化结果

**报告判断：成立。** 原 `map_position` 对同一来源位置只返回第一个 segment，block 也只从每个来源文件生成一轮。

**实施**：单次 entry 解析后，同一来源的每次出现各自产生一个 block，拥有独立的 entry 区间、顺序和 section 归属；`source` 仍指向同一来源区间（这是事实），区别体现在 `entry` 与 `section_id`。

**表示选择**：没有引入 occurrence id。当前用“`source` 锚点 + `source_spans` + `entry` 区间”表达一次出现，`document/2` 的 schema 字段在 DESIGN §5.4 中同步更新。如果下游需要稳定的出现身份（例如逐次引用审核），再增加显式 `occurrence` 字段即可，不需要改变现有语义。

**验证**：报告案例中 entry 两次 `REPEATED_CONTENT.`，document.json 两个 paragraph，`source` 相同、`entry` 不同，section 分别为 A、B。

### F6 正则截取会删除或截断正文

**F6.1 已修复**：`_block_text` 不再对所有环境统一吞掉首个花括号组；只对已知接受可选标题/位置参数的 block kind（theorem 类、figure/table/algorithm 等）剥离 `[...]`，未知环境保留 `\begin{...}` 之后的全部内容。回归断言 `IMPORTANT_ASSERTION` 仍在 text 中，同时 `\begin{theorem}[Named]` 的标题仍被剥离。

**F6.2 已修复**：文档边界改用与指令扫描一致的扫描器，跳过注释、`\verb`/`\lstinline` 和字面环境，verbatim 中的 `\end{document}` 不再结束正文。回归同时检查 entry 与 document.json 两级：`Second` section 与 `ACTUAL_TAIL.` 都在。

**补充**：修复 F6.2 时发现拼接本身也能制造截断，见 §3.1。

### F7 输出目录缺少防覆盖保护

**报告判断：成立。** 原 `write_outputs` 对任意已存在目录直接写六个文件。

**实施**（[prepare.py](../../../qecgraph/source/prepare.py) 的 `write_outputs`、[prepare_arxiv.py](../../../tools/prepare_arxiv.py)）：

- 非空且没有 prepare manifest 的目录默认拒绝；`--overwrite` 是显式例外，并且会整体替换该目录（包括无关文件），已在 `tools/README.md` 与中文版写明。
- 输出目录是来源目录、来源位于输出目录内、输出路径是符号链接时都拒绝。
- 全部产物先在目标同级的 staging 目录生成，再用一次目录改名切换；失败时保留上一份完整结果并清理 staging。
- 增加回归：拒绝非受管理目录（canary 不变）、受管理目录整体替换且不留下旧文件、来源重叠与 symlink 拒绝、注入写入失败后旧产物逐字节不变。

## 3. 报告之外的补充发现

### 3.1 引入拼接会粘住控制词

字节级拼接把 `\input{x}` 替换成 x 的内容，如果前一个字节是控制词的字母、而内容又以字母开头，两个 token 会粘成一个。例如报告 F1.2 的案例组装后是：

~~~tex
\iffalse\input{unused}\elseACTIVE_BODY.
\fi
~~~

`\else` 与 `ACTIVE_BODY` 之间没有分隔，TeX 词法上会读成 `\elseACTIVE`，`\else` 消失。基线在逐文件解析时没有暴露这个问题；单次 entry 解析会直接受它影响。

**处理**：entry 的原始字节和 source map 保持不变；只在“解析副本”里于这类拼接点插入一个空格，并维护 parse ↔ entry 的字符偏移映射，block 与诊断坐标在映射后仍然精确落在 entry 上。`entry.tex` 仍是原字节。

**局限**：47 包没有出现拼接（真实来源通常在指令前有空白），报告的最小案例本身会命中；因此回归用 F1.2 的形态覆盖。

### 3.2 单次解析的错误耦合与分块兜底

统一解析的代价是一处畸形内容会放弃整篇结构。开发中 `arXiv-2201.08309v1` 在一次花括号不匹配后，section 从 52 掉到 14，block 从 1366 掉到 795；这些内容仍在 entry.tex 里，但没有进入 document.json。

**处理**：entry 解析出现 `latex_parse_error` 且允许恢复时，按顶层已解析 include 的位置把 entry 分块，每块前面附上 entry preamble 后重新解析，再回映到 entry 坐标；取 block 更多的结果。`arXiv-2201.08309v1` 最终为 52 section、1372 block，与基线 52、1366 基本一致。解析错误仍会报告，结构仍是 partial。

**代价**：诊断数量上升（该包 8 → 19），因为每个分块各自报告自己的错误。这是“报告限制”而不是静默吞掉，未做进一步去重。

### 3.3 preamble 声明不再伪装成正文 block

基线逐文件解析时，被 `\input` 的完整文档的 preamble、宏文件、`.bbl` 内容会作为独立文件被解析成 paragraph block，出现在 document.json 里。单次 entry 解析后，preamble 不属于正文，这些 block 消失；文本仍在 `entry.tex` 中，没有丢失。语料里 `arXiv-2607.00262v1` 的 −55 个 block 主要来自这一点，属于改进而不是回退。

### 3.4 判定语义写入设计

`docs/design/DESIGN.md` 与中文版同步补充了：单次 entry 解析与 `source_spans`、路径宏的顺序与作用域、可判定/不可判定条件、`content_complete`/`structure_complete`/`document_complete` 的精确定义与 `uncovered_entry_chars`、`conditional_directives`、输出目录的受管理语义。文档与实现同一次提交落地，不留下“代码先行、文档滞后”的窗口。

## 4. 最小案例复跑

报告 §3–§9 与 §11 的案例在当前代码上复跑（F7 部分改为捕获异常并检查 canary）：

| 案例 | 当前结果 |
| --- | --- |
| F1 无扩展名片段 | document.json 出现 `IMPORTANT_EXTENSIONLESS_BODY.`，`missing_dependencies=0`，complete |
| F1 `\iffalse`/`\else` | entry 与 block 含 `ACTIVE_BODY.`，不含 `NOT_ACTIVE.`；block 覆盖该分支后不再报未覆盖正文 |
| F2 顺序重定义 | 依次选中 `one/frag.tex`、`two/frag.tex` |
| F2 非活跃分支定义 | 两次都选中 `one/frag.tex`，不再被 `\iffalse` 内的 `\renewcommand` 改变 |
| F2 分组内定义 | 组内 `two/frag.tex`，组外 `one/frag.tex` |
| F3 import 上下文 | entry 只有 `CORRECT_CHAPTER.`，无 `UNRELATED_ROOT.` |
| F4 定理声明 | `kind=theorem`、`environment=specialthm`、label 保留 |
| F4 跨文件正文 | 单个 theorem block，`text` 为正文，`source_spans` 为 main/body/main 三段 |
| F5 重复引用 | 两个 paragraph，section 分别为 A、B，`source` 相同、`entry` 不同 |
| F6.1 首个分组 | text 含 `IMPORTANT_ASSERTION`；可选标题 `[Named]` 仍被剥离 |
| F6.2 字面 `\end{document}` | section 为 First、Second，block 含 `ACTUAL_TAIL.` |
| F7 覆盖非受管理目录 | 抛 `ValueError`，canary 逐字节不变，无 staging 残留 |

报告 §12 的六项验收都有对应位置：路径选择（F3、F2）、文档结构（F4）、重复引用（F5）、正文提取（F6.1、F6.2）、完整状态（F1）、输出管理（F7）见 §2 的回归列；全量评测见 §5，口径限制见 §6。

## 5. 47 包语料回归

**口径**：与报告 §10.3 相同，47 个原始包、默认入口识别、固定代码版本，未手工指定入口。脚本为一次性探针，未入库，因此这些数字是回归证据，不是长期评测或人工金标。

| 指标 | 基线 `1d11dec` | 当前 `2b4b093` |
| --- | ---: | ---: |
| 退出码 0 / 2 / 1 | 30 / 6 / 11 | 29 / 7 / 11 |
| block 总数 | 11853 | 12003 |
| section 总数 | 1022 | 1035 |

发生计数变化的包：

| 来源包 | 退出码 | block | section | 说明 |
| --- | --- | ---: | ---: | --- |
| 2201.08309v1 | 2 → 2 | 1366 → 1372 | 52 → 52 | 分块兜底恢复结构；诊断 8 → 19 |
| 2411.11822v1 | 0 → 2 | 259 → 249 | 11 → 11 | 条件分支内的 include 被标为不确定 |
| 2605.29137v1 | 2 → 2 | 1940 → 2048 | 149 → 162 | 统一上下文识别出更多章节与块 |
| 1907.02554v1 | 0 → 0 | 47 → 88 | 7 → 7 | 原先逐文件解析丢掉的正文进入模型 |
| 2009.07851v3 | 0 → 0 | 126 → 209 | 17 → 17 | 同上 |
| 2607.00262v1 | 0 → 0 | 284 → 229 | 25 → 25 | preamble 声明不再作为正文 block |
| 2512.07737v1 | 0 → 0 | 207 → 202 | 52 → 52 | 段落不再按 include 边界拆分 |
| 1302.3428v1 等 | 0 → 0 | 略减 | 不变 | 同上，属合并策略变化 |

**内容核对**：把每包的 block 文本规范化后逐条检查旧文本是否仍出现在新模型里。唯一的“消失”是 preamble 声明（如 `\usepackage`、`\renewbibmacro`）和 `\input{*.tikz}` 的占位文本；前者仍在 `entry.tex`，后者已被展开为 TikZ 内容。没有发现正文丢失。

**新增 partial 的解释**：`arXiv-2411.11822v1` 用 `\ifx\compilefullpaper\undefined` 分支组织不同编译模式，include 位于条件内。两个分支都被组装进 entry，无法确定哪个是活跃分支；报告 F1.3 要求这种情况不能声称完整。这不是新失败，而是把原先静默的“完整”改成显式 partial。

## 6. 仍未验证

- 未对 47 包建立独立人工内容金标；block/section 计数只用于回归，不证明内容正确。
- 未执行 TeX/PDF 编译对照；本阶段不要求可编译工程。
- 未执行 Docker、Lean 或真实模型调用。
- 未在 `~/Workspace/QEC-database` 的 machine 副本上运行下游检索评测：`parser.py` 未改动，`assembly.py`/`merge_blocks` 只被离线 prepare 使用，prepare 仍未接入 workspace 的 stage/validate/publish。按仓库约定，下游检索质量仍记为未验收，而不是“无影响即通过”。
- 未做写入中断（kill -9）、磁盘满等真实故障注入；只通过注入 `_write_artifacts` 失败验证了 staging 清理与旧结果保留。
- 全量测试在 414 项中有 2 个错误，都是 `integration.cli.test_progress` 的真实 pty 测试报 `out of pty devices`；基线同样失败，属本机环境限制。`tools/reproduce.py` 也只在这里中断。

## 7. 已知遗留与后续项

1. **不可判定条件内的宏定义仍会学习**：两个分支都扫描，后出现的定义生效。语料未命中；若要完全保守，应把这类定义标为不确定并使路径解析失败。
2. **阅读文本保留条件标记**：`reading-v1` 对未知控制词不做删除，F1.2 形态的 block `text` 仍会包含 `\iffalse`/`\else`/`\fi`。内容未丢，但文本不够干净，建议在投影层单独处理条件标记。
3. **两个分支都会进入 entry**：include 两侧都可能被解析，语料中没有重复正文，但结构上存在重复风险；当前只降级 `structure_complete`，不做去重。
4. **分块兜底的诊断未去重**：畸形 entry 的诊断数量会随分块上升；可按 code+位置合并。
5. **F5 的出现身份**：当前没有独立 occurrence id；如果下游要按“第几次引用”审核，需要显式字段。
6. **金标与编译矩阵**：需要独立样本和人工内容核对，不能由本次回归替代。

## 8. 提交与复现命令

整改提交（均在 `main`，已推送）：

| 提交 | 内容 |
| --- | --- |
| `efcc08f` | F6.2 字面环境感知的文档边界 |
| `45b9e42` | F3 include 目录上下文 |
| `c320151` | F7 输出目录保护与原子切换 |
| `d28ca7c` | F6.1 保留环境开头花括号组 |
| `a1f9580` | F4/F5 单次 entry 解析与来源回映 |
| `4bd8353` | F2 宏顺序与作用域 |
| `2b4b093` | F1 条件分支与完整性判定 |

本机执行：

~~~sh
# 全量测试：414 项，2 个 pty 环境错误（基线相同）
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests

# 端到端复现：卡在上述 pty 测试，其余步骤未执行
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reproduce.py --out /tmp/qec-reproduce

# CLI 冒烟：第二次写入整体替换受管理目录；非受管理目录被拒绝
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/prepare_arxiv.py \
  <source-tree> --entry main.tex --out /tmp/prepared/paper --json
~~~

47 包语料对比使用一次性探针脚本，未入库；基线通过 `git archive 1d11dec` 解出到临时目录后用同一脚本运行。若要把该对比长期化，应先把它固化为可版本化的评测入口，再引用其数字。

## 9. 文档说明

本回复创建时按顺序重命名了本目录的三份文件，便于继续迭代；第 1–3 份文件的正文没有改动。后续新增回复建议沿用 `05-…`、`06-…` 的序号和 `0N-reply-to-0M-…` 的命名。由于正文未改，其中原有的 3 处相对链接仍指向旧文件名（第 2 份指向第 1 份，第 3 份指向第 1、2 份）。需要的话可以单独提交一次只修链接的文档提交，并保持本回复作为第 4 份。
