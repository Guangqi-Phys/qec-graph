# 2026-11-12 整改验收记录

> 状态：带日期的工程证据；不作为持续有效的能力声明。

对应 [原评审](REVIEW-2026-11-12.zh-CN.md)、[41 项回复](REPLY-2026-11-12.zh-CN.md) 和 [人工交接](HANDOFF-2026-11-12.zh-CN.md)。初始基线 `420a78a`，全量集成验证基准 `210f08d`；之后仅收尾文档。所有初始 reply 已在 `9b3bd78` 提交，先于代码修改。原评审未改写。

## 执行环境与范围

使用仓库 `.venv/bin/python`：Python 3.15.2、SQLite 3.54.1、pylatexenc 2.10、jsonschema 4.26.0；平台 `macOS-27.2.1-arm64-arm-64bit-Mach-O`。机器实际信息来自 reproduce 报告，不推断其他平台通过。

真实工作区只使用临时 machine 副本 `/tmp/qec-review-real/machine`，固定 release `aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22`。没有读取真实配置、human 或私人笔记，没有修改原库、调用在线模型或重绑旧审核。报告写入仓库 `build/review/`，重解析 store 写入副本之外的临时目录。

## 实际命令与结果

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m coverage run -m unittest discover -s tests -v` | 425 tests，47.398 s，全部通过；初始基线 400 tests / 46.554 s |
| `.venv/bin/python -m coverage report` | 总覆盖率 83.10%，开启分支覆盖，80% 门禁通过 |
| `.venv/bin/python tools/reproduce.py --out build/reproduce` | passed；包含 425 tests、来源/带注解 graph、SQLite 搜索及 context 检查 |
| `.venv/bin/python -m ruff check qecgraph tests tools` | 通过 |
| `.venv/bin/python tools/check_complexity.py` | 89 个历史 >10 函数，无新增/增长回归；不是复杂度债务清零 |
| `.venv/bin/python -m mypy` | 配置内 92 个源码文件通过；逐模块收紧 |
| `.venv/bin/python -m pyright --pythonpath .venv/bin/python` | 0 errors / 92 warnings；明确使用正确解释器，未关闭规则 |
| `.venv/bin/python -m mypy --check-untyped-defs` | 诊断检查未通过：105 errors / 26 files，记录 F1 人工债务；不是正式门禁通过项 |
| `.venv/bin/python -m unittest discover -s tests/contracts/docs -v` | 16 项通过；双语标题/表格/示例、链接和命令契约 |
| `npx --offline --cache /tmp/qec-review-npm --yes markdownlint-cli2@0.20.0` | 通过；仅原始评审作为不可改写输入排除，reply/交接/验收仍检查 |

首轮集成测试暴露的旧 fixture/兼容问题已单独修复提交：legacy_import 的 state 契约、typed assumption 的 candidate 断言、fake-provider 上传授权、工具 `--help`。最终重跑通过。未经显式指定解释器的 pyright 曾误用系统环境；最终结果使用上表命令。

## 真实论文评测

执行：

```sh
.venv/bin/python tools/eval_retrieval.py --machine /tmp/qec-review-real/machine --release aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22 --cases validation/retrieval_qa.json --out build/review/retrieval-real.json
.venv/bin/python tools/reproduce_knowledge.py --machine /tmp/qec-review-real/machine --release aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22 --out build/review/knowledge-real.json
```

八问检索集绑定五篇真实论文的原始文件哈希与码点范围，dataset SHA-256 `b6d2f50612a0f4b415d4a748361dee303fa2511d0fecc2beb0a812ac57a46b6d`。锚点在看过检索片段后选定，属于工程 smoke，**不是独立科学金标**。比较同一当前代码、固定 release 和候选集的 literal/BM25，不能描述为历史代码回放。

| 方法 | recall@5 | recall@10 | MRR@10 | 五条精简响应字符中位数 | 延迟中位数 | 工具失败 |
|---|---|---|---|---|---|---|
| literal | 0.125 | 0.125 | 0.125 | 612 | 51.27 ms | 0 |
| BM25 keyword | 0.875 | 0.875 | 0.6875 | 2366.5 | 64.81 ms | 0 |

与相关噪声排名有关的一题仍未召回。literal 的较小返回体主要是空结果，不能据此断言其效率更高。延迟是这次本机运行值，没有规模/并发外推。

直接阅读/搜索读取/任务上下文检查共 10 个来源探针、50 次工具调用，三个路径分别找到 10/10 所要求的证据段落，tool/baseline errors 均为 0。探针由已登记来源选择，查询使用来源文字，只证明来源传递机制；没有评估自然语言答案正确性。

另执行 `.venv/bin/python /tmp/qec-review-reparse.py`，用固定 release 的已登记 TeX 来源重新建立五个临时 store，并调用 `validate_snapshot`。五份新快照的完整性检查通过，合计产生 5 个 abstract、5 个 algorithm、104 个 bib_entry、5 个 title、16 个 author_block。该检查不是完整归档重导入：machine 的来源镜像未带入全部外部图像资源，仍报告 missing_resource，以及宏、条件、重复标签和未解析引用限制；不把有诊断的抽取称为完整解析。原 release 没有改动。

## 产物与未完成范围

原始 JSON 报告保留在本地（未提交论文原文或运行日志）：

| 本地产物 | SHA-256 |
|---|---|
| `build/reproduce/results.json` | `62e4366651814234c279f31af5dd93a3f4ea8d7f1a2fd1a2c9c63c72a0f5a2dd` |
| `build/review/retrieval-real.json` | `7ec2571032898ea2c025a81d343a39606305143790683f7b4e7478dc8e0de516` |
| `build/review/knowledge-real.json` | `d64e64e2bb56d71afffe49b260c55f78f223c70462c442df34f422ef31feeeca` |
| `build/review/reparse-real.json` | `96eeeb68a66f9eefeb57d160e1bb1fab836585727b2722abcc90ed913c2ebef9` |

41 项的状态、首个独立 commit 和逐项结果见 REPLY。实体归并/自动 research 转换、旧接口与 Lean 退役、紧凑存储/GC/分片 state、两阶段 AI 发布、长论文分块、人工认证和独立科学 QA 仍按 HANDOFF 处理。代码和文档修复没有填充或晋级真实库中的候选记录。

未执行：Docker/OS 隔离部署、Lean/lake、公理审计、在线 AI/embedding/缓存收益、联网六篇 pinned golden、GitHub Python 3.11/3.13 × Ubuntu/macOS 远端矩阵、500 篇规模测试及人工科学验收。没有创建 release/tag。将这些未执行项写清楚，不把工作流配置或本地结果当成远端通过证据。
