# TeX 编译优先准备：剩余 10 篇 partial 诊断与 `compile-prepare-v10` 改进报告

> 状态：诊断、规则改进与固定语料回放已完成；科学可用性未验收。日期：2026-11-17。相关记录见 [02-test-implementation-and-verification.zh-CN.md](02-test-implementation-and-verification.zh-CN.md)。

本文检查固定公开语料中 47 篇 TeX 输入和 1 篇 PDF 反例的准备结果，解释剩余 10 篇 TeX 论文为什么没有达到 `ready`，记录本轮 `compile-prepare-v10` 的安全改进、回放数字和仍然存在的实现问题。范围是离线的编译优先材料准备，不包含科学抽取、模型调用、工作区迁移或原始数据库写入。

## 目录

- [1. 结论与计数](#1-结论与计数)
- [2. 10 篇逐项诊断](#2-10-篇逐项诊断)
- [3. 本轮实现改动](#3-本轮实现改动)
- [4. 当前实现仍然存在的问题](#4-当前实现仍然存在的问题)
- [5. 验证与证据](#5-验证与证据)
- [6. 边界与未验收](#6-边界与未验收)

---

## 1. 结论与计数

固定清单 SHA-256 为 `153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b`。同一批输入、入口配置、支持文件和判据下，`compile-prepare-v10` 相比上一版的结果：

| 指标 | 改进前 | 改进后 | 说明 |
| --- | ---: | ---: | --- |
| `ready` | 37 | **41** | 新增 4 篇，无 ready 回退 |
| `partial` | 10 | **6** | 剩余 6 篇均有明确阻断原因 |
| `failed` | 1 | 1 | PDF-only 反例 `1208.0928v1`，预期配置失败，不属于 10 篇 TeX partial |
| 原生编译成功 | 46 | 46 | 47 篇 TeX 中仅 `1804.03719v1` 失败 |
| 非空语法树 | 45 | 45 | `1804.03719v1` 无编译产物 |
| 文献绑定完整 | 45 | 45 | `1804.03719v1`、`2209.05640v1` 未完成 |
| 派生 LaTeX 重编译 | 45 | 45 | 使用原引擎和支持文件 |
| 派生 LaTeX 逐页 PDF 文字相等 | 45 | 45 | 去空白后的页面文字比较，不是像素或数学等价 |
| `normalization` 完整 | 44 | 44 | `hep-th/9407087v1` 仍为 partial Harvmac 语法 |
| 来源语法 probe | 20/20 | 20/20 | 机械检查，不是人工科学金标 |

这 10 篇是 TeX 输入中的 `partial`；`1208.0928v1` 是单独的 PDF 反例，不能把“10 篇没通过”和它混为一谈。

## 2. 10 篇逐项诊断

| 论文 | 原状态 | 现状态 | 直接原因 | 本轮处理 |
| --- | --- | --- | --- | --- |
| `2111.05176v1` | partial | **ready** | 源码引用 `figs/bp_plot.png`，包内实际为 `figs/BP_plot.png` | 仅当构建 FLS 实际消费该路径时接受大小写不敏感匹配，记录 `asset_case_mismatch` |
| `2411.11822v1` | partial | **ready** | `\ifx\compilefullpaper\undefined` 包住 `\documentclass`、`\begin{document}`、`\end{document}`；严格扫描跳过不可判定分支后找不到正文 | 唯一文档标记对回退；保留 guard 不选正文分支；已组装的 setup-guard include 降级为观测 |
| `2605.29137v1` | partial | **ready** | 39 个引用指向 tcolorbox 的 `\begin{defbox}[label={...}]` 选项；另有 `tikzpicture` 内 `\ifodd\i` 绘图循环 | AUX 唯一确认的环境选项标签；绘图条件归为 `drawing_payload`，保留原文且不阻断阅读 |
| `2605.29554v1` | partial | **ready** | `\label{eq:resolved  system1_1}` 使用双空格，引用使用单空格 | 按 TeX 参数词法折叠连续空白后匹配 |
| `2012.04068v1` | partial | partial | 两个相邻 lemma 都使用 `\label{lm:alpha-beta-exp}`，引用本身有歧义 | 明确报 `cross_reference_ambiguous` 并列出 key；保留双目标，不任选一个 |
| `2102.06132v1` | partial | partial | `fig:bitfliplep` 重复两次，`pij-approx` 在正文和 supplement 各一次；`fig:my_label` 出现四次但未被引用 | 同上；重复标签只作为观测，不静默丢弃 |
| `2308.07915v2` | partial | partial | 正文与 supplement 重复 `ABC2`、`alpha_beta_gamma_delta`；`\ifdefined\maindocument` 的非活动 standalone 分支还有缺失的 `packages.tex`，guard 未映射 | 保留歧义；未对 `\ifdefined` 做源码级真假绑定，因此缺失 include 仍阻断 |
| `1804.03719v1` | partial | partial | 旧 RevTeX4 与当前 `array` 组合在 `Eidenbenz_intro.tex:65` 报 `Extra \or` | 未改源码、未做通用回滚；需要匹配的历史 class/TeX Live 集 |
| `2209.05640v1` | partial | partial | `\UseRawInputEncoding` 下存在一个非 UTF-8 字节 `0xA8`，转换阶段 UTF-8 解码失败 | 未猜测 Latin-1；需要显式可逆的 byte/font encoding 投影和精确 source mapping |
| `hep-th/9407087v1` | partial | partial | 纯 Harvmac plain TeX（`\input harvmac`、`\newsec`、`\end`），没有标准 LaTeX 正文环境，语法解析在 `\end` 处失败 | 未替换成 LaTeX class；需要独立的 Harvmac 语法/阅读适配器 |

### 2.1 已转为 ready 的 4 篇

1. **`2111.05176v1`（大小写资产）**
   - 原生构建在 macOS 大小写不敏感文件系统上成功，PDF 日志显示实际读取 `figs/bp_plot.png`，FLS 也记录了该请求。
   - 现在只在“候选资产仅大小写不同，且 FLS 证实该路径被消费”时解析；否则仍为 `asset_target_unresolved`。
   - `manifest.warnings` 记录 `asset_case_mismatch`。**这个 ready 不声称可移植到大小写敏感文件系统。**

2. **`2411.11822v1`（受保护文档边界）**
   - 严格 `document_bounds` 会跳过所有不可判定条件分支，因此 `\ifx\compilefullpaper\undefined` 中的文档标记被隐藏，`body_range` 为 `[None, None]`。
   - 新回退只遮蔽条件控制词（`\if...`、`\else`、`\fi`），要求掩码后全文恰好一对 `\begin{document}`/`\end{document}`，再交给原扫描器定位边界；所有分支原文都保留。
   - `\input{header}` 在 guard 内，但组装器实际已经展开；旧的 `directive_in_conditional` 是误报。现在记录为 `conditional_directive_resolved`，不当作正文缺失。
   - guard 仍不选择正文分支，只观测成功原生构建实际使用的文档边界。

3. **`2605.29137v1`（tcolorbox 标签与绘图条件）**
   - 缺失的 39 个 key 不是缺失的 `\label`，而是 `\begin{defbox}[label={...}]` 这类环境选项；AUX 中存在对应 `\newlabel`。
   - 新规则只在 AUX 唯一发出该 key 时，把环境选项绑定为标签；未确认的选项保持未解析。
   - `\foreach` 内的 `\ifodd\i` 是 TeX 绘图循环，两个分支逐次执行，不能选一个全局分支；它完整位于 `tikzpicture` 内，因此记录为 `drawing_payload`，原文保留、阅读视图不把它当正文条件。

4. **`2605.29554v1`（TeX key 空白）**
   - `\label{eq:resolved  system1_1}` 的双空格在 TeX 读参数时会折叠成一个空格，AUX 中也是单空格；旧实现拿原文字面 key 去比，导致 8 个引用未解析。
   - 新实现对所有标签/引用 key 折叠连续空白后再匹配；这是 TeX 参数词法，不是对某个论文的特判。

### 2.2 仍为 partial 的 6 篇（附 PDF 反例）

1. **`2012.04068v1`、`2102.06132v1`（重复标签）**
   - 这两篇的重复标签都在作者源码中真实存在，不是组装重复。
   - 引用确实指向多个目标，不能任选第一个；现在报 `cross_reference_ambiguous`，并在 `coverage.observations` 中记录 `duplicate_labels`。
   - 正确出路是作者修正源码，或在人工审核后提供明确的派生标签映射；自动猜测会违反“重复标签必须返回歧义”的约束。

2. **`2308.07915v2`（重复标签 + 条件分支）**
   - `ABC2`、`alpha_beta_gamma_delta` 在正文和 supplement 中各出现一次，引用歧义。
   - `supplemental_v2.tex` 的 `\ifdefined\maindocument` 在 standalone 模式下才需要 `\input{packages.tex}`；主文档构建中该分支不活动，但组装器没有执行条件，因此仍把缺失 include 记为 `unresolved_directives`。
   - 需要把 `\ifdefined` 的源码级真假绑定到实际构建视图，再决定是否忽略该 include；不能直接删除诊断。

3. **`1804.03719v1`（历史 RevTeX/array 兼容）**
   - 当前 TeX Live 2026 的 `revtex4` 与 `array` 组合在表格列定义处报 `Extra \or`，没有 PDF。
   - 既有历史支持集是 RevTeX 3.1，不匹配本包的 RevTeX4；内核回退和只回退 `array` 都在其他命令处失败。
   - 需要固定一套匹配的历史 class/package 或历史 TeX Live 镜像；不能用源码改写或通用宏回滚伪装成功。

4. **`2209.05640v1`（非 UTF-8 原始字节）**
   - `main.tex` 使用 `\UseRawInputEncoding`，第 69892 字节是 `0xA8`，不是合法 UTF-8 起始字节。
   - 当前转换要求 UTF-8 文本；不能把这个字节猜成 Latin-1 字符，也不能直接替换。
   - 需要设计可逆的字节/字体编码投影：保留原字节、给出明确 `encoding` 和精确 source mapping，并单独验证重编译文字，而不是假设它是某个 Unicode 字符。

5. **`hep-th/9407087v1`（Harvmac plain TeX）**
   - 文档没有 LaTeX `\begin{document}`，以 Harvmac 的 `\newsec`、`\end` 组织；语法解析器把 `\end` 当作需要环境名的 LaTeX 命令而失败。
   - 该包可以原生编译并有 PDF，说明问题在“阅读语法适配”，不是“论文不能编译”。
   - 需要保留引擎和原始语法的 Harvmac 适配器；直接换成 `article` 会改变作者结构和宏语义。

6. **`1208.0928v1`（PDF-only 反例）**
   - 这是配置中的负例：输入只有 PDF，没有 TeX 源码。它保持 `failed`，用于验证工具不会把 PDF 伪装成可准备 TeX。

## 3. 本轮实现改动

规则版本提升为 `compile-prepare-v10`。改动集中在离线 preparation 层，不改变工作区发布、科学解析或模型调用路径。

| 改动 | 位置 | 作用 |
| --- | --- | --- |
| TeX key 空白归一化 | [crossrefs.py](../../../qecgraph/preparation/crossrefs.py) | 标签/引用 key 折叠连续空白，匹配 TeX 参数词法 |
| 环境选项标签 | [crossrefs.py](../../../qecgraph/preparation/crossrefs.py) | 只有唯一 AUX `\newlabel` 确认时，`label={key}` 才成为标签 |
| 受保护文档边界 | [assembly.py](../../../qecgraph/source/assembly.py)、[convert.py](../../../qecgraph/preparation/convert.py)、[branches.py](../../../qecgraph/preparation/branches.py) | 严格扫描无正文时，用唯一文档标记对观测边界；不选正文分支 |
| setup-guard include 观测 | [convert.py](../../../qecgraph/preparation/convert.py) | 已组装的 guard 内指令不再被误报为正文缺失；未解析的仍阻断 |
| 绘图条件分类 | [conditions.py](../../../qecgraph/preparation/conditions.py) | `tikzpicture` 等绘图环境内的条件记为 `drawing_payload`，不阻断阅读 |
| 大小写资产匹配 | [convert.py](../../../qecgraph/preparation/convert.py) | 只有 FLS 消费了大小写变体时才解析，并记录非可移植警告 |
| 诊断增强 | [convert.py](../../../qecgraph/preparation/convert.py) | `cross_reference_unresolved`/`cross_reference_ambiguous` 带 key 和 occurrence；新增 `duplicate_labels` |
| manifest 警告 | [pipeline.py](../../../qecgraph/preparation/pipeline.py) | `manifest.warnings` 列出非阻断观测，避免只看 `status=ready` 误读 |
| 子集回放修复 | [reproduce_preparation.py](../../../tools/reproduce_preparation.py) | `--papers` 与 `--cases` 同时使用时，不再对未选中的 probe 论文抛 `FileNotFoundError` |
| 规则与验收文档 | [DESIGN.md](../../design/DESIGN.md)、[CHANGELOG.md](../../../CHANGELOG.md)、[preparation_acceptance.json](../../../validation/preparation_acceptance.json) | 记录新规则、计数和逐篇证据 |

关键边界：

- `manifest.status` 仍是二值 `ready`/`partial`；`manifest.warnings` 补充非阻断观测，但不会把 `ready` 变成可移植性或科学正确性的声明。
- 环境 `label=...` 的绑定仍是“AUX 唯一确认”的通用规则，没有证明该环境在 class 中确实定义为标签环境；对 tcolorbox 足够，但极端自定义环境仍有误绑风险。
- `document_bounds_observed` 只在严格扫描找不到正文且文档标记唯一时启用；多文档候选、注释中的标记或宏定义中的标记会保守拒绝。

## 4. 当前实现仍然存在的问题

1. **`ready` 不等于“可移植”或“科学正确”**
   - `2111.05176v1` 依赖 macOS 大小写不敏感文件系统；`2411.11822v1` 依赖“成功原生构建 + 唯一文档标记”的观测规则。
   - 两者都写入 `manifest.warnings`，但下游如果只读 `status=ready` 仍会误读。消费方必须同时读取 `warnings`。

2. **条件语义仍未执行**
   - 组装器不判断 `\ifdefined\maindocument` 的真假。`2308.07915v2` 的非活动 standalone 分支中缺失的 `packages.tex` 仍会被当成 `unresolved_directives`；另一类风险是未知 guard 内的 include 被无条件展开，内容可能不属于活动视图。
   - 要彻底解决，需要在源码层绑定 guard 的真实分支并保留证据，而不是只放宽诊断。

3. **重复标签策略仍是半严格**
   - 被引用的重复标签会阻断 `ready`；未被引用的重复标签只写 `duplicate_labels` 警告。`2201.08309v1`、`2209.01119v1` 目前是“ready + duplicate_labels”。
   - 如果要求所有重复标签都阻断，需要明确策略并重新计算 ready 数；当前选择是不让未引用重复标签无谓降低可读材料覆盖率。

4. **环境选项标签是通用启发式**
   - 现在只要求“环境开头有 `label={key}` 且 AUX 唯一”，没有扫描 class/preamble 的 `\newtcolorbox`/`\newtcbtheorem` 声明来证明该环境接受标签选项。
   - 更稳的方案是只对已声明环境启用，并把声明来源和哈希记入证据；这需要额外的 class 扫描和回归用例。

5. **非 UTF-8 没有通用路径**
   - `2209.05640v1` 需要可逆字节投影；直接 `errors="replace"` 或猜 Latin-1 都会破坏来源保真。
   - 需要单独设计 `encoding` 约定、JSON 可表示性和 normalized LaTeX 的写回验证。

6. **plain TeX/Harvmac 没有方言适配器**
   - `hep-th/9407087v1` 能编译但没有 LaTeX 文档体；`document_bounds` 和 `LatexWalker` 都按 LaTeX 结构工作。
   - 需要一个保留引擎、字体和原始命令的 Harvmac 语法/阅读层，而不是 class 替换。

7. **历史 TeX 兼容性没有固定镜像**
   - `1804.03719v1` 需要匹配 RevTeX4 时代的 class/package；当前只对 Quantumarticle 4.2 的空 hook 做了很窄的兼容重试。
   - 不应把这扩展成通用宏回滚；应固定历史 TeX Live 或经过验证的 class/package 集，并记录哈希。

8. **Linux 隔离未验收**
   - 本轮完整回放只在 macOS + TeX Live 2026 上执行。`2111.05176v1` 正好说明大小写差异会在 Linux 上暴露；bubblewrap 路径尚未运行。
   - 因此不能声称跨平台准备率相同。

9. **验收报告仍需要半手工同步**
   - `validation/preparation_acceptance.json` 的 rows 和 counts 由 `results.json` 再加工；这次已同步到 41/6，但没有自动生成器，后续容易再次漂移。
   - 建议增加一个从固定回放结果生成验收片的工具，并校验计数、ready 集合和 probe 数。

10. **machine 评测仍不可用**
    - 在只复制 `machine/`、不读 human/凭据的前提下重跑固定 release，仍报 `Registry state schema mismatch`，没有 before/after 指标。
    - 这是既有 registry schema 问题，不是本轮准备逻辑造成的；在 schema 迁移完成前不能宣称知识质量已验收。

## 5. 验证与证据

### 5.1 固定语料回放

```bash
.venv/bin/python tools/reproduce_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --out build/preparation-v10/full \
  --entries validation/preparation_entries.json \
  --support-dir build/compile-first/dependencies \
  --support-dir build/compile-first/historical-revtex \
  --cases validation/preparation_cases.json --jobs 2
```

结果：`papers=48, ready=41, partial=6, failed=1, compiled=46`；`source_fidelity=45`，`normalized_recompiled=45`，`normalized_text_equal=45`，`normalization_complete=44`，`syntax_probes=20/20`。

新增 ready：`2111.05176v1`、`2411.11822v1`、`2605.29137v1`、`2605.29554v1`。ready 回退：无。

### 5.2 测试与静态检查

```bash
.venv/bin/python -m coverage run -m unittest discover -s tests
QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest tests.integration.pipeline.test_compilation
.venv/bin/python -m ruff check qecgraph tests tools
.venv/bin/python -m mypy qecgraph
.venv/bin/python -m pyright --pythonpath .venv/bin/python
.venv/bin/python tools/check_complexity.py
```

| 检查 | 实际结果 |
| --- | --- |
| 单元/集成/契约测试 | `574 tests OK, 5 skipped` |
| 覆盖率 | `85.11%` |
| 真实 TeX 集成 | `5/5 OK` |
| Ruff | `All checks passed!` |
| mypy | `Success: no issues found in 110 source files` |
| pyright | `0 errors, 83 warnings` |
| 复杂度 | `85` 个历史函数超 10，`0` 个新增回归 |

说明：PTY 回归测试需要进程级伪终端；在受限工作区沙箱下会因 `out of pty devices` 失败，本轮证据运行在允许 TeX/PTY 的宿主环境中执行。真实 TeX 测试只在显式 `QECGRAPH_TEST_TEX=1` 时运行。

### 5.3 验收证据

- 逐篇结果、原因、未解析 key、`manifest.warnings` 和回放命令：[preparation_acceptance.json](../../../validation/preparation_acceptance.json)
- 当前规则说明：[DESIGN.md](../../design/DESIGN.md)
- 行为变更记录：[CHANGELOG.md](../../../CHANGELOG.md)
- 本轮测试实现记录：[02-test-implementation-and-verification.zh-CN.md](02-test-implementation-and-verification.zh-CN.md)

## 6. 边界与未验收

- **科学可用性未验收**：`ready` 是机械准备覆盖，不是定理、距离界、实验数据或九问答案的验收。20 个 probe 是 agent 编写的机械检查，不是独立人工金标。
- **Linux 未执行**：只有 macOS 回放；`2111.05176v1` 的非可移植性已显式记录，但不能据此推断其他论文在 Linux 上同样 ready。
- **历史 TeX 未执行**：`1804.03719v1` 需要的历史发行版/class 集没有固定镜像；没有声称它“论文本身不可编译”。
- **Docker/Lean 未执行**：本轮不涉及容器、Lean 构建或形式化验证。
- **machine 评测未通过**：固定 release 的 registry schema 不兼容；没有知识质量前后指标，也没有修改原始数据库。
- **工作树未提交**：本轮代码和验收改动仍在工作树中；`docs/reviews/` 既有记录保持原样，本报告是新增文件。
