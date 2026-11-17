# 保留引用歧义的准备完成判据

> 状态：实现与固定语料复验完成，46 ready / 1 partial；科学可用性未验收。日期：2026-11-17。

本轮依据用户明确决定：“保留歧义就好了，这种引用歧义视为准备完成”。承接 [05 总结](05-native-dialects-byte-projection-and-capabilities.zh-CN.md)，只调整 preparation 的完成边界，不替作者消歧，不开发后续提取，不调用模型。旧 review 记录保持原样。

## 1. 判据和代码边界

规则提升为 `compile-prepare-v19`，新材料写入 `cross_reference_policy=preserve_ambiguity/1`。

1. 先原生编译，再进行原有来源映射、结构转换、书目适配、规范化重编译与保真检查；这些判据不变。
2. 支持的交叉引用存在多个已定位候选时，保留 `status=ambiguous`、全部节点/外部目标、key 和原始来源位置，不选第一个、不按编译排版结果猜唯一目标。
3. `cross_reference_ambiguous` 写入 `coverage.observations` 和 `manifest.warnings`，不再单独阻止 conversion complete 或 overall ready。
4. `cross_reference_preparation=complete` 表示支持的正文引用已唯一绑定，或已完整保留歧义候选；`cross_reference_bindings=partial` 仍如实说明并非全部引用唯一绑定。已有 `unresolved_cross_references` 兼容字段仍列出所有非唯一引用，包括 ambiguous。
5. 目标不存在的 `unresolved` 继续产生阻断诊断；书目 key 冲突/缺失、编译失败、未知语法、未映射条件、来源保真失败和规范化失败不放宽。此决定仅适用于已识别的交叉引用候选歧义。
6. 只读验收重新从保留的语法节点、声明和 AUX 证据重建候选，比较全部标签与引用；删除候选、伪造 resolved 后刷新产物哈希也不能通过。Harvmac 沿用自己的独立语法/候选核验。ready 材料仍不允许缺失目标。
7. 无新策略字段的旧材料按原版本读取，能力字段不自动补写或升级。已实际重新打开 v18 的 `2012.04068v1`：保持 partial 和原分项能力。

`convert.py` 负责观测和阻断诊断的区分，`crossrefs.py` 保留并核验全部候选，`capabilities.py` 区分准备与唯一绑定，`pipeline.py` 按原阶段条件发布，`acceptance.py` 生成机械证据。没有新增模型或下游科研语义处理。

## 2. 固定语料前后对照

基线为 `ff69adf` 提交的 v18 验收报告：43 ready / 4 partial，另有 1 个预期 PDF-only 失败。执行代码提交为 `8cc1d99`。固定清单仍为 47 篇 TeX 和 1 篇 PDF，SHA-256 为 `153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b`。

| 指标 | v18 基线 | v19 完整回放 |
| --- | ---: | ---: |
| ready | 43 | **46** |
| partial（TeX） | 4 | **1** |
| failed（PDF 负例） | 1 | **1** |
| 原生编译成功 | 46 | **46** |
| 非空语法且来源保真通过 | 46 | **46** |
| 正文语法完整 | 46 | **46** |
| 书目绑定完整 | 46 | **46** |
| 交叉引用唯一绑定完整 | 43 | **43** |
| 交叉引用准备完整（新分项） | 未单列 | **46** |
| 完整 normalization / 重编译 / 逐页文字相等 | 46 / 46 / 46 | **46 / 46 / 46** |
| 来源语法 probe | 20/20 | **20/20** |

47 个 TeX 材料均重新打开核验，ready 回退为 0；三篇歧义论文已实际重新准备并核对：

| 论文 | 保留的歧义 key | v18 → v19 |
| --- | --- | --- |
| `2012.04068v1` | `lm:alpha-beta-exp` | partial → ready |
| `2102.06132v1` | `fig:bitfliplep`、`pij-approx` | partial → ready |
| `2308.07915v2` | `ABC2`、`alpha_beta_gamma_delta` | partial → ready |

三篇的完整 `labels`、`cross_references` 与 v18 逐项相同，来源树哈希相同；候选与引用位置没有被修改，唯一绑定仍为 partial。对照保存在本地 `build/preparation-v19/ambiguity-comparison.json`。ready 增加来自用户确认的准备完成判据变化，不能宣称解决了作者意图歧义。

## 3. 实际验证

- 默认全套：`.venv/bin/python -m coverage run -m unittest discover -s tests -v`，614 tests，OK，跳过 12 个显式启用的原生 TeX 测试；分支覆盖率 84.40%，v18 为 84.39%。
- 原生编译：`QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest tests.integration.pipeline.test_compilation -v`，12/12 通过。新增真实重复标签样本 ready，保留两个候选，规范化前后逐页文字相同，原始字节相同。
- 新增缺失目标与歧义并存的阻断回归，以及删除候选/伪造唯一状态、刷新哈希仍被拒绝的回归；原有 Harvmac 重复公式回归继续验证原公式字节与全部候选。
- Ruff 通过；mypy 121 文件通过；Pyright 使用 `--pythonpath .venv/bin/python`，0 errors、83 个既有 warnings。未指定解释器的首次检查有 14 个依赖解析错误；显式选择已安装依赖的解释器后消除，没有屏蔽错误或降低规则。
- `python tools/check_complexity.py`：85 个既有复杂函数，0 新回退；未改 complexity baseline。
- `python tools/reproduce.py --out build/preparation-v19/reproduce`：端到端通过，614 tests、4 source files、29 fragments。
- 文档检查：`python -m unittest tests.contracts.docs.test_docs tests.contracts.docs.test_docs_bilingual -v`，17/17 通过。
- 本轮 10 个非 validation Markdown 文件按 `markdownlint-cli2 --no-globs` 检查，0 issues；validation 文档由文档测试覆盖。全树 lint 仍只有旧 review 的 2 处 MD031（`review-2026-11-16-arxiv-prepare-2/01-implementation-review.zh-CN.md` 第 129、137 行）；按永久保留要求不修改旧记录。
- 验收报告已通过完整回放生成，随后用同一参数加 `--check` 独立重开全部材料核验；结果记录在 [当前机械验收报告](../../../validation/preparation_acceptance.json)。

真实语料回放命令：

```sh
.venv/bin/python tools/reproduce_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --out build/preparation-v19/final \
  --entries validation/preparation_entries.json \
  --support-dir build/compile-first/dependencies \
  --support-dir build/compile-first/historical-revtex \
  --cases validation/preparation_cases.json --jobs 2
.venv/bin/python tools/report_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/preparation-v19/final \
  --cases validation/preparation_cases.json --baseline-revision ff69adf \
  --machine-evaluation build/preparation-v19/machine-evaluation.json \
  --out validation/preparation_acceptance.json
# Repeat the report command with --check.
```

支持目录沿用 v18 的本地固定文件及实际搜索顺序，没有下载或改写系统 TeX；每个构建保留实际消费依赖的路径和哈希。原始来源不改写。

## 4. 未完成与保护范围

`1804.03719v1` 仍因旧 RevTeX4/array 原生构建失败而 partial：当前日志在 `Eidenbenz_intro.tex:65` 报 `Extra \or`，没有有效原生 PDF。本轮没有改作者源码或更换文档类。`1208.0928v1` 仍为 PDF-only 预期负例；这条 TeX 准备路线不提供 PDF OCR。三篇引用歧义继续存在，按本轮确认的边界已经准备完成。

固定 machine 副本再次运行 `reproduce_knowledge.py`，release 为 `aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22`，仍以 exit 1 返回 `Registry state schema mismatch`，因此未验收。副本 state SHA-256 为 `e9cccd58ebfbbea1a8539d7198c3640a385bdfb2f5bfef95534b74d794cc8a60`，与原库的固定 state 字节一致；没有修改原库或读取 human/私人笔记/凭据，没有模型请求。

Linux/bubblewrap 真实回放、本语料以外的通用适配、独立科学金标和后续提取均未验收。准备完成不表示科学结论正确，也不表示作者意图已经消歧。大小写资产匹配的可移植性限制仍保留。

`Human.md` SHA-256 保持 `6a95cc5aeb4a466cb58a9bc2b790319aad729ccd8b53f0733198893820a1630d`。`docs/reviews/` 既有文件、固定语料清单、原始论文和 complexity baseline 均未修改。代码与文档分步提交，最终推送 main。
