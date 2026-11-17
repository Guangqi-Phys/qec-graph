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

当前[准备验收报告](preparation_acceptance.json)在 `compile-prepare-v10` 下记录
47 篇 TeX 和一个 PDF 反例：46 篇可编译（45 篇有非空语法），45 篇文献绑定完整，
41 篇满足全部准备判据，其余 6 篇 TeX 保持 partial 并逐篇列出原因。
45 份派生 LaTeX 可重新编译且逐页去空白 PDF 文字相同，44 份通过完整统一格式阶段。
新规则覆盖 TeX 参数空白归一化的 key、经 AUX 确认的环境 `label=...` 选项、
唯一受条件包裹的文档边界、绘图内部条件，以及有构建证据的大小写资产匹配；
最后一种明确依赖大小写不敏感文件系统，不能声称可移植。
五篇论文的 20 个来源绑定语法检查通过；这是机械检查，不是独立人工金标。
三个显式入口配置保存在 `preparation_entries.json`，历史 TeX 依赖的 URL/哈希和命令
写在报告里。固定 machine 的评测因注册表 schema 不兼容而未验收。
原始数据库和 Human.md 均未修改。

`validation/retrieval_qa.json` 包含八道绑定评审中五篇论文固定来源的工程问题。
锚点在查看检索片段后选择，所以这是导航 smoke，不是独立相关性金标。运行
`python tools/eval_retrieval.py --machine /path/to/copied-machine --cases validation/retrieval_qa.json --out build/retrieval-eval.json`。
脚本在同一当前实现上比较 literal/BM25，输出 recall@5/10、reciprocal rank@10、
紧凑响应字符数、延迟和失败；不调用模型、不包含 AI 提议。50 道人工审核的科学问题
和各 skill 精确率样本仍待完成。

复杂度回归门禁为 `python tools/check_complexity.py`；修改
`validation/complexity_baseline.json` 必须明确评审。基线记录旧债务，不代表现有函数简单。
准备报告包含 16 个遗漏旧复杂度上限的明确评审：逐项对照起始版本 `3ef28ae`，
没有放行复杂度增长。新增编译/准备函数的复杂度均不超过 10。

## 添加证据

把新日志或报告附在产生它的 release/CI 运行上；或者仅在该版本仍是当前版本时
新增版本化目录。不要把旧报告复制到新版本，也不要修改已记录的结果来匹配新代码。
