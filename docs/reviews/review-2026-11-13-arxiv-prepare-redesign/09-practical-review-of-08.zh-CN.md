# 08 实现的可用性复评

> 状态：工程复评记录，未修改实现。日期：2026-11-13。固定 commit：85cd8e30df9dcdec2247385e231ee4a1b51ea966。

对应 [08：第三轮整改回复](08-reply-to-review-07.zh-CN.md) 和 [07：第三轮实现复评](07-review-of-06-remediation.zh-CN.md)。本轮按用户最新要求，以可用、稳定和后续内容抽取为准，不以支持全部 LaTeX 语法或消除所有边界情况为目标。

## 1. 结论

**08 可以进入后续内容抽取联调，无需继续为了覆盖所有语法而重构。正式批量使用前，建议补一条防止读错正文的保守判断。**

现有真实样本上的运行结果稳定，上一轮的具体反例已修复。当前值得优先处理的是：混合全局和局部宏定义时，分支合并仍可能选择错误的正文文件。这个问题会直接改变抽取输入，应避免。

其他已知限制按是否影响实际抽取处理；不再作为要求全部解决后才能推进的清单。

## 2. 已验证的工程结果

| 项目 | 本轮结果 |
| --- | --- |
| 全量测试 | 452 项全部通过 |
| tools/reproduce.py | 全部通过，包括发布、校验、搜索与上下文读取 |
| 上一轮 07 的九个内容反例 | 均得到预期修复 |
| 03、05、07 的内容案例回放 | 合计 26 例，未发现此前修复退回原错误行为 |
| 原始 TeX 包 | 47 个，默认入口，未手工指定 |
| CLI 退出码 0 / 2 / 1 | 29 / 7 / 11，与 08 回复一致 |
| 产物规模 | 12003 个 block，1035 个 section |
| diagnostics | 36，与 08 回复一致 |
| 来源回映检查 | 12003 个块和 8 个条件区间，0 个错误 |
| 中断后目标为空、无关目录、另一份受管理产物 | 均返回 conflict，保留备份；移开冲突目录后能恢复旧 manifest |

本机没有遇到 08 中记录的 pty 环境错误。

29 个退出码 0 是程序判定，不是人工内容金标。7 个 partial 和 11 个失败应保留状态，不能在进入下一阶段时合并为“已成功导入”。这些显式失败不影响先开展成功样本的抽取联调。

## 3. 唯一建议优先补的内容保护

### 混合全局与局部定义时，不要据当前可见值相同就选定文件

**位置**：[assembly.py](../../../qecgraph/source/assembly.py)，`_merge_branches`，第 1343–1365 行，尤其第 1358 行。

实现先比较各分支结束时的可见值，再用“任何一个分支有全局写入”决定把合并结果写入根作用域。当前可见值相同，不代表退出外层分组后的值也相同。

最小案例：

~~~tex
\documentclass{article}
\newcommand{\DIR}{one}
\begin{document}
\begingroup
\ifdefined\flag
  \gdef\DIR{two}
\else
  \def\DIR{two}
\fi
\endgroup
\input{\DIR/frag}
\end{document}
~~~

包内：

| 文件 | 内容 |
| --- | --- |
| one/frag.tex | CORRECT_ONE. |
| two/frag.tex | WRONG_TWO. |

flag 在该来源中未定义，else 的局部定义退出分组后应恢复为 one。即使离线工具不判断 flag，也应保留两个分支退出分组后不同的结果，返回 partial。

**本轮实际结果**：选择 two/frag.tex，document.json 包含 WRONG_TWO，document_complete=true，CLI 退出 0。

另一个变体也已复现：两个分支分别全局定义为 one / three，随后都局部覆盖为 two。合并错误地把当前局部值 two 写成全局值，退出分组后仍选 two。

这两例都直接影响抽取正文，因此保留为必要修正，而不是要求继续完善所有宏语义。

**建议采用小范围保守处理**：

- 判断分支的写入层级和退出分组后的状态是否一致。
- 无法证明一致时，把相应路径标为 uncertain_path / partial，不选一个看似确定的文件。
- 不要求立即精确解释所有条件或宏。
- 增加上述两个直接检查 target 和正文的回归，再跑现有测试与 47 包即可。

## 4. 后续抽取的实用边界

联调时使用已有状态即可：

- 对正文块的 conditional=true 保留条件上下文或进入待确认路径，不把互斥分支直接合成确定主张。
- partial 的内容可供检查或试抽取，但不能据此声称整篇完整。
- 入口歧义、编码和旧 tar 等显式失败，后续按实际遇到的材料逐个处理，不需要现在追求全部自动通过。

本轮确认：少数格式开关后直接跟正文分组的情况，例如 bfseries{正文}、small{公式}，仍可能出现“块标 conditional=true，包却 complete=true”。正文与条件标记都保留了，联调时应以块的条件状态为准，不仅依赖包级 complete。这项检查口径的改进暂不作为本轮阻塞项。

恢复端另有一个维护边界：若中断后人工重建的目标只保留正确的新 manifest，或其他产物缺失/被改写，恢复仍可能判 committed 并清理旧备份。本轮已在临时目录复现；正常转换和已测试的三类目录冲突路径不受这个反例影响。它应留作恢复工具维护项，不阻塞当前抽取联调。

版本标识、旧文档链接和其他未影响本轮抽取联调的问题，不再展开为整改清单。

## 5. 建议下一步

开始后续内容抽取联调，同时补上第 3 节的保守判断。后续修复优先由真实论文中的正文丢失、错误来源、抽取失败或恢复故障驱动，不继续无边界地增加特殊语法探针。

本轮工程检查支持继续推进。内容质量仍需要在实际抽取结果中核对，不以测试数量、块数或 complete 标志替代内容检查。

## 6. 验证记录

实际执行：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reproduce.py \
  --out /tmp/qec-prepare-review4-vssfwe7w/reproduce
~~~

内部执行 python -m unittest discover -s tests -v，452 项测试约 34.15 秒，端到端状态 passed。

47 包逐个执行以下形式，三个并发子进程，每包 60 秒超时；本轮无超时，总耗时约 15.51 秒：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/prepare_arxiv.py \
  "<original-package>" --out "<temporary-root>/all-packages/<case-id>" --json
~~~

| 记录 | 值 |
| --- | --- |
| Python / pylatexenc / jsonschema | 3.15.2 / 2.10 / 4.26.0 |
| SQLite | 3.54.1，FTS5 可用 |
| 样本清单 SHA-256 | 153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b |
| 示例 release | cabac5b60d14515f863018f34b2f5e21baab4f8a07f61ed78def968aec2ff327 |
| 端到端 UTC 起止 | 2026-11-13 09:22:56 至 09:23:31 |
| 临时证据目录 | /tmp/qec-prepare-review4-vssfwe7w |

临时目录保留 reproduce/results.json、synthetic-cases.json、all-packages.json、mapping-checks.json、cli-reproductions.json、recovery-probes.json 及相应探针脚本，可能被系统清理。本报告保留关键结论、输入版本和复现条件。

未执行 TeX/PDF 编译、Docker、Lean 或真实模型；未建立独立人工内容金标，未运行 QEC-database machine 副本的下游检索评测。本轮没有修改导入或解析实现，也没有访问 human、私人笔记或凭据。
