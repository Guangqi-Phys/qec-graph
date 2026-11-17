# 离线 prepare 推送前复核摘要

> 日期：2026-11-13。实现基线：`49053ad`。对应 [10：第四轮整改回复](10-reply-to-review-09.zh-CN.md)。本次按“可用、稳定”的标准复核，不扩展新的语法边界。

## 1. 结论

没有发现阻止当前版本提交和进入内容抽取联调的大问题。前次优先项已经修复，真实样本包没有出现可观测回退。本次不修改实现代码；将全部 review 按现有日期目录提交，修复 02/03 的三处旧链接，并更新文档入口。

本结论适用于离线预处理和下一步抽取联调，不代表所有 LaTeX 包都能完整转换，也不代表下游知识质量已经验收。

## 2. 实现复核

- 混合全局/局部宏定义、全局值被局部遮蔽的两个案例均返回 `uncertain_path`，CLI 退出码为 2；不再误选 `two/frag.tex`。
- `\bfseries{正文}`、`\relax{正文}`、`\small{公式}` 的不确定条件内容均使结果降为 partial，原文与条件标记保留。
- 发布中断后，目标只有 manifest、缺少 `document.json` 或文档内容被改写，均返回 conflict 并保留 backup/journal；移开冲突目标后可以恢复旧版本。
- 26 个历史案例与上一轮输出逐项相同。恢复探针共 7 种状态：正常恢复成功，其余 6 种冲突均保留备份并在移开冲突目标后恢复成功。

继续接受 [09 的实用边界](09-practical-review-of-08.zh-CN.md)：例如布局命令后紧跟正文分组的案例，包级 complete 仍可能偏宽，但正文保留且块标为 `conditional=true`。本轮不将其升级为阻塞项；下游读取时仍须保留条件上下文，不能只凭 complete 判定数学内容可靠。

## 3. 验证结果

| 检查 | 结果 |
| --- | --- |
| 全量测试与端到端复现 | `tools/reproduce.py` passed；456 项测试全部通过，本环境无 pty 错误 |
| 47 个真实来源包 | 完整 29、partial 7、明确拒绝处理 11；退出码分布 0/2/1 与上一轮一致 |
| 文档结构 | 12003 个 block、1035 个 section、36 条 diagnostic，与上一轮一致 |
| 来源映射 | 36 份输出的字节拼接、12003 个 block 的来源及字符/字节坐标、8 个条件区间均通过核对 |
| 历史案例 | 26 个案例输出无变化 |
| 恢复案例 | 7 种中断/冲突状态符合预期 |

样本清单 SHA-256：`153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b`。逐包检查原始 SHA-256，PDF 对照包不计入上述 47 包。运行环境为 Python 3.15.2、macOS arm64、pylatexenc 2.10。

本次实际执行的核心命令：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reproduce.py \
  --out /tmp/qec-prepush-20261113-djRbSL/reproduce

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python \
  /tmp/qec-prepare-review4-vssfwe7w/probe.py /tmp/qec-prepush-20261113-djRbSL
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python \
  /tmp/qec-prepare-review4-vssfwe7w/recovery_probe.py /tmp/qec-prepush-20261113-djRbSL
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python \
  /tmp/qec-prepare-review4-vssfwe7w/validate.py /tmp/qec-prepush-20261113-djRbSL
~~~

三个临时脚本沿用上一轮探针；结果保存在本机临时目录，不作为仓库中的持久测试资产。仓库回归测试包含本轮宏作用域、格式开关与恢复修复的用例。

未运行模型、TeX/PDF 编译、Docker 或 Lean；未修改原始来源包或 QEC-database。下游机器库的检索评测和人工内容金标仍未验收，后续改进由真实抽取失败驱动。
