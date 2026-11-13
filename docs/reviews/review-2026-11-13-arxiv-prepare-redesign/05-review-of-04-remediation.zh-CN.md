# 离线 prepare 整改复评（第二轮）

> 状态：代码复评与离线复现记录；建议尚未实施。日期：2026-11-13。复评基线：2b4b0939360a66fbcf5db1f70b8f9d72b72177d4。

本报告回应 [04：离线 prepare 整改回复](04-reply-to-implementation-review.zh-CN.md)，并对照 [03：首次实现评估](03-implementation-review.zh-CN.md)。本轮只新增此评估文件，没有修改实现、测试、已有评审文件或原始论文包。探针、故障注入和转换输出全部位于新建临时目录。

## 目录

- [1. 复评结论](#1-复评结论)
- [2. 已核实的修复与验证结果](#2-已核实的修复与验证结果)
- [3. 仍需修复的六项问题](#3-仍需修复的六项问题)
- [4. 其他改进项](#4-其他改进项)
- [5. 建议整改顺序与验收条件](#5-建议整改顺序与验收条件)
- [6. 可复跑的内容反例](#6-可复跑的内容反例)
- [7. 执行记录与证据边界](#7-执行记录与证据边界)

## 1. 复评结论

**本轮整改有实际效果，但不能接受“F1–F7 全部关闭”的结论。**

上一轮的核心最小案例已经得到修复。统一解析 entry、保留多段来源映射、恢复重复引用、拒绝默认覆盖非受管理目录，都是有效改进。47 包的汇总数字也能独立复现。

但增加少量边界变化后，仍能得到“正文遗漏、错误文件被读入，程序却返回完整”的结果。本轮还实际验证了发布过程的中断窗口：目标目录会消失，旧结果留在隐藏备份目录中。因此，目前适合继续作为带诊断的实验性离线工具使用，还不应把退出码 0 或 document_complete 作为可靠内容验收凭据。

### 1.1 对上一轮问题的关闭判断

| 原问题 | 本轮判断 | 依据与保留事项 |
| --- | --- | --- |
| F1 完整性判断 | 部分修复，不能关闭 | 无扩展名片段已进入模型；含注释的条件分支仍能丢正文却 complete；没有 include 的不确定正文分支仍被判完整 |
| F2 路径宏状态 | 部分修复，不能关闭 | 普通顺序重定义和花括号作用域的原案例通过；动态重定义、空值重定义和条件内定义仍能留下错误的确定值 |
| F3 import 上下文 | 原案例修复已确认 | 同名文件案例现在读入 chap/section.tex；既有嵌套 import 回归通过 |
| F4 主文档上下文 | 原案例修复已确认 | 主文件声明的定理类型、跨文件定理正文得到保留；来源回映检查通过 |
| F5 重复引用 | 原案例修复已确认 | 两次正文各有独立 entry 区间和 A/B 章节归属 |
| F6 正文删改与截断 | 两个原案例已修复，问题类别仍有缺口 | 首个分组和 verbatim 示例通过；宏定义或非活跃分支中的文档标记仍会截断子文档 |
| F7 输出保护 | 默认覆盖问题已修复；中断恢复未完成 | canary 保持不变，普通写入失败测试通过；两次目录改名之间终止进程后目标目录不存在 |

“原案例修复已确认”只覆盖本轮检查的语法和数据，不表示所有 LaTeX 变体都已验收。也不要求实现完整 TeX 引擎：不支持的情况可以保留原文并明确降级，关键是不能静默选错或丢失后再标 complete。

### 1.2 本轮问题总览

P1 表示应在把转换结果当作可靠抽取输入前修复；P2 表示仍需修复，但本轮已观察到 partial 或可恢复的旧备份，影响与 P1 不同。

| 编号 | 优先级 | 问题 | 实测结果 |
| --- | --- | --- | --- |
| R1 | P1 | 条件边界扫描把字面 \n 当作换行查找 | 注释后活跃正文没有进入模型，CLI 仍退出 0 |
| R2 | P1 | 路径宏缺少失效与不确定状态传播 | 读取旧路径或错误分支的文件，CLI 仍退出 0 |
| R3 | P1 | 条件完整性只检查 include，未覆盖正文 | 两个互斥正文分支混入同一块仍 complete；已知非活跃正文又可能造成误报 partial |
| R4 | P1 | include 拼接没有保留文件结束处的注释边界 | 子文件末尾注释吞掉主文件后续正文，CLI 仍退出 0 |
| R5 | P2 | 文档边界扫描仍把定义和非活跃内容当成执行内容 | 合法子文档后半部分从 entry.tex 消失，CLI 返回 2 |
| R6 | P2 | 两次改名不构成一次原子发布 | 在两步之间终止进程，目标目录消失，旧结果仅在备份中 |

代码行号均对应本报告固定的复评基线。

## 2. 已核实的修复与验证结果

### 2.1 既有测试和原反例

- tools/reproduce.py 本轮成功完成，内部 **414 项测试全部通过**，包括真实 pty 测试；本轮没有遇到回复中记录的 out of pty devices。
- 端到端示例的切割、工作区发布、校验、搜索和上下文读取通过。
- 直接复跑第 03 份报告脚本中的 8 个内容案例：无扩展名、无注释的 iffalse/else、顺序重定义、import、定理声明、重复引用、首个分组、verbatim 文档结束示例，原先指出的对应问题均已改善。
- 另行执行非受管理输出目录探测：调用抛出 ValueError，USER_ORIGINAL_CANARY 逐字节不变。
- 跨文件定理和原花括号作用域等案例同时由本轮通过的既有回归覆盖。

这支持“原案例得到修复”，但新反例说明现有测试集还不足以支持“问题类别全部关闭”。

### 2.2 47 个原始包

使用与前两份报告相同的原始包、默认入口识别；未指定入口，PDF 对照不计入分母。每个输入包的 SHA-256 均与样本清单核对。

| 指标 | 第 03 份基线记录 | 第 04 份整改回复 | 本轮独立复跑 |
| --- | ---: | ---: | ---: |
| 退出码 0 / 2 / 1 | 30 / 6 / 11 | 29 / 7 / 11 | 29 / 7 / 11 |
| block 总数 | 11853 | 12003 | 12003 |
| section 总数 | 1022 | 1035 | 1035 |

本轮的 29 个退出码 0 占 61.7%，7 个 partial 占 14.9%，11 个失败占 23.4%。这些是程序分类比例，不是人工核验后的内容成功率。

11 个失败仍是 8 个入口歧义、1 个编码问题、2 个旧 tar 尾部校验问题，没有增加失败包。新增 partial 的 2411.11822v1 确实由 conditional_directives 触发。

本轮 partial 明细：

| 包 | block | section | 原因 |
| --- | ---: | ---: | --- |
| 0903.0566v1 | 132 | 6 | parser_errors |
| 2201.08309v1 | 1372 | 52 | parser_errors、uncovered_entry_text |
| 2411.11822v1 | 249 | 11 | conditional_directives |
| 2511.01062v1 | 201 | 20 | parser_errors |
| 2511.01062v2 | 203 | 21 | parser_errors |
| 2605.29137v1 | 2048 | 162 | conditional_directives、parser_errors |
| 2607.29382v2 | 573 | 34 | conditional_directives、parser_errors |

### 2.3 来源坐标检查

对全部 36 份已产生模型的输出、合计 12,003 个 block，额外核对：

1. source-map 中各来源字节片段拼接后等于 entry.tex。
2. 每个 block 的 source_spans 按顺序拼接后等于其 entry 字符区间。
3. entry 的字节区间与 Unicode codepoint 区间指向相同文本。
4. 非空 parent_key 均能在当前模型中找到对应块。

本轮上述检查 **0 个错误**。这支持新的来源回映实现；它验证的是“记录的区间是否对应原字节”，不能证明活跃正文选对了、所有应保留的内容都被选入，或块类型在数学意义上正确。

## 3. 仍需修复的六项问题

### 3.1 R1：条件分支中一行注释即可重新触发正文遗漏

**位置**：[assembly.py](../../../qecgraph/source/assembly.py) 的 _conditional_bounds，第 375–409 行，尤其第 388 行；[prepare.py](../../../qecgraph/source/prepare.py) 的 _parse_entry 与 _coverage，第 345–354、484–515 行。

条件边界扫描中的代码是：

~~~python
end = text.find("\\n", index)
~~~

这里寻找的是反斜杠和字母 n，并非换行字符。遇到正常的百分号注释后，扫描常常直接跳到文件末尾，找不到 else/fi。

最小主文件：

~~~tex
\documentclass{article}
\begin{document}
\section{Intro}
\iffalse
% disabled branch
\input{unused}
\else
\input{active}
\fi
\end{document}
~~~

unused.tex 为 NOT_ACTIVE.，active.tex 为 ACTIVE_BODY.。

**本轮实际结果**：

- assembly 没有记录任何 input 事件。
- document.json 只有 Intro 标题，缺少 ACTIVE_BODY。
- diagnostics 有 iffalse_skipped 和 include_not_in_entry。
- missing_dependencies 为 1，但 document_complete=true，CLI 退出码为 0。

这也说明仅修正换行字符还不够：解析器已经报告了“从 entry 外读到正文”，完整性门槛却没有将其作为正文缺失处理。

**建议**：

- 修正注释的换行边界，并补充含注释的 iffalse、iftrue、嵌套分支回归。
- 给依赖诊断保留位置和正文/导言区归属；正文的 include_not_in_entry 应使结果降级，不能因为导言区依赖允许缺失而放过所有依赖问题。
- 回归直接断言 ACTIVE_BODY 出现在模型中，并验证缺失时不能退出 0。

### 3.2 R2：路径宏仍会沿用已经失效的确定值

**位置**：[assembly.py](../../../qecgraph/source/assembly.py) 的 _literal_definition，第 460–474 行；_scan，第 563–568 行；_assemble_range，第 766–772 行。

#### 非字面重定义和空值重定义

例如：

~~~tex
\documentclass{article}
\newcommand{\DIR}{one}
\newcommand{\OTHER}{two}
\begin{document}
\renewcommand{\DIR}{\OTHER}
\input{\DIR/frag}
\end{document}
~~~

one/frag.tex 为 STALE_ONE.，two/frag.tex 为 CORRECT_TWO.。

当前无法识别新的非字面定义时，直接不更新宏状态，旧的 one 仍有效。实际读入 STALE_ONE，document_complete=true，CLI 退出 0。即使暂不支持展开这种宏，也应使 DIR 变为不确定，而不能继续使用旧值。

空定义也有同类问题：

~~~tex
\newcommand{\PREFIX}{old}
\renewcommand{\PREFIX}{}
\input{\PREFIX-frag}
~~~

包内存在 old-frag.tex 和 -frag.tex。本轮实际仍选择 old-frag.tex，因为更新逻辑以 if item.value 排除了合法的空字符串。

#### 条件内定义没有把不确定性传到条件外

~~~tex
\documentclass{article}
\newcommand{\flag}{}
\newcommand{\DIR}{one}
\begin{document}
\ifdefined\flag
  \renewcommand{\DIR}{one}
\else
  \renewcommand{\DIR}{two}
\fi
\input{\DIR/frag}
\end{document}
~~~

本例 flag 已定义。当前扫描两个分支，后出现的 two 生效；input 在条件之外，所以 conditional_directives=0。本轮实际只读入 WRONG_TWO，仍 complete，CLI 退出 0。

第 04 份回复已经坦诚列出这个限制，但它应被视为 F2/F1 尚未关闭的正确性问题，而非只影响未知未来样本的普通后续项。

#### 其他已复现的作用域边界

| 形态 | 实际结果 | 应改进之处 |
| --- | --- | --- |
| 花括号内先局部重定义为 two，再 gdef 为 three | 组内读 two，组外读 three，仍 complete | 全局重定义不能继续被旧的局部值遮蔽 |
| begingroup/endgroup 内重定义为 two，组外原值 one | 两次都读 two，仍 complete | 若尚不支持这种作用域，应标记限制，不能无声泄漏 |

**建议**：

- 宏状态区分“确定字面值”“确定空值”“未定义”“已定义但值不确定”，不要仅用字符串或缺项表达全部状态。
- 遇到不支持的重定义，主动使旧值失效。
- 条件分支合并时，只有各可能分支给出相同值才能保持确定；否则将不确定性传播到后续路径使用点。
- 对已支持的全局定义落实作用域语义；不支持的作用域组合应明确降级。

### 3.3 R3：条件完整性还没有覆盖普通正文

**位置**：[assembly.py](../../../qecgraph/source/assembly.py) 的 `_scan`，第 554–588 行；[prepare.py](../../../qecgraph/source/prepare.py) 的 `_coverage`，第 499–503 行，以及 `_uncovered_entry_prose`，第 457–481 行。

当前只有“条件内存在 include 指令”才触发 conditional_directives。没有 include 的真实正文同样存在活跃分支问题：

~~~tex
\documentclass{article}
\begin{document}
\section{Intro}
\ifdefined\flag
FIRST_BRANCH.
\else
SECOND_BRANCH.
\fi
\end{document}
~~~

**本轮实际结果**：两段互斥正文进入同一个 paragraph；只有 conditionals_present 诊断，document_complete=true，CLI 退出 0。块内没有表达哪个分支有效的结构化状态。

相反，将开头改成可判定的 iffalse，并令两个分支分别为 NOT_ACTIVE 和 ACTIVE_BODY，模型正确只取 ACTIVE_BODY 时，覆盖计数又把原始 entry 中未覆盖的 NOT_ACTIVE 当成遗漏，产生 uncovered_entry_text，错误降级为 partial。

因此目前同时存在：

- 应当保留不确定性的正文被判完整。
- 已知不应输出的非活跃正文被当成缺失。

**建议**：

- 对正文区间建立统一的活跃、非活跃、不确定状态，而不是只给 include 加标志。
- 只含排版命令的条件可不影响内容完整性；包含正文或会改变正文依赖的条件必须参与判断。
- 对已知非活跃区间明确排除；对不确定正文保留分支和诊断，并降级。
- 覆盖检查与结构解析使用同一份条件区间信息，避免两套扫描语义互相矛盾。

### 3.4 R4：子文件结尾的注释会吞掉主文件后续正文

**位置**：[assembly.py](../../../qecgraph/source/assembly.py) 的 EntryCoordinates，第 203–247 行；_assemble_range，第 820–845 行；[prepare.py](../../../qecgraph/source/prepare.py) 第 337–343 行。

第 04 份回复修复了相邻控制词的部分拼接问题，但仍未处理文件结束与注释的边界。

主文件正文：

~~~tex
\section{Intro}
\input{a}MUST_SURVIVE.
~~~

a.tex 的全部内容如下，**文件末尾没有换行**：

~~~tex
PRECEDING_BODY.% trailing comment
~~~

组装后得到：

~~~tex
PRECEDING_BODY.% trailing commentMUST_SURVIVE.
~~~

本轮 document.json 只有 PRECEDING_BODY，MUST_SURVIVE 没有进入阅读文本；uncovered_entry_chars=0，document_complete=true，CLI 退出 0。拼接把原本属于另一个输入流的正文变成了注释，覆盖检查又将它作为注释排除。

**建议**：

- 除控制词边界外，处理子文件 EOF、注释、行结束及恢复主文件输入时的词法边界。
- 原始字节和来源坐标继续保真，但结构解析与阅读文本应共享正确的解析视图；不能修好解析副本后，又对未经边界处理的拼接文本重新投影而丢失修复。
- 若暂时无法可靠表达边界，保留来源并报 partial，不得将被吞掉的正文判为已覆盖。
- 回归必须包含“子文件无末尾换行，主文件紧接正文”的情况。

### 3.5 R5：文档范围仍会被宏定义和非活跃内容截断

**位置**：[assembly.py](../../../qecgraph/source/assembly.py) 的 document_bounds，第 599–652 行；_document_body，第 655–668 行。

当前扫描器避开了注释和字面环境，但没有避开宏定义体或非活跃条件中的文档标记。

完整子文档 supp.tex：

~~~tex
\documentclass{article}
\begin{document}
\section{First}
Before.
\newcommand{\finish}{\end{document}}
\section{Second}
ACTUAL_TAIL.
\end{document}
~~~

主文件通过 input 引入 supp。finish 只是被定义，没有调用；定义体里的 end{document} 不应结束文档。

**本轮实际结果**：entry.tex 被截断，Second 和 ACTUAL_TAIL 均不存在。CLI 返回 2，并报告结构解析错误。

另一个已复现变体是将定义行替换为：

~~~tex
\iffalse\end{document}\fi
~~~

结果同样截断。与 R1/R2/R4 不同，这两例已返回 partial，所以本报告将其列为 P2；但被丢掉的尾部无法通过后续解析 entry.tex 找回，仍应修复。

**建议**：文档边界、include 扫描、条件分析复用同一套词法上下文。至少跳过未执行的声明体和可判定的非活跃分支；无法判断时保留完整来源并报告限制，避免提前裁剪。

### 3.6 R6：发布过程仍存在目标目录消失的中断窗口

**位置**：[prepare.py](../../../qecgraph/source/prepare.py) 的 write_outputs，第 635–643 行。

当前替换已有目录实际包含两步：

~~~python
os.replace(out, backup)
os.replace(staging, out)
~~~

每次改名可以独立原子完成，但两步之间不是一个原子事务。第 04 份回复与 DESIGN 中“一次目录改名切换，失败时保留上一份完整结果”的表述，对进程中断保证说得过满。

本轮故障注入方式：在独立子进程中包装 os.replace，正常完成第一步 out → backup 后立刻调用 os._exit(77)，绕过 Python 异常恢复。全部操作只发生在新建临时目录。

| 检查 | 实际结果 |
| --- | --- |
| 子进程退出码 | 77 |
| 原输出目录是否存在 | false |
| 原路径下能否读取旧 manifest | false |
| 隐藏 backup 数量 | 1 |
| 隐藏 staging 数量 | 1 |
| backup 是否与旧结果逐文件哈希一致 | true |

旧数据没有在本次探针中被删除，但原访问路径不可用，也没有自动恢复到旧结果。现有注入 _write_artifacts 失败的测试发生在改名之前，覆盖不到这个窗口。

**建议**：

- 区分普通写入异常、可捕获的改名失败和进程直接终止三种保证。
- 若需要中断后仍可读取上一版，采用不可变产物目录加原子指针切换，或设计有事务记录和明确恢复入口的发布协议。
- 至少对“第一步改名之后”“第二步之前/失败时”“恢复再次中断”增加故障注入。
- 在真正实现前，收窄文档中的原子发布和失败恢复承诺。

## 4. 其他改进项

### 4.1 未覆盖正文的计数仍只是启发式

**位置**：[prepare.py](../../../qecgraph/source/prepare.py) 的 _prose_chars，第 406–454 行。

本轮单独测试计数器，构造“标题已覆盖、后续正文完全未覆盖”的区间：

| 未覆盖内容 | uncovered_entry_chars |
| --- | ---: |
| 普通英文 Unrepresented words. | 18 |
| textbf 参数中的同一句话 | 0 |
| 中文正文 | 0 |
| 数学式 $x+y=1$ | 0 |
| 单字母 X | 0 |

这是对验证器盲区的直接测试，不等同于已经证明真实语料的这些内容全部丢失。但它足以说明“0 个未覆盖 ASCII 字母”不能代表整个正文已完整表达。命令参数也可能是真正正文，verbatim/lstlisting 等字面内容也可能是读者需要的内容。

建议为选中的源区间记录“已建模、明确排除、保留为未解析内容”及原因；公式、Unicode、文字命令参数和算法片段分别有内容断言。保留此计数作提示指标即可，不宜让它独自承担内容完整性的验收职责。

### 4.2 为离线转换规则记录独立版本

**位置**：[prepare.py](../../../qecgraph/source/prepare.py) 第 601–617 行；[prepare_arxiv.py](../../../tools/prepare_arxiv.py) 第 48–54 行。

当前输出记录 parser_version=0.3.6；本轮七个整改提交没有修改该版本，也没有记录独立的 prepare/assembly 规则版本或实现 commit。document/2 和 prepare/2 是格式标识，不能区分不同转换规则。

建议增加独立的离线转换规则版本，并把它及各产物哈希纳入产物清单。这样可以追溯“相同来源在不同转换逻辑下产生的不同模型”，也不必为了离线工具变化强迫无关 workspace 快照重建。

### 4.3 三处旧评审链接仍失效

第 04 份回复已经指出，本轮也确认：

- 第 02 份中的 LATEX-OFFLINE-ASSESSMENT.zh-CN.md。
- 第 03 份中的 LATEX-OFFLINE-ASSESSMENT.zh-CN.md。
- 第 03 份中的 REPLY-2026-11-13.zh-CN.md。

建议后续做一次仅更新链接的修复。本轮遵守“新增评估”的范围，没有改动这三处原文件。

## 5. 建议整改顺序与验收条件

1. **先阻止错误 complete**：修正 R1；正文缺失诊断、不确定路径和不确定正文必须降级。不能等扩大语法支持后再补完整性门槛。
2. **修正来源选择与拼接**：处理 R2 的宏失效/分支合并，以及 R4 的文件词法边界。
3. **统一条件与文档边界**：处理 R3/R5，让解析、裁剪和覆盖判断共享活跃区间，减少互相矛盾的扫描规则。
4. **补上发布恢复**：处理 R6 的事务窗口，修正文档保证并加入进程终止测试。
5. **固化回归与版本**：将本轮反例转为正式测试，记录 prepare 规则版本，再按相同输入重跑 47 包。

建议验收以以下结果为准：

| 范围 | 验收条件 |
| --- | --- |
| 条件注释 | 活跃正文保留；已知非活跃内容不产生误报；正文漏入时不能 complete |
| 宏状态 | 动态/空值重定义不沿用旧值；不确定状态传播到路径；明确支持的作用域行为正确 |
| 条件正文 | 不把两个互斥分支当成已确定的普通正文；未知状态可定位到来源区间 |
| 文件拼接 | 子文件末尾注释不吞主文件正文；解析文本与阅读投影一致 |
| 文档边界 | 定义体和非活跃分支中的文档标记不截断实际尾部 |
| 来源映射 | 新解析视图中的内容仍能精确回映原始字节，重复出现保持独立区间 |
| 发布 | 每个约定的失败点都有明确结果，原路径的可用性和恢复方式与文档一致 |
| 完整性证据 | 分别报告程序退出、字节映射、内容保留、结构正确性和人工验收，不能相互替代 |

这些问题可以继续用离线程序处理，并不构成必须引入 AI 的理由。优先建立保守的状态传播和可解释的 partial，通常比对每个反例继续增加独立正则更容易控制错误。

## 6. 可复跑的内容反例

以下脚本可在项目根目录使用项目解释器运行。来源在内存中构造，不读写真实论文目录；prepare 内部只使用临时树。它输出当前行为，供后续修复时转为回归断言。

~~~python
import json

from qecgraph.source.package import SourceTree
from qecgraph.source.prepare import prepare_source


def doc(body, preamble=""):
    return (
        "\\documentclass{article}\n" + preamble
        + "\n\\begin{document}\n" + body + "\n\\end{document}\n"
    )


cases = {
    "R1_comment_in_iffalse": {
        "main.tex": doc(
            "\\section{Intro}\n\\iffalse\n% disabled branch\n"
            "\\input{unused}\n\\else\n\\input{active}\n\\fi"
        ),
        "unused.tex": "NOT_ACTIVE.\n",
        "active.tex": "ACTIVE_BODY.\n",
    },
    "R2_dynamic_redefinition": {
        "main.tex": doc(
            r"\renewcommand{\DIR}{\OTHER}\input{\DIR/frag}",
            r"\newcommand{\DIR}{one}\newcommand{\OTHER}{two}",
        ),
        "one/frag.tex": "STALE_ONE.\n",
        "two/frag.tex": "CORRECT_TWO.\n",
    },
    "R2_empty_redefinition": {
        "main.tex": doc(
            r"\renewcommand{\PREFIX}{}\input{\PREFIX-frag}",
            r"\newcommand{\PREFIX}{old}",
        ),
        "old-frag.tex": "STALE_OLD.\n",
        "-frag.tex": "CORRECT_EMPTY.\n",
    },
    "R2_conditional_definition": {
        "main.tex": doc(
            "\\ifdefined\\flag\n\\renewcommand{\\DIR}{one}\n"
            "\\else\n\\renewcommand{\\DIR}{two}\n\\fi\n\\input{\\DIR/frag}",
            r"\newcommand{\flag}{}\newcommand{\DIR}{one}",
        ),
        "one/frag.tex": "CORRECT_ONE.\n",
        "two/frag.tex": "WRONG_TWO.\n",
    },
    "R3_unknown_body_branches": {
        "main.tex": doc(
            "\\section{Intro}\n\\ifdefined\\flag\nFIRST_BRANCH.\n"
            "\\else\nSECOND_BRANCH.\n\\fi"
        ),
    },
    "R3_inactive_prose_false_positive": {
        "main.tex": doc(
            "\\section{Intro}\n\\iffalse\nNOT_ACTIVE.\n"
            "\\else\nACTIVE_BODY.\n\\fi"
        ),
    },
    "R4_comment_at_eof": {
        "main.tex": doc("\\section{Intro}\n\\input{a}MUST_SURVIVE."),
        "a.tex": "PRECEDING_BODY.% trailing comment",
    },
    "R5_document_end_in_definition": {
        "main.tex": doc(r"\input{supp}"),
        "supp.tex": doc(
            "\\section{First}\nBefore.\n"
            "\\newcommand{\\finish}{\\end{document}}\n"
            "\\section{Second}\nACTUAL_TAIL."
        ),
    },
    "R5_document_end_in_inactive_branch": {
        "main.tex": doc(r"\input{supp}"),
        "supp.tex": doc(
            "\\section{First}\nBefore.\n\\iffalse\\end{document}\\fi\n"
            "\\section{Second}\nACTUAL_TAIL."
        ),
    },
}

for name, files in cases.items():
    tree = SourceTree(
        "review",
        {path: text.encode("utf-8") for path, text in files.items()},
    )
    prepared = prepare_source(tree, "main.tex")
    print(json.dumps({
        "case": name,
        "complete": prepared.coverage["document_complete"],
        "reasons": prepared.coverage["reasons"],
        "targets": [event.target for event in prepared.assembly.events],
        "texts": [block["text"] for block in prepared.document["blocks"]],
        "diagnostics": prepared.diagnostics,
    }, ensure_ascii=False))
~~~

在本报告基线上，R1、三个 R2、R3_unknown_body_branches、R4 共六个反例返回 complete=true；R3 的已知非活跃正文误报和两个 R5 返回 false。前六种不是验收通过，而是本报告指出的错误完整判定。

R6 的进程终止探针需在独立子进程和新建临时目录运行；不要在真实输出目录测试。其注入点及实际结果见 §3.6。本报告没有将此故障探针加入正式测试套件。

## 7. 执行记录与证据边界

### 7.1 固定版本和运行环境

| 项目 | 值 |
| --- | --- |
| 实现 commit | 2b4b0939360a66fbcf5db1f70b8f9d72b72177d4 |
| 样本清单 | test-sources/arxiv-sources/manifest.json |
| 清单 SHA-256 | 153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b |
| Python | 3.15.2，项目 .venv |
| pylatexenc / jsonschema | 2.10 / 4.26.0 |
| SQLite | 3.54.1，FTS5 可用 |
| 平台记录 | macOS-27.2.1-arm64-arm-64bit-Mach-O |
| 端到端示例 release | 2330ea440e9e356a3d69c525bd87f0430ab87f5fba58ff4b947cff8aff8ab3bc |

本轮测试开始于 2026-11-13 08:07:24 UTC，端到端复现结束于 08:08:01 UTC。414 项测试日志记录约 35.85 秒。47 包采用 3 个并发子进程、每包 60 秒超时，合计约 16.14 秒，没有超时；此时间不是稳定性能基准，不能与另一机器或不同并发负载下的数字直接比较。

### 7.2 实际执行命令

端到端复现：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reproduce.py \
  --out /var/folders/9h/g5yg6yhx3_9gmyxzmxzft0zc0000gn/T/qec-prepare-rereview-wwb26e89/reproduce
~~~

该命令内部执行 python -m unittest discover -s tests -v。结果为 414 项测试及后续端到端步骤全部通过。

47 包逐个调用以下 CLI 形式；未设置 entry：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/prepare_arxiv.py \
  "<original-package>" \
  --out "<temporary-root>/all-packages/<case-id>" \
  --json
~~~

另外将八种新内容反例落到临时来源目录，使用同一 CLI 和显式 main.tex 重跑：R1、R2 的动态/空值/条件定义、R3 的未知正文、R4 均退出 0；两个 R5 退出 2。R3 的非活跃正文误报通过 prepare_source 直接验证。

### 7.3 临时证据

临时根目录：

~~~text
/var/folders/9h/g5yg6yhx3_9gmyxzmxzft0zc0000gn/T/qec-prepare-rereview-wwb26e89
~~~

| 文件 | 内容 |
| --- | --- |
| reproduce/results.json | 固定运行环境、执行步骤、414 项测试和端到端汇总 |
| reproduce/unit_tests.stderr.txt | 测试明细 |
| synthetic-cases.json | 原 8 个内容案例及扩展探针的输入、组装、模型、诊断 |
| additional-cases.json | EOF 注释和声明内文档标记探针 |
| all-packages.json | 47 包的输入哈希、退出码、耗时、stderr 和 summary |
| mapping-checks.json | 36 包、12,003 块的来源回映检查结果 |
| cli-reproductions.json | 八个新增反例的 CLI 结果 |
| fault-and-coverage.json | 输出目录保护、中断注入和覆盖计数器检查 |
| review_probe.py / check_results.py / fault_probe.py | 本轮一次性探针脚本 |

这些临时文件可能被系统清理；本报告保留了关键版本、数字、失败行为和可复跑的内容反例。它们不是已经纳入版本管理的长期评测设施。

### 7.4 本轮没有验收的事项

- 没有建立 47 包的独立人工正文或结构金标，不能据本轮数字宣称内容成功率为 61.7%。
- 没有重新验证第 04 份回复对每个 block 增减原因的全部人工解释；本轮复现的是输出计数、原案例与来源区间一致性。
- 没有执行 TeX/PDF 编译、Docker、Lean 或真实模型调用。
- 没有访问 human、私人笔记或凭据，也没有修改 QEC-database。
- 没有运行 QEC-database machine 副本上的下游检索评测；本轮只做审查和新增文档，离线 prepare 仍未接入 workspace。下游质量继续记为未验收。
- 进程中断测试使用 os._exit 注入；没有宣称验证断电、磁盘满或全部文件系统崩溃恢复场景。
- 没有实现本报告的建议、提交 Git 变更或修改既有评审记录。
