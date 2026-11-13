# 离线 prepare 第四轮整改回复

> 对应 [09：08 实现的可用性复评](09-practical-review-of-08.zh-CN.md)。整改基线 `85cd8e30df9dcdec2247385e231ee4a1b51ea966`，完成提交 `49053ad`（本轮三个提交已推送到 `origin/main`）。状态：09 §3 的优先项与 §4 的两个已复现边界均已修复；其余限制按 09 的建议保留，不再作为进入抽取联调前的阻塞项。

本文件只记录本轮整改；没有修改 01–09 的正文，没有修改原始论文包或 QEC-database。09 的三个内容案例与恢复边界均已复跑，见 §3。

## 1. 结论

- 09 的判断准确：08 可以进入内容抽取联调；唯一应优先补的是混合全局/局部定义的分支合并。
- 除优先项外，09 §4 指出的两个已复现边界（`\bfseries{...}` 条件内容计数、恢复只校验 manifest）也已修复；它们不是新语法探针，都是会让“错误内容被判 complete”或“删除唯一旧备份”的实际缺口。
- 47 包退出码保持 29/7/11；block 12003、section 1035、diagnostics 36 均不变。
- 全量测试 452 → 456 项；本机仍只有 2 个 pty 环境错误。

## 2. 逐项回应

### 2.1 混合全局与局部定义（09 §3，优先项）

**复评判断：成立。** 旧合并先比较各分支结束时的可见值，再根据“任一分支有全局写入”把结果写入根作用域；可见值相同不等于退出外层分组后的值相同。

**实施**（`_merge_branches`）：

- 无全局写入的分支仍只合并可见值：全部分支相同确定字符串则保留，全部未定义则不写入，否则 `UNCERTAIN`。
- 有全局写入时，额外要求每个分支的**根作用域值**和**可见值**都等于同一个确定字符串，才把该值写入根作用域并清除局部遮蔽；否则把根和当前可见值都标为 `UNCERTAIN`。
- 09 的两个案例（`gdef` + `def` 混合、两分支 `gdef` 后局部覆盖）现在都是 `uncertain_path`、partial，不再选 `two/frag.tex`。
- 回归直接检查 target、正文和 complete：`mixed_global_and_local_branch_definitions_stay_uncertain`、`global_then_local_branch_values_do_not_become_global`、`test_mixed_branch_scopes_do_not_pick_a_file`。

### 2.2 格式开关后的正文分组（09 §4）

**复评判断：成立。** `\bfseries{FIRST_BRANCH}` 的 `{...}` 被当成格式开关的参数跳过，条件内容计数为 0，包仍 complete。

**实施**：格式开关本身不接参数，只跳过控制词本身；布局命令（`\vspace`、`\setlength` 等）仍跳过其参数。`\bfseries{...}`、`\small{公式}` 现在按可见内容处理，条件结果 partial。回归：`test_formatting_switch_with_a_body_group_makes_the_conditional_partial`。

### 2.3 恢复只校验 manifest（09 §4）

**复评判断：成立。** 中断后人工重建的目标如果只复制了正确的新 manifest，其他产物缺失或被改写，恢复仍判 committed 并删除旧备份。

**实施**：

- journal 记录每个产物的 SHA-256。
- 恢复判 committed 前要求 manifest 与所有产物摘要都匹配预期新版本；任一缺失或不一致则 `conflict`，保留 journal 与 backup。
- 回归覆盖“目标只有正确 manifest”的状态：冲突保留 backup，移开目标后可恢复旧 manifest。
- 文档同步说明：committed 需要完整的新产物，不只是 manifest。

## 3. 复跑结果

| 案例 | 09 基线 | 当前 |
| --- | --- | --- |
| 混合 `gdef`/`def`（flag 未定义） | 读 `two`，complete | 无 target，partial |
| 两分支 `gdef` 后局部覆盖 `two` | 读 `two`，complete | 无 target，partial |
| `\bfseries{FIRST_BRANCH}` 条件 | complete，内容计数 0 | `conditional_body`，partial |
| 中断后目标只含正确新 manifest | committed，backup 被删 | conflict，backup/journal 保留 |
| 09 引用的其余 26 个旧案例 | 通过 | 通过 |

## 4. 测试与语料

- 全量测试 **456** 项（+4），本机 2 个错误仍为 pty 环境问题，其余通过。
- 47 包：退出码 **29/7/11** 不变；block **12003**、section **1035**、diagnostics **36** 不变。
- 09 的实用边界接受：`conditional=true` 的块保留条件上下文，partial 内容可供检查或试抽取，不以包级 complete 或块数替代内容核对。

## 5. 仍未完成（按 09 建议不再阻塞联调）

- 阅读文本仍保留 `\ifdefined`/`\else`/`\fi`；条件不确定性通过 `conditional` 与 `conditional_ranges` 表达。
- assembly 的 `_scan` 仍读原始 entry；被拼接注释遮住的指令不会展开，但 parser 读到的外部内容会触发 `include_outside_entry` 并降级。
- `\ifcase` 不按值选择，不同值一律不确定。
- 条件配对与自定义 `\if...` 宏的识别仍是启发式；无法配对时报告 `unclosed_conditional`。
- 未建立人工内容金标、未执行 TeX/PDF 编译、Docker、Lean 或真实模型；下游 QEC-database 检索评测仍未验收。
- 02/03 的三处旧链接仍待一次只改链接的提交。

## 6. 提交与复现

| 提交 | 内容 |
| --- | --- |
| `cdfc3e0` | 分支合并要求全局值与可见值一致 |
| `d828b19` | 格式开关后的分组计入条件内容 |
| `49053ad` | 恢复校验全部产物摘要 |

本机执行：

~~~sh
# 全量测试：456 项，2 个 pty 环境错误
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests

# 09 内容案例与恢复边界：按 09 的步骤构造
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/prepare_arxiv.py \
  --out /tmp/prepared/paper --recover --json
~~~

47 包对比仍为一次性探针；后续修复按 09 的建议，由真实论文中的正文丢失、错误来源或恢复故障驱动，不再无边界增加语法探针。

## 7. 文档说明

本回复为第 10 份文件，沿用 `0N-...` 的顺序；没有改动 01–09 的正文。
