# 准备层架构优化与行为保持验收

> 状态：架构重构与固定语料行为保持验收完成；科学可用性未验收。日期：2026-11-17。

本轮按“保证所有功能不丢失，优化准备阶段架构和功能结合”的要求实施。基线为 `d5b2576`，沿用 [06](06-preserved-reference-ambiguity-acceptance.zh-CN.md) 的 `compile-prepare-v19` 判据：完整保留的交叉引用歧义可以 ready，唯一绑定仍如实标为 partial；缺失目标继续阻断。没有改变准备语义或升级规则，没有重建工作区和下游快照。

## 1. 职责与依赖调整

| 代码 | 当前责任 |
| --- | --- |
| `artifacts.py` | 共用哈希、确定性 JSON、路径检查、原始坐标索引、PDF 文字归一化、已编译书目副本选择 |
| `reference_syntax.py` | 经典书目、Harvmac、引用和作用域适配器共同使用的字面参数读取及来源绑定记录 |
| `execution.py` | 原生命令执行和日志、`Build` 结果、派生构建配置传递、统一 PDF 文字比较 |
| `material.py` | 单次准备的材料、阶段结果、诊断、能力、完成判据与序列化；不编译、不做 I/O |
| `pipeline.py` | 归档和入口、按序调用准备步骤、原文绑定、独立验收和事务发布 |
| `contract.py` | 只读重验材料、来源、层级、引用候选、能力及规范化；不调用原生工具或模型 |

字节投影、原生条件观测和规范化重编译共用 `compile_derived`，沿用同一个 compiler 函数端口，显式传递原引擎与支持目录。BBL/BIB 复用和逐页文字比较也共用实现。原生命令和支持文件优先级、超时、隔离、依赖防改写检查保持原样。

基础工具从高层 contract 中移出，引用词法/记录也从适配器中移出，消除了 `contract → projection → roundtrip → build → contract`、`references ↔ scopes` 等循环。新增架构测试检查所有准备包内部导入，包含函数内延迟导入，并约束纯材料规则与编译/发布的依赖方向。

阶段状态集中在一个 `Material` 实例。编译失败、转换失败和派生构建失败仍保存原有可用材料、阶段结果和诊断；已有 ready 输出的失败重试仍写 `.attempt`。字节投影的来源修饰只做一遍，且保留原有失败前的处理顺序。

| 架构指标 | 基线 | 当前 |
| --- | ---: | ---: |
| 准备包内部循环依赖 | 有 | 无 |
| `pipeline.py` 行数 | 295 | 175 |
| `_material` 编排函数行数 | 146 | 14 |
| 准备包模块数 | 26 | 30 |
| 准备包总行数 | 5316 | 5405 |
| 复杂度超过 10 的既有函数 / 新回退 | 85 / 0 | 85 / 0 |

总行数增加 89 行，来自显式状态和共用边界；没有把“拆文件”描述成整体代码量下降。旧的 `contract` 基础工具导入和 `build.Build/tool/execute` 入口继续可用，CLI、产物 schema 和规则版本保持兼容。对抗测试的私有 mock 目标移到实际原生命令边界，错误/超时/文字不一致的断言未放宽。

## 2. 验收读取的重复计算

性能剖析发现：投影论文一次读取会重复解析同一份投影 JSON 约 12000 次；大论文为 775 条 AUX 标签反复构造 Unicode 字节索引。现在 `_SourceEvidence` 只在当前验收调用中保留来源索引和已解析投影证据；同一文件/编码建一次索引，每个标签仍逐条检查完整定位和复制文字。下一次读取会重新校验当前字节，不使用跨材料或持久缓存。

新增回归构造 200 条真实 AUX 标签，验证同一 AUX 只建一次索引；随后修改 AUX 并刷新 manifest 产物哈希，再次读取仍因来源证据不符而被拒绝。投影来源修饰在单次遍历中复用已解码文字。

同一台 macOS、Python 3.15.2 上读取相同的 v19 保留材料，每篇前后各三次，中位数如下。原始测量保存在 `build/preparation-refactor/{baseline,current}-read-benchmark.json`；没有编译或模型调用。

| 保留材料 | 节点数 | 基线中位数（秒） | 当前中位数（秒） |
| --- | ---: | ---: | ---: |
| `2012.04068v1` | 17006 | 0.481 | 0.495 |
| `2209.05640v1` | 11967 | 1.917 | 0.485 |
| `2411.11822v1` | 8800 | 0.476 | 0.455 |
| `2605.29137v1` | 70128 | 10.943 | 3.135 |

两处重复计算明显的样本读取约快 3.5–4 倍；普通样本有小幅波动。本结果仅覆盖上述材料和本地读取，不能推广为所有 arXiv 包或原生编译速度的承诺。

## 3. 行为保持证据

重构前先提交 v19 产物特征测试，固定以下 10 类场景的全部产物哈希、manifest 和编译次数：普通成功、重复标签、缺失引用、非活动分支、未证实条件、书目、原始编译失败、编译器异常、派生构建失败、字节投影失败。重构后不刷新 fixture，逐字节对照通过。

新增 `tools/compare_preparation.py` 重新打开两组保留回放，比较原始包/来源、投影来源、entry/normalized TeX、来源/规范化映射、引用、覆盖、诊断、语法节点、能力和结果。随机插桩导致的 `build_view_sha256`、原生重编译证据对应的 `source_projection_sha256` 以及原生 PDF/日志字节不作为稳定字节比较项；这些证据仍由每组材料的 contract 分别核验。PDF 负例只比较未准备失败状态，不冒称已有可用正文。

最终代码 `0497f04` 的固定清单 SHA-256 仍为 `153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b`。完整回放与基线一致：

| 指标 | v19 基线 | 当前最终代码 |
| --- | ---: | ---: |
| ready / TeX partial / PDF 预期失败 | 46 / 1 / 1 | **46 / 1 / 1** |
| 原生编译 / 来源保真 / 规范化重编译 | 46 / 46 / 46 | **46 / 46 / 46** |
| 逐页 PDF 文字相等 / 书目完整 | 46 / 46 | **46 / 46** |
| 正文完整 / 交叉引用准备完整 | 46 / 46 | **46 / 46** |
| 唯一交叉引用完整 | 43 | **43** |
| 来源语法 probe | 20/20 | **20/20** |
| 保留材料/负例对照 | — | **48/48 一致** |

47 个 TeX 材料包均重新打开核验；固定 PDF 负例仅验证失败状态。稳定产物对照为 0 差异，ready 增减均为 0。三篇歧义论文的候选和坐标未变化。输出为 `build/preparation-refactor/material-comparison.json`，当前机械验收见 [preparation_acceptance.json](../../../validation/preparation_acceptance.json)。报告同时保留最终执行代码哈希、精确命令、依赖和 machine 失败证据。

## 4. 实际检查与复现

- 基线默认套件：614 tests，OK，跳过 12 个显式启用的原生测试；基线端到端复现通过。
- 当前完整默认套件：622 tests，OK，跳过 12 项；分支覆盖率 84.84%（基线 84.40%）。
- 当前真实 TeX 检查：12/12 通过，含经典书目绑定、隔离、派生文字比较、原生 Harvmac、无效字节投影和原生条件观测。默认对抗测试另外覆盖来源/支持防改写、工具失败和超时；固定语料还有 5 个 Biblatex 材料。
- Ruff 通过；mypy 125 文件通过；Pyright 显式选择 `.venv/bin/python`，0 errors、83 个既有 warnings。重构中出现的一处新增类型提示已修正；最终代码重新进行固定语料回放。
- 复杂度门禁：85 个既有复杂函数，0 新回退；未修改 baseline。
- 文档合同与双语检查：17/17 通过；本轮 8 个非 validation Markdown 文件的 scoped lint 为 0 issues。全树 lint 仍只有旧 review 第 129、137 行的 2 处 MD031，未改旧记录。
- 最终端到端：`build/preparation-refactor/reproduce-verified/results.json` 为 passed，622 tests、4 source files、29 fragments。
- 最终验收报告已生成，并用相同参数加 `--check` 重新核验；稳定材料对照 48/48 一致。

```sh
.venv/bin/python -m coverage run -m unittest discover -s tests -v
.venv/bin/python -m coverage report
QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest tests.integration.pipeline.test_compilation -v
.venv/bin/python tools/reproduce.py --out build/preparation-refactor/reproduce-verified
.venv/bin/python tools/reproduce_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --out build/preparation-refactor/final-verified \
  --entries validation/preparation_entries.json \
  --support-dir build/compile-first/dependencies \
  --support-dir build/compile-first/historical-revtex \
  --cases validation/preparation_cases.json --jobs 2
.venv/bin/python tools/compare_preparation.py --baseline build/preparation-v19/final \
  --current build/preparation-refactor/final-verified \
  --out build/preparation-refactor/material-comparison.json
.venv/bin/python tools/report_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/preparation-refactor/final-verified \
  --cases validation/preparation_cases.json --baseline-revision d5b2576 \
  --machine-evaluation build/preparation-refactor/machine-evaluation.json \
  --out validation/preparation_acceptance.json
# Repeat the report command with --check.
```

## 5. 剩余限制与文件保护

`1804.03719v1` 的旧 RevTeX4/array 原生编译问题仍未解决；`1208.0928v1` 仍为预期 PDF-only 负例。三篇重复标签论文保留全部歧义候选，准备状态与 v19 基线相同。未改变书目歧义和缺失引用的阻断规则，也未增加后续提取或模型处理。

再次对 machine 副本执行固定 release `aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22` 的评测，仍以 exit 1 返回 `Registry state schema mismatch`，前后均未验收。state SHA-256 为 `e9cccd58ebfbbea1a8539d7198c3640a385bdfb2f5bfef95534b74d794cc8a60`，与原库固定 state 字节一致；未修改原库，不读 human、私人笔记或凭据，不调用模型。

Linux/bubblewrap 真实回放、Docker 构建、Lean 验证和后续提取未执行；独立科学金标未验收。全树 Markdown 已有旧 review 的 2 处 MD031 不在本轮修复范围；当前变更另行检查。`docs/reviews/` 的既有文件、`Human.md`、复杂度 baseline 和固定语料清单均保持原样；`Human.md` SHA-256 为 `6a95cc5aeb4a466cb58a9bc2b790319aad729ccd8b53f0733198893820a1630d`。
