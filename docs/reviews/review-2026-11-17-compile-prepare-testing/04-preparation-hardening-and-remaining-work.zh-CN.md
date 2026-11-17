# 编译优先准备：证据加固、自动验收与未完成事项

> 状态：实现与固定语料复验完成；机械准备覆盖保持 41 ready / 6 partial，科学可用性未验收。日期：2026-11-17。

本轮承接同目录 [01 测试方案](01-test-engineering-plan.zh-CN.md)、[02 测试实施](02-test-implementation-and-verification.zh-CN.md)、[03 v10 诊断](03-remaining-partial-diagnosis-and-v10-improvement.zh-CN.md)。范围仅为离线 preparation：把原始工程准备成可定位、可解析、可重编译的材料；不接入科学抽取、工作区发布或模型，不修改原始论文。

## 目录

- [1. 基线及最终结果](#1-基线及最终结果)
- [2. 本轮完成的改动](#2-本轮完成的改动)
- [3. 材料产物与代码边界](#3-材料产物与代码边界)
- [4. 未完成事项与后续路径](#4-未完成事项与后续路径)
- [5. 实际验证与复现命令](#5-实际验证与复现命令)
- [6. 提交与文件保护](#6-提交与文件保护)

## 1. 基线及最终结果

基线固定为 `59a0b9f`：先独立验证并提交交接时已存在的 v10 实现、测试和 01/02/03 报告。03 的 **37 → 41 ready** 属于前一轮成果，本轮不重复计为新增。语料 SHA-256 为 `153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b`，仍是 47 篇 TeX 加 1 篇 PDF 负例。

| 指标 | v10 基线 | v14 最终回放 |
| --- | ---: | ---: |
| ready | 41 | **41** |
| partial（TeX） | 6 | **6** |
| failed（PDF-only 负例） | 1 | **1** |
| 原生编译成功 | 46 | **46** |
| 非空语法且来源保真通过 | 45 | **45** |
| 文献绑定完整 | 45 | **45** |
| 统一 LaTeX 重编译 / 逐页文字相等 | 45 / 45 | **45 / 45** |
| 完整 normalization | 44 | **44** |
| 来源语法 probe | 20/20 | **20/20** |

**新增 ready 0，ready 回退 0。** 本轮消除了不可靠的推断和一个非活动 include 误报，增强了可复查证据；没有把未解决的论文改成 ready。47 个 TeX 材料包均独立重开验收，包括仍为空语法或 partial 的材料。逐篇自动证据见 [preparation_acceptance.json](../../../validation/preparation_acceptance.json)。

本轮提高了 ready 的证据要求：环境标签不能仅凭 AUX 推断；受保护的正文边界必须绑定真实分支观测；include 只能展开实际消费的文件。因此前后数字是相同语料上的机械覆盖比较，不能解释成科学抽取精确率。

## 2. 本轮完成的改动

### 2.1 环境标签必须同时有声明和编译证据

v10 只要求环境选项出现 `label={key}` 且 AUX 唯一发出同名 key，自定义环境可能被误绑。

现在按以下顺序处理：

1. 只扫描 FLS 消费过的原始 `.tex`、`.cls`、`.sty`，不把附件、宏定义内部或未知条件内部的文字当声明。
2. 识别字面 `newtcolorbox` 声明，要求首个可选参数通过独立的 `#1` 选项转交；支持带默认值、参数数为 1–4 的这一窄语法。
3. 重复/被重定义的环境或动态声明不获得标签能力。`renewtcolorbox` 可以保留声明记录，但不会单独授予能力。
4. 环境调用只读取顶层选项；`title={label=...}`、重复 `label`、动态值均不能冒充标签。
5. 同时要求唯一 AUX `newlabel`，保存声明和调用的原文、字符/字节/行范围及哈希。
6. `read_material` 从原始消费来源重新核对声明和绑定，拒绝只改 JSON 的伪造证据。

真实书籍 `2605.29137v1` 的声明和 39 个先前缺失引用仍可按这条严格路径处理；不是为某个论文名设置白名单。

### 2.2 用原生分支观测替代唯一文档标记回退

新转换不再因为源码只有一对 `begin/end{document}` 就跨过未知条件。

1. 先完成未改写原始工程的编译，保存 FLS、AUX、BBL、PDF 和日志。
2. 从实际消费来源中选择支持的独占行字面条件：`\ifdefined\control`、`\ifx\control\control`。最多 128 个；不推断行内或动态条件。
3. 在独立副本插入带随机前缀的 `write16` 分支标记。两侧分支原文保持；没有 else 时补的标记分支仅用于探针。复用原编译生成的书目、引擎和显式支持文件。
4. 再编译探针副本。只有编译成功、逐页去空白 PDF 文字相同、同一 guard 仅稳定观测到一个分支时，才产生可消费的分支结果。
5. 未执行、随上下文改变、编译失败或 PDF 比较不可用/不一致都不给出选择。
6. 组装扫描保持字符位置的活动视图，但输出仍复制原始字节。语法树明确标记 inactive 区域；统一副本只把已验证条件头改为 `iftrue/iffalse`，记录每段编辑映射，两侧正文仍保留。
7. 只读验收重算候选语法、插桩树、日志结果、PDF 比较文字哈希、组装映射和正文边界。测试覆盖了“修改 selected 并刷新 JSON/manifest 哈希”的伪造，仍会拒绝。

`2411.11822v1` 已通过这条路径。`2308.07915v2` 的非活动 standalone 分支不再要求缺失的 `packages.tex`，但其活动正文的重复标签仍阻断 ready。绘图循环仍按 `drawing_payload` 保留，不能把循环两侧压成全局单一分支。

### 2.3 只组装实际消费的 include

编译路线给共用组装器传入实际 FLS 输入集合。文件存在但未被本次构建消费时，保留原指令并记录 `not_consumed`，不把附件中的另一构建版本拼进活动正文。默认静态兼容 API 不传这个限制，保持原有行为。

全量真实回放还暴露了一个新校验器错误：内存 source map 中的指令参数是 tuple，JSON 读回后是 list，直接比较误报映射不一致。已改为比较规范 JSON，并增加“字面路径宏 → input 子文件 → 发布 → 只读重开”的回归。初次中断回放不作为最终证据。

### 2.4 补齐书目通配符和非主作用域绑定

- `\nocite{*}` 不再被过滤后以空 requested 列表通过；它按作用域展开为实际 BBL/AUX 条目，并保留源调用范围。没有可观测条目时明确报 `wildcard_bibliography_unobserved`。
- Biblatex 的 wildcard 按 refsection 检查；不会拿另一 section 的条目填补。
- 原始内联 `bibitem` 可以绑定唯一的非主编译作用域。跨作用域重复 key 明确报歧义，不猜测。
- 真实 BibTeX 的 wildcard 和 `sub/main.tex` 入口经过原生集成验证。保留 TeX 从项目根目录运行时的实际 job 输出位置，不随意搬运 `sub/main.bbl`。

### 2.5 自动生成并检查验收报告

新增 `tools/report_preparation.py`，不再手动同步当前验收计数：

1. 要求固定清单的每个输入恰好有一行结果，子集不能冒充完整验收。
2. 核对清单、实际原包、运行时代码快照、规则版本和 probe 配置哈希；源码变更后必须重新回放。
3. 对每个已发布包执行 `read_material`，核对状态、阶段、节点、来源保真、诊断和统一格式结果，再计算汇总。
4. 从实际原文重跑语法 probe，不能照抄 `passed` 数。
5. 从显式 Git commit 读取同一语料的基线，生成新增 ready/回退集合；基线版本读实际报告，不手填旧版本名。
6. 报告原子写入；`--check` 只验证已保存报告是否完全对应证据，不编译、不改报告、不调用模型。

离线对抗测试覆盖虚增计数、伪造行/节点数、原包变化、代码快照过时、假 probe 通过、缺行和不同基线语料。报告只声明机械准备证据；独立科学验收始终为未通过。

## 3. 材料产物与代码边界

| 层 | 职责 | 主要交付 |
| --- | --- | --- |
| 原始编译 | 原始工程副本的实际执行与隔离 | `sources/`、`original.package`、`build/`、`build.json` |
| 分支观测 | 可选、受限的真实分支探针 | `build-view.json`、`build-view/`，失败不猜分支 |
| 引用适配 | BIB/BBL/AUX/BCF 的字面条目与运行时 key/作用域 | `references.json`，不推断证明依赖 |
| 语法准备 | 原文组装、语法树、阅读范围、标签、表格/资产位置 | `entry.tex`、`content.json`、`source-map.json` |
| 统一格式 | 有界语法改写和来源投影 | `normalized.tex`、`normalized-map.json` |
| 往返及材料验收 | 派生重编译、PDF 文字比较、来源和证据检查 | `normalization.json`、`normalized-build/`、coverage/diagnostics/manifest |
| 语料验收 | 独立复核完整回放并生成机械报告 | `validation/preparation_acceptance.json` |

当前规则为 `compile-prepare-v14`，材料 schema 仍是 `qecgraph.prepare/3`。旧材料按其记录版本读取，不自动升级为新证据。新模块为 `options.py`、`environments.py`、`guard_syntax.py`、`build_view.py`、`view_contract.py` 和 `acceptance.py`；未增加第三方 Python 依赖。新函数复杂度保持不超过 10，既有复杂度基线未修改。

准备完成后得到的是可回到原文、附带能力和限制的机器材料，不是科学记录、定理判断、九问答案或任意宏的语义展开。PDF 文字相等也不能证明像素、数学含义或跨平台结果相同。

## 4. 未完成事项与后续路径

最终 6 篇 TeX partial 如下。可编译和可完整准备是不同阶段，不能仅用 PDF 存在判定完成。

| 论文 | 当前直接阻断 | 本轮结果及后续路径 |
| --- | --- | --- |
| `1804.03719v1` | 原生编译失败；旧 RevTeX4/array 在 `Eidenbenz_intro.tex:65` 报 `Extra \or` | 未修；固定相匹配的历史依赖/发行版后重编译，不改作者正文 |
| `2012.04068v1` | `lm:alpha-beta-exp` 有两个来源标签，引用歧义 | 保留双目标；需要作者修正或明确审核的派生消歧映射 |
| `2102.06132v1` | `fig:bitfliplep`、`pij-approx` 重复，活动引用歧义 | 同上，不选择第一个/最后一个标签 |
| `2308.07915v2` | `ABC2`、`alpha_beta_gamma_delta` 重复 | **已修复非活动 packages.tex 误报**；剩下的活动引用歧义仍阻断，需消歧 |
| `2209.05640v1` | `UseRawInputEncoding` 下原始偏移 69892 为非 UTF-8 字节 `0xA8` | 未修；需要显式可逆的原字节/字体编码投影及 source map |
| `hep-th/9407087v1` | Harvmac plain TeX：没有标准 LaTeX 正文，`\end`、`\ifa` 和相关 include 未被当前语法完整适配 | 未修；原生编译和文字比较通过仍不足以使语法准备完成，需要独立方言适配 |

另一个输入 `1208.0928v1` 只有 PDF，保持预期 `failed`，不混入这 6 篇 TeX partial。

另外保留以下限制：

| 事项 | 当前状态和下一步 |
| --- | --- |
| 非 UTF-8 投影 | 未实现可逆 byte/font encoding 约定；不得猜 Latin-1、替换或丢弃字节 |
| Harvmac 方言 | 未实现独立的 plain TeX 阅读语法适配；不能换 article 伪装原结构 |
| 历史 RevTeX4 | 未固定相匹配的历史 TeX/class/package 集；不得用通用宏回滚消除报错 |
| 更广条件语法 | 行内/动态条件、同一 guard 多上下文和任意宏执行不在本轮支持范围；无充分证据保持 partial |
| 任意环境声明 | 只支持明确的 tcolorbox 参数转交模式，未支持 newtcbtheorem、动态定义和所有自定义环境 |
| 子目录已有 BBL | 已验证真实子目录 entry + BibTeX；没有把所有 sibling BBL 自动改名/搬到 job 根目录，须尊重实际消费路径 |
| 包内旧子 AUX | 本轮没有“一律删除所有 AUX”；外部文档/预编译输入可能合法，需要按实际任务闭包设计并单独验收 |
| 外部/本地同名标签 | 保留歧义，遵循重复标签必须消歧的约束；不采纳任选本地或最后一个的策略 |
| 含注释的引用包装宏 | 原始调用与字节保留；没有扩展统一格式的所有包装宏正则，未确认的调用不强行改写 |
| Linux/大小写 | 只有 macOS 原生实测；bubblewrap/Linux、大小写敏感文件系统未运行，case-only 资产仍有警告 |
| 科学质量 | 20 个 source probe 是机械检查，不是独立科学金标；未做科学抽取或模型质量评测 |
| machine 评测 | 固定 release 仍报 `Registry state schema mismatch`，无可比知识质量数字；本轮不改 registry/migration |

## 5. 实际验证与复现命令

| 检查 | 实际结果 |
| --- | --- |
| 默认测试套件 | **596 tests OK，8 skipped**；交接基线为 574 tests、5 skipped |
| 默认套件覆盖率 | **84.93%**；v10 为 85.11%，本轮没有声称覆盖率提高 |
| 真实 TeX 集成 | **8/8 OK**；含真实分支、来源环境声明、nocite wildcard/子目录入口 |
| Ruff | All checks passed |
| mypy | 116 个源文件无问题 |
| Pyright | 0 errors、83 warnings，与交接基线告警数相同 |
| 复杂度门禁 | 85 个历史函数超过 10，新增回归 0；未改 baseline |
| 兼容端到端 | passed；596 项测试、4 个来源文件、29 个片段，查询与上下文复现通过 |
| 中英文文档契约 | 17/17 OK |
| 自动验收生成 / `--check` | 全部 48 行核对、47 个材料包重开、计数/20 probe/基线比较一致 |
| `git diff --check` | 通过 |
| 模型/上传 | 本次准备和语料评测均为 0；没有来源上传 |

默认覆盖率不包含单独启用的原生 TeX 测试；新分支观测仍有未覆盖路径，不能以测试数量增加冒充质量金标。

### 5.1 固定语料和报告

```bash
.venv/bin/python tools/reproduce_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --out build/preparation-v14/final \
  --entries validation/preparation_entries.json \
  --support-dir build/compile-first/dependencies \
  --support-dir build/compile-first/historical-revtex \
  --cases validation/preparation_cases.json --jobs 2

.venv/bin/python tools/report_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/preparation-v14/final \
  --cases validation/preparation_cases.json --baseline-revision 59a0b9f \
  --machine-evaluation build/preparation-v14/machine-evaluation.json \
  --out validation/preparation_acceptance.json
```

第二条相同命令加 `--check` 验证已保存验收；本机大型原始/派生材料在忽略的 `build/` 下。报告记录执行代码提交 `3ab90cf` 和源文件哈希，即使之后仅提交文档，也不会把新文档提交冒充编译时的代码提交。

### 5.2 检查命令

```bash
.venv/bin/python -m coverage run -m unittest discover -s tests -v
.venv/bin/python -m coverage report
QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest tests.integration.pipeline.test_compilation -v
.venv/bin/ruff check qecgraph tests tools
.venv/bin/mypy qecgraph
.venv/bin/pyright --pythonpath .venv/bin/python
.venv/bin/python tools/check_complexity.py
.venv/bin/python tools/reproduce.py --out build/preparation-v14/reproduce
.venv/bin/python -m unittest tests.contracts.docs.test_docs tests.contracts.docs.test_docs_bilingual -v
git diff --check
```

默认套件跳过需显式启用的真实 TeX 测试；上面的原生命令另行执行。TeX/PTY 检查使用允许宿主进程的执行环境，TeX 自身仍受 preparation 沙箱限制，没有无隔离回退。兼容端到端仅复现已有合成抽取/查询，不开发后续阶段。Docker、Linux、Lean 和独立人工科学金标未执行。

### 5.3 固定 machine 副本评测

```bash
.venv/bin/python tools/reproduce_knowledge.py \
  --machine build/preparation-v10/machine-copy \
  --release aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22 \
  --out build/preparation-v14/machine-evaluation-raw.json
```

实际退出 1，错误为 `Registry state schema mismatch`。只使用已有 machine 副本；固定 state 与 `~/Workspace/QEC-database/machine/` 同 release 原文件字节一致，不读取 human、私人笔记或凭据，不修改原始库。失败命令、错误、release 和 state 哈希通过独立 JSON 附入当前验收；不能将此写成知识质量通过。

### 5.4 显式支持文件来源

本轮未下载或修改系统 TeX；复用既有显式支持目录。以下五个既有文件的当前字节哈希均逐项核对，与 v10 固定值相同：

| 文件 | SHA-256 | 既有来源 |
| --- | --- | --- |
| `dependencies/BoxedEPS.tex` | `0d7a065b0fc97cfdd5bf262dca32a46f563137f87023ea08b7f5b6f63132f2e7` | [CTAN BoxedEPS](https://www.ctan.net/macros/generic/boxedeps/boxedeps.tex) |
| `dependencies/doublespace.sty` | `46bb289da9b6d0c1a099d1f44ca66e4418bb30097f7bbcf03dc1fb8bf1380918` | [CTAN doublespace](https://www.ctan.net/obsolete/macros/latex209/contrib/misc/doublespace.sty) |
| `dependencies/boxedeps.cfg` | `40e5abdffbfa93bb1170efa13bb15607cc86c3a9cbb8c17afada10eef6ba6bb7` | [CTAN configuration](https://www.ctan.net/macros/generic/boxedeps/boxedeps.cfg) |
| `revtex.zip` | `a6338191e5e96b282889a5673594e31814e107d77c5c7b389b691d59feb1de3f` | [CTAN historical RevTeX](https://www.ctan.net/obsolete/macros/latex209/contrib/revtex.zip)；不解决 RevTeX4 兼容 |
| `biber-arm64` | `a1a2784931d9156a9d4cc8cb609912d533f04365d2e4aa7b902001a2f1a65066` | 既有 TeX Live Biber 2.21 的 Apple `lipo -thin arm64` 产物 |

这些是已存在文件的来源记录与本地字节核对，不声称今天重新下载或上游内容恒定。实际每次构建的依赖绑定仍以材料 `build.json`/日志为准。

## 6. 提交与文件保护

| 提交 | 内容 |
| --- | --- |
| `59a0b9f` | 独立复验后记录交接的 v10、01/02/03 和测试基线 |
| `305b90c` | 来源声明和顶层选项共同约束环境标签 |
| `1d2dc65` | 有原生分支日志/PDF 证据的活动来源视图和独立校验 |
| `2619224` | wildcard/inline scope 补全及 FLS include 消费边界 |
| `4a66d33` | 自动验收生成/检查及对抗回归 |
| `29afd44` | 真实回放发现的 source map JSON 比较修复与回归；规则 v14 |
| `3ab90cf` | 消除新增的声明位置类型告警；最终回放执行代码 |
| `ec3cae2` | 中英文设计、边界、工具说明及 changelog |

本报告和自动验收在复验完成后单独提交，随后 push。`docs/reviews/` 保留；既有 01/02/03 与三份历史测试附件不重写。`Human.md` 没有修改，SHA-256 仍为 `6a95cc5aeb4a466cb58a9bc2b790319aad729ccd8b53f0733198893820a1630d`。旧复杂度基线和原始数据库也没有改动。
