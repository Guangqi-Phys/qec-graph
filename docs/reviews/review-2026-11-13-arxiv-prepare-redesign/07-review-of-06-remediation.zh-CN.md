# 离线 prepare 第三轮实现复评

> 状态：代码复评与离线复现记录；本报告建议尚未实施。日期：2026-11-13。固定实现：6bea6d901d6c7176a43be7a44c2858882d3ba2d5。

本报告对照 [06：第二轮整改回复](06-reply-to-review-05.zh-CN.md) 和 [05：第二轮复评](05-review-of-04-remediation.zh-CN.md)，检查原反例、最新实现及组合边界。本轮只新增评估文档；探针与转换产物全部写入新建临时目录，没有修改实现、正式测试或原始论文包。

## 目录

- [1. 结论](#1-结论)
- [2. 已确认的改进](#2-已确认的改进)
- [3. 五项仍需优先修复的问题](#3-五项仍需优先修复的问题)
- [4. 建议的下一轮修复与验收](#4-建议的下一轮修复与验收)
- [5. 可复跑的内容反例](#5-可复跑的内容反例)
- [6. 验证记录与范围](#6-验证记录与范围)

## 1. 结论

**上一轮的九个内容反例已经得到预期修复，但当前实现仍不能以 complete 或退出码 0 作为内容正确性的可靠保证。**

本轮发现五组需要优先处理的问题。其中，恢复逻辑会在目标目录被重新创建后删除旧结果备份，是新的数据保留问题。其余问题涉及条件与作用域合并、条件边界的词法处理，以及解析视图与完整性检查不一致；均有小型反例，实际出现错误内容仍被判完整的情况。

本轮没有要求实现完整 TeX 引擎。支持不了的结构可以保留原文并明确 partial，但“只会更保守，不会确定地选错”这一保证目前不成立。

| 编号 | 优先级 | 问题 | 已复现影响 |
| --- | --- | --- | --- |
| S1 | P1 | 恢复把“目录存在”当成“新结果已发布” | 空目录或无关目录导致旧结果备份被删除，CLI 仍报告 committed |
| S2 | P1 | 分支合并丢失作用域和多分支状态 | 选择错误文件，仍 complete |
| S3 | P1 | 条件配对仍扫描定义体和字面环境中的 fi | 活跃分支被错误结束，读入另一分支文件，仍 complete |
| S4 | P1 | 条件正文门槛仍依赖 ASCII 字母计数 | 互斥的公式、加粗正文、Unicode 正文混入模型，仍 complete |
| S5 | P1 | 条件分析读取未经补边界的 entry | 条件标记被拼接注释遮住，两分支正文甚至未标 conditional，仍 complete |

P1 表示建议在把产物作为可靠抽取输入之前修复，不表示本轮曾操作或损坏真实用户数据。

## 2. 已确认的改进

### 2.1 原反例的修复情况

直接执行第 05 份报告 §6 的九个案例：

| 原案例 | 当前结果 |
| --- | --- |
| 条件内一行注释 | 正确包含 ACTIVE_BODY |
| 非字面宏重定义 | 无 target，partial，不再沿用旧文件 |
| 空字符串重定义 | 正确选择 -frag.tex |
| 不确定条件内不同定义 | 无 target，partial |
| 不确定的普通英文正文分支 | partial，块标记 conditional=true |
| 已知非活跃正文 | 不再产生遗漏误报，complete |
| 子文件末尾注释 | 主文件的 MUST_SURVIVE 保留 |
| 定义体中的文档结束标记 | Second 和 ACTUAL_TAIL 保留 |
| 非活跃分支中的文档结束标记 | Second 和 ACTUAL_TAIL 保留 |

另外，原有中断路径已得到改善：子进程在 out → backup 后终止，目标目录保持不存在的情况下，执行 --recover 能恢复旧结果；六个产物逐文件 SHA-256 与中断前一致。S1 是在此路径上增加“恢复前重新创建目标目录”后暴露的问题。

所有 36 份生成产物均记录 prepare_version=prepare-rules-v2。独立规则版本已落实。

### 2.2 测试、语料与来源坐标

| 检查 | 本轮结果 |
| --- | --- |
| 全量单元及集成测试 | 438 项全部通过 |
| tools/reproduce.py | 通过，包括后续发布、校验、搜索和上下文读取 |
| 47 包退出码 0 / 2 / 1 | 29 / 7 / 11 |
| block / section 总数 | 12003 / 1035 |
| 产物 diagnostics 总数 | 38 |
| 36 包、12003 块的来源区间检查 | 0 个错误 |

语料汇总与第 06 份回复一致。本机此次没有出现该回复记录的 pty 环境错误。

来源检查包括 source-map 字节片段拼接、block 的 source_spans 与 entry 字符区间一致、entry 字节与 Unicode codepoint 区间一致。这能证明选中内容的坐标保真，不能证明选择了正确分支或遗漏检查没有盲区。

## 3. 五项仍需优先修复的问题

代码行号对应本报告固定的实现 commit。

### 3.1 S1：恢复可能删除唯一的旧结果备份

**位置**：[prepare.py](../../../qecgraph/source/prepare.py)，recover_output，第 752–757 行。

目前的判断是：只要 out.is_dir()，就认为新目录已安装成功，删除 staging 和 backup，并返回 committed。它没有验证目标目录的 manifest，也没有核对它是不是这次事务生成的版本。

**实际复现过程**：

1. 在临时目录生成包含 OLD_RESULT 的完整旧产物。
2. 更新产物；在 out → backup 完成后通过独立子进程的 os._exit(77) 中断。
3. 模拟用户或调用脚本执行 mkdir -p out，重新创建空输出目录。
4. 执行 tools/prepare_arxiv.py --out out --recover --json。

| 恢复前状态 | CLI 结果 | 恢复后旧结果 | backup |
| --- | --- | --- | --- |
| out 仍不存在 | restored，退出 0 | 逐文件哈希一致 | 正常清理 |
| out 是刚重建的空目录 | committed，退出 0 | 不存在；out 仍为空 | 被删除 |
| out 中只有无关 user.txt | committed，退出 0 | 不存在；只剩 user.txt | 被删除 |

后两种情况还删除了 journal。旧产物本来完整保存在 backup 中，却被恢复操作删掉。这不只是暂时无法从原路径访问。

**建议**：

- journal 记录事务标识、预期旧版本、新 manifest 的摘要及所管理产物。
- 只有确认 out 是预期完整的新版本，才能清理旧 backup。
- 对空目录、非受管理目录、版本不匹配或缺少产物的目录，保留备份并返回明确冲突；不要据目录存在判断 committed。
- 增加“中断后 mkdir”“中断后放入无关文件”“目标是另一份合法但版本不同的产物”测试。

现有正常中断恢复测试通过，不能覆盖这些状态变化。

### 3.2 S2：分支合并并非只会更保守

**位置**：[assembly.py](../../../qecgraph/source/assembly.py)，_define，第 1238–1251 行；_conditional，第 1253–1278 行。

处于条件内时，定义直接写进 conditional_frames 的单个 current 字典，绕过普通作用域和 global_scope 处理；离开条件后又只合并两个字典。这会产生确定但错误的值。

#### 局部定义泄漏到条件外

主文件先定义 DIR=one，然后：

~~~tex
\ifdefined\flag
  {\renewcommand{\DIR}{two}}
\else
  {\renewcommand{\DIR}{two}}
\fi
\input{\DIR/frag}
~~~

两个分支的重定义都位于已关闭的花括号内，不论选择哪个分支，条件外都应恢复为 one。

本轮实际选择 two/frag.tex，文本为 WRONG_TWO，document_complete=true，CLI 退出 0。

#### 全局定义反而被局部化

在外层花括号里，两分支均执行 gdef：

~~~tex
{
\ifdefined\flag
  \gdef\DIR{two}
\else
  \gdef\DIR{two}
\fi
}
\input{\DIR/frag}
~~~

两个分支都会使全局 DIR=two；本轮实际选择旧的 one/frag.tex，仍 complete，CLI 退出 0。

#### ifcase 的多分支被压成两个结果

~~~tex
\ifcase0
  \renewcommand{\DIR}{one}
\or
  \renewcommand{\DIR}{two}
\else
  \renewcommand{\DIR}{two}
\fi
\input{\DIR/frag}
~~~

当前把第一个分支和 or 分支顺序执行到同一字典里，再与 else 比较，得到“双方均为 two”。实际选择 two/frag.tex，仍 complete，CLI 退出 0。

因此第 06 份回复关于“分支内作用域和 ifcase 限制只会更保守，不会产生确定错误路径”的判断应修正。这三例都没有满足该保证。

**建议**：

- 分支状态保留完整的作用域栈及全局写入效果。
- 合并的是各分支执行结束后可见的状态，不能把所有出现过的局部定义当作最终结果。
- 对 ifcase 显式处理所有可能分支；尚未支持时，把受影响的值标不确定，不能用最后一次赋值替代整个分支集合。
- 验收同时检查目标文件、正文和 complete；只检查出现 uncertain_path 的原案例不足以覆盖上述路径。

### 3.3 S3：条件匹配仍把字面 fi 当成结束符

**位置**：[assembly.py](../../../qecgraph/source/assembly.py)，_conditional_bounds，第 453–476 行。

外层 _scan 和 document_bounds 能跳过声明与字面环境，但负责配对条件的 _conditional_bounds 没有同样的词法上下文。它直接扫描控制词，遇到第一个相应深度的 fi 就结束。

主文件先定义 DIR=old，然后：

~~~tex
\iftrue
  \newcommand{\fake}{\fi}
  \renewcommand{\DIR}{one}
\else
  \renewcommand{\DIR}{two}
\fi
\input{\DIR/frag}
~~~

fake 只被定义，没有调用；定义体里的 fi 不应结束这个活跃条件。实际应使用 one，当前却读入 two/frag.tex，document_complete=true，CLI 退出 0，diagnostics 为空。

将 fake 的定义替换成活跃分支中的字面示例，结果相同：

~~~tex
\begin{verbatim}
\fi
\end{verbatim}
~~~

本轮两个案例均实际复现了 WRONG_TWO。

**建议**：条件配对也必须具有与调用者相符的词法上下文。在活跃分支中忽略声明体和字面环境里的控制词；无法可靠判断的组合应降级。修复不能仅停留在最外层扫描器，否则嵌套调用依然会误配。

### 3.4 S4：公式和文字命令仍能绕过条件完整性门槛

**位置**：[prepare.py](../../../qecgraph/source/prepare.py)，_conditional_body_prose，第 553–562 行；_coverage，第 597–599 行。

`conditional_body` 使用 `_prose_chars` 计数。它跳过命令参数、非 ASCII 字符和不足两个字母的连续串，因此正文计数为 0，并不意味着条件里只有排版指令。

实际复现以下正文：

~~~tex
\ifdefined\flag
$d=3$
\else
$d=1$
\fi
~~~

本轮输出把两个互斥公式都放进一个 paragraph，块已标 conditional=true，但 conditional_body_chars=0、document_complete=true，CLI 退出 0。

另外两类真实正文也得到相同结果：

| 分支内容 | 条件正文计数 | 块标记 | 完整状态 |
| --- | ---: | --- | --- |
| textbf 参数中的 FIRST_BRANCH / SECOND_BRANCH | 0 | conditional=true | complete |
| 第一分支。 / 第二分支。 | 0 | conditional=true | complete |
| 数学式 d=3 / d=1 | 0 | conditional=true | complete |

第 06 份回复虽已披露计数是启发式，但它仍直接决定是否允许 complete，所以这已是实际输出的正确性缺口，不能仅归为“还没有人工金标”。

**建议**：

- 判断条件区间是否包含可见内容、数学块、结构块或未解析内容。
- 对确知纯排版的命令做明确排除；未知命令参数不能一律当成没有正文。
- 未解析的条件内内容保留不确定状态，不因计数为 0 升级为完整。
- 增加公式、格式命令包裹文本和 Unicode 的真实 prepare/CLI 测试，不只单测计数器。

### 3.5 S5：修复解析视图后，条件分析仍读取旧的拼接文本

**位置**：[prepare.py](../../../qecgraph/source/prepare.py)，prepare_source，第 632–647 行；[assembly.py](../../../qecgraph/source/assembly.py)，EntryCoordinates，第 267–313 行。

结构解析使用补过换行的解析副本，后续 document_bounds、condition_regions 和条件正文计数却仍读取 assembly.text。两种视图的词法边界不同。

主文件正文：

~~~tex
\section{Intro}
\input{a}\ifdefined\flag
FIRST_BRANCH.
\else
SECOND_BRANCH.
\fi
~~~

a.tex 没有末尾换行，内容为：

~~~tex
PRECEDING_BODY.% trailing comment
~~~

- 解析副本在子文件末尾补换行，因此能够读到 ifdefined 和两段正文。
- 原始 entry 的拼接结果把 ifdefined 接在百分号注释后面；condition_regions 跳过这行，就看不到条件的开始。

**本轮结果**：模型包含 FIRST_BRANCH 和 SECOND_BRANCH，但 conditional_ranges 为空、对应 paragraph 的 conditional=false、document_complete=true，CLI 退出 0。

这次使用的是普通英文正文，不涉及 S4 的 ASCII 计数盲区。它说明 R4 与 R3 单独通过之后，组合起来仍会产生错误的确定性判断。

**建议**：结构解析、条件分析、文档边界与覆盖判断共用同一解析视图；再用 EntryCoordinates 把区间转换回 entry 坐标。原始来源字节仍应保留，不能通过修改归档内容解决视图不一致。

## 4. 建议的下一轮修复与验收

优先顺序：

1. 先修 S1，确保恢复不会因目标目录被重建而删除上一份完整产物。
2. 修 S2/S3，保证路径选择和分支匹配不会产生确定的错误内容。
3. 修 S5，统一解析视图和来源坐标转换。
4. 修 S4，用可见内容和未解析内容的状态补足完整性门槛。
5. 将组合案例加入正式回归，再按相同输入重跑语料。

本轮不建议继续按单个示例增加互不关联的判断规则。已有 _scan、_conditional_bounds、document_bounds、condition_regions，以及原始 entry 和解析副本；它们需要共享词法事件、作用域和条件区间，才能减少同一种语法在不同阶段得到不同解释的情况。

验收应包括：

| 范围 | 必须直接断言 |
| --- | --- |
| 恢复 | 目录存在但产物不完整时不得清理唯一旧备份；冲突可解释且可重试 |
| 分支状态 | 局部定义退出后恢复、全局定义保留、所有可能分支参与合并 |
| 词法 | 活跃声明和字面内容里的 fi 不改变条件配对 |
| 条件内容 | 公式、文字命令和 Unicode 都参与内容状态判断 |
| 组合视图 | EOF 注释之后的条件能被解析、标记并正确降级 |
| 来源 | 条件区间和阅读文本继续对应正确的 entry/source_spans |
| 完整状态 | 选错文件或混合未决正文不能返回 complete |

这些问题仍可通过离线程序解决。当前限制来自状态模型与检查口径不一致，不能用现有样本计数没有变化来排除。

## 5. 可复跑的内容反例

以下脚本在项目根目录使用项目解释器运行。它构造内存来源，prepare 内部使用临时树；不接触真实论文目录。

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
    "S2_local_scope": {
        "main.tex": doc(
            "\\ifdefined\\flag\n{\\renewcommand{\\DIR}{two}}\n"
            "\\else\n{\\renewcommand{\\DIR}{two}}\n\\fi\n\\input{\\DIR/frag}",
            r"\newcommand{\DIR}{one}\newcommand{\flag}{}",
        ),
        "one/frag.tex": "CORRECT_ONE.\n",
        "two/frag.tex": "WRONG_TWO.\n",
    },
    "S2_global_scope": {
        "main.tex": doc(
            "{\\ifdefined\\flag\n\\gdef\\DIR{two}\n"
            "\\else\n\\gdef\\DIR{two}\n\\fi}\n\\input{\\DIR/frag}",
            r"\newcommand{\DIR}{one}\newcommand{\flag}{}",
        ),
        "one/frag.tex": "WRONG_ONE.\n",
        "two/frag.tex": "CORRECT_TWO.\n",
    },
    "S2_ifcase": {
        "main.tex": doc(
            "\\ifcase0\n\\renewcommand{\\DIR}{one}\n\\or\n"
            "\\renewcommand{\\DIR}{two}\n\\else\n"
            "\\renewcommand{\\DIR}{two}\n\\fi\n\\input{\\DIR/frag}",
            r"\newcommand{\DIR}{old}",
        ),
        "one/frag.tex": "CORRECT_ONE.\n",
        "two/frag.tex": "WRONG_TWO.\n",
    },
    "S3_definition": {
        "main.tex": doc(
            "\\iftrue\n\\newcommand{\\fake}{\\fi}\n"
            "\\renewcommand{\\DIR}{one}\n\\else\n"
            "\\renewcommand{\\DIR}{two}\n\\fi\n\\input{\\DIR/frag}",
            r"\newcommand{\DIR}{old}",
        ),
        "one/frag.tex": "CORRECT_ONE.\n",
        "two/frag.tex": "WRONG_TWO.\n",
    },
    "S3_verbatim": {
        "main.tex": doc(
            "\\iftrue\n\\begin{verbatim}\n\\fi\n\\end{verbatim}\n"
            "\\renewcommand{\\DIR}{one}\n\\else\n"
            "\\renewcommand{\\DIR}{two}\n\\fi\n\\input{\\DIR/frag}",
            r"\newcommand{\DIR}{old}",
        ),
        "one/frag.tex": "CORRECT_ONE.\n",
        "two/frag.tex": "WRONG_TWO.\n",
    },
    "S4_math": {
        "main.tex": doc(
            "\\section{Intro}\n\\ifdefined\\flag\n"
            "$d=3$\n\\else\n$d=1$\n\\fi"
        ),
    },
    "S4_text_command": {
        "main.tex": doc(
            "\\section{Intro}\n\\ifdefined\\flag\n"
            "\\textbf{FIRST_BRANCH}\n\\else\n\\textbf{SECOND_BRANCH}\n\\fi"
        ),
    },
    "S4_unicode": {
        "main.tex": doc(
            "\\section{Intro}\n\\ifdefined\\flag\n"
            "第一分支。\n\\else\n第二分支。\n\\fi"
        ),
    },
    "S5_comment_then_condition": {
        "main.tex": doc(
            "\\section{Intro}\n\\input{a}\\ifdefined\\flag\n"
            "FIRST_BRANCH.\n\\else\nSECOND_BRANCH.\n\\fi"
        ),
        "a.tex": "PRECEDING_BODY.% trailing comment",
    },
}

for name, files in cases.items():
    prepared = prepare_source(
        SourceTree("review", {
            path: text.encode("utf-8") for path, text in files.items()
        }),
        "main.tex",
    )
    print(json.dumps({
        "case": name,
        "complete": prepared.coverage["document_complete"],
        "reasons": prepared.coverage["reasons"],
        "conditional_body_chars": prepared.coverage["conditional_body_chars"],
        "conditional_ranges": prepared.coverage["conditional_ranges"],
        "targets": [event.target for event in prepared.assembly.events],
        "blocks": [
            {"text": block["text"], "conditional": block["conditional"]}
            for block in prepared.document["blocks"]
        ],
    }, ensure_ascii=False))
~~~

在本报告固定基线上，上述九例均返回 complete=true。S2/S3 输出对应的 WRONG 内容；S4 虽标 conditional，但仍完整；S5 连 conditional 标记也丢失。这些是失败反例，不是九项验收通过。

S1 的故障注入需在新建临时目录的独立子进程中执行。注入点是首次 os.replace(out, backup) 成功之后立即 os._exit(77)，随后在父进程重建 out 并调用 --recover。完整步骤和三组实际结果见 §3.1。

## 6. 验证记录与范围

### 6.1 环境与固定输入

| 项目 | 值 |
| --- | --- |
| 实现 commit | 6bea6d901d6c7176a43be7a44c2858882d3ba2d5 |
| prepare_version | prepare-rules-v2 |
| Python | 3.15.2，项目 .venv |
| pylatexenc / jsonschema | 2.10 / 4.26.0 |
| SQLite | 3.54.1，FTS5 可用 |
| 平台 | macOS-27.2.1-arm64-arm-64bit-Mach-O |
| 样本清单 SHA-256 | 153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b |
| 示例 workspace release | cfe992c694d96fb9109ae8fea4dc1c70fe7c4f4764e52c65ea1723863c706732 |

样本清单是 test-sources/arxiv-sources/manifest.json，每包 SHA-256 均核对。47 包使用原始包、默认入口，不含 PDF 对照。三个并发子进程、每包 60 秒超时，本轮没有超时，总耗时约 15.97 秒；不是稳定吞吐量承诺。

### 6.2 命令与结果

执行端到端复现：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reproduce.py \
  --out /tmp/qec-prepare-review3-0dkqg9_f/reproduce
~~~

内部执行 python -m unittest discover -s tests -v。438 项测试日志约 36.01 秒，结果 OK；端到端状态 passed。UTC 起止为 2026-11-13 08:53:35 至 08:54:12。

47 包按以下 CLI 形式执行：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/prepare_arxiv.py \
  "<original-package>" --out "<temporary-root>/all-packages/<case-id>" --json
~~~

对本轮九个错误完整的内容反例，额外写入临时来源目录后使用同一 CLI、显式指定 main.tex，全部退出 0。另一个嵌套条件探针已返回 unclosed_conditional、退出 2；没有将它计入以上九个错误完整反例。

恢复测试使用：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/prepare_arxiv.py \
  --out "<temporary-output>" --recover --json
~~~

三种恢复前状态及逐文件哈希比较见 §3.1。

### 6.3 证据与限制

临时目录为 /tmp/qec-prepare-review3-0dkqg9_f，保留：

| 文件 | 内容 |
| --- | --- |
| reproduce/results.json | 环境、执行步骤及测试/端到端汇总 |
| reproduce/unit_tests.stderr.txt | 438 项测试日志 |
| synthetic-cases.json | 原九例与十个扩展探针的输入和完整输出 |
| all-packages.json | 47 包的输入哈希、退出码、耗时与 summary |
| mapping-checks.json | 来源区间校验、diagnostics 数与规则版本 |
| cli-reproductions.json | 扩展内容案例的 CLI 退出码 |
| recovery-probes.json | 三种恢复前状态和旧结果哈希比较 |
| probe.py / validate.py / recovery_probe.py | 本轮临时探针脚本 |

临时目录可能被系统清理，关键反例和验证数字已经保留在本报告中。未将这些探针宣称为正式长期评测。

本轮未建立独立人工内容金标，未执行 TeX/PDF 编译、Docker、Lean 或真实模型；没有访问 human、私人笔记或凭据，也没有修改 QEC-database。离线 prepare 仍未接入 workspace，下游 machine 副本检索质量继续记为未验收。本轮没有改变导入或解析代码。

进程终止测试使用 os._exit，并非断电或文件系统损坏测试。关于三个旧评审链接及其他已披露限制，保留第 06 份回复的未完成状态，本轮没有改动历次文档。
