# 验证证据

> **状态：当前（0.6.x）。** 这里是可执行检查的索引，不是历史运行归档。

> **中文** · [English](README.md)

仓库不再携带历史运行产物。早期 release 的证据保留在 Git history；本目录只保留
当前检查和明确限定范围的验收结果，避免把过期报告误当成对当前代码的结论。

## 当前检查

| 检查 | 命令 |
|---|---|
| 单元、集成和契约测试 | `python -m unittest discover -s tests` |
| 编译优先准备，零模型 | `python tools/reproduce_preparation.py --manifest test-sources/arxiv-sources/manifest.json --out build/preparation-replay --entries validation/preparation_entries.json --cases validation/preparation_cases.json` |
| 重算/检查准备验收 | `python tools/report_preparation.py --manifest test-sources/arxiv-sources/manifest.json --replay build/preparation-replay --cases validation/preparation_cases.json --out build/preparation-acceptance.json --check` |
| 端到端抽取和查询复现 | `python tools/reproduce.py --out build/reproduce` |
| 直接阅读 / 搜索 / 任务上下文证据 | `python tools/reproduce_knowledge.py --out build/knowledge-synthetic.json --include-payloads` |
| 已登记真实来源阅读（只读） | `python tools/reproduce_knowledge.py --machine /path/to/machine --out build/knowledge-real.json --include-payloads` |
| Workspace、MCP 和隔离检查 | `python tools/reproduce_workspace.py` 和 `python tools/reproduce_mcp.py` |
| 发行分发包 | `python -m build` 后运行 `python tools/check_distribution.py dist/` |
| 发行二进制 | `Standalone Release` GitHub workflow |
| AI 配置与 provider 探针 | `qec-graph ai status` 和 `qec-graph ai test` |
| AI proposals | `qec-graph ai proposals --json` |

检查只对实际运行它的源码修订和环境构成证据。测试通过不代表论文定理为真、
距离界已被数学验证，或 Lean 声明已语义匹配。

当前[准备验收报告](preparation_acceptance.json)由完整 `compile-prepare-v19` 回放自动生成，
逐包重新打开材料、重算计数和来源绑定语法 probe，并核对语料/代码快照。
先运行不带 `--check` 的 `report_preparation.py` 生成报告，再用相同参数加 `--check`
检查漂移；检查不编译、不调用模型。已提交报告的 `replay.argv` 保存实际支持文件路径、
入口和 probe 配置；比较基线固定为 v18 的 `ff69adf`。原生工具结果保留在材料包中，
不会复制旧测试套件的通过声明。

固定语料为 47 篇 TeX 和一个 PDF 反例；v19 为 46 ready、1 篇 TeX partial、
1 个预期 PDF 失败。新增 ready 的三篇保留引用歧义，唯一引用绑定数没有增加；报告另列正文完整数、可逆投影数和原生方言。
覆盖数和失败原因是机械准备证据，
不是科学答案金标或数学验收。[06 总结](../docs/reviews/review-2026-11-17-compile-prepare-testing/06-preserved-reference-ambiguity-acceptance.zh-CN.md)
记录可比前后数字、实际检查、依赖来源及未完成事项。大小写资产匹配仍不能声称可移植到
大小写敏感文件系统。固定 machine 副本评测仍因注册表 schema 不兼容而未验收。
Human.md 和原始数据库均未修改。

`validation/retrieval_qa.json` 包含八道绑定评审中五篇论文固定来源的工程问题。
锚点在查看检索片段后选择，所以这是导航 smoke，不是独立相关性金标。运行
`python tools/eval_retrieval.py --machine /path/to/copied-machine --cases validation/retrieval_qa.json --out build/retrieval-eval.json`。
脚本在同一当前实现上比较 literal/BM25，输出 recall@5/10、reciprocal rank@10、
紧凑响应字符数、延迟和失败；不调用模型、不包含 AI 提议。50 道人工审核的科学问题
和各 skill 精确率样本仍待完成。

复杂度回归门禁为 `python tools/check_complexity.py`；修改
`validation/complexity_baseline.json` 必须明确评审。基线记录旧债务，不代表现有函数简单。
当前门禁保留 85 个复杂度超过 10 的历史函数，没有新增回归。此前 16 个遗漏上限的
明确评审保留在 `59a0b9f:validation/preparation_acceptance.json`，不冒充本次的新验收。
新增编译/准备函数的复杂度均不超过 10。

## 添加证据

把新日志或报告附在产生它的 release/CI 运行上；或者仅在该版本仍是当前版本时
新增版本化目录。不要把旧报告复制到新版本，也不要修改已记录的结果来匹配新代码。
