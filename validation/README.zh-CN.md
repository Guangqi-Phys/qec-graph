# 验证证据

> **状态：当前（0.6.x）。** 这里是可执行检查的索引，不是历史运行归档。

> **中文** · [English](README.md)

仓库不再携带历史运行产物。早期 release 的证据保留在 Git history；本目录只保留
当前索引，避免把过期报告误当成对当前代码的结论。

## 当前检查

| 检查 | 命令 |
|---|---|
| 单元、集成和契约测试 | `python -m unittest discover -s tests` |
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

`validation/retrieval_qa.json` 包含八道绑定评审中五篇论文固定来源的工程问题。
锚点在查看检索片段后选择，所以这是导航 smoke，不是独立相关性金标。运行
`python tools/eval_retrieval.py --machine /path/to/copied-machine --cases validation/retrieval_qa.json --out build/retrieval-eval.json`。
脚本在同一当前实现上比较 literal/BM25，输出 recall@5/10、reciprocal rank@10、
紧凑响应字符数、延迟和失败；不调用模型、不包含 AI 提议。50 道人工审核的科学问题
和各 skill 精确率样本仍待完成。

复杂度回归门禁为 `python tools/check_complexity.py`；修改
`validation/complexity_baseline.json` 必须明确评审。基线记录旧债务，不代表现有函数简单。

## 添加证据

把新日志或报告附在产生它的 release/CI 运行上；或者仅在该版本仍是当前版本时
新增版本化目录。不要把旧报告复制到新版本，也不要修改已记录的结果来匹配新代码。
