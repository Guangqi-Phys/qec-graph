# 准备层扩展：可逆字节投影、Harvmac 与分项能力

> 状态：实现与固定语料复验完成，43 ready / 4 partial；科学可用性未验收。日期：2026-11-17。

本轮承接 [04](04-preparation-hardening-and-remaining-work.zh-CN.md) 后对剩余 6 篇 partial 的讨论。范围仍为离线 preparation，不开发后续提取、不调用模型、不上传来源、不修改原始论文或数据库。旧 review 和 `Human.md` 保持原样。

## 目录

- [1. 基线与结果](#1-基线与结果)
- [2. 完成的适配及代码边界](#2-完成的适配及代码边界)
- [3. 仍未解决的部分](#3-仍未解决的部分)
- [4. 验证与复现](#4-验证与复现)
- [5. 提交与文件保护](#5-提交与文件保护)

## 1. 基线与结果

基线为已推送的 `9f4f537`、`compile-prepare-v14`：41 ready、6 partial，另有 1 个预期 PDF-only 失败。固定语料仍为 47 篇 TeX 与 1 篇 PDF，清单 SHA-256 为 `153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b`。

| 指标 | v14 基线 | v18 回放 |
| --- | ---: | ---: |
| ready | 41 | **43** |
| partial（TeX） | 6 | **4** |
| failed（PDF 负例） | 1 | **1** |
| 原生编译成功 | 46 | **46** |
| 非空语法且来源保真通过 | 45 | **46** |
| 书目绑定完整 | 45 | **46** |
| 统一来源重编译 / 逐页文字相等 | 45 / 45 | **46 / 46** |
| 完整 normalization | 44 | **46** |
| 正文语法完整（分项能力） | 未单独记录 | **46** |
| 已验证字节投影 | 不支持 | **1** |
| 来源语法 probe | 20/20 | **20/20** |

新增 ready 为 `2209.05640v1` 和 `hep-th/9407087v1`，ready 回退为 0。47 个 TeX 材料包均重新打开核验。显式支持目录的字节不变，但 v18 修正了实际搜索优先级，因此不能把本轮描述成完全相同的依赖消费结果。Harvmac 原来空书目列表的“完整”计数现由 33 条真实来源/运行时绑定替代，计数相同不代表实现没有变化。

规则提升到 `compile-prepare-v18`。所有分支都保留原始包、文件与哈希；新增适配按源格式和实际依赖触发，没有论文 ID 特判。能力标记不会把歧义引用升级成唯一目标或把整体 partial 改成 ready。

## 2. 完成的适配及代码边界

### 2.1 可逆字节投影

`2209.05640v1` 的 `main.tex` 在字节偏移 69892 的文献页码中含 `0xA8`，其他文本中还有合法 UTF-8。把整篇猜成 Latin-1 会改变合法字符；忽略或替换错误字节会丢失来源。

现在按以下次序准备：

1. 入口识别只使用临时视图读取 TeX 边界，原生编译始终接收原始字节。
2. 原生编译成功后，只检查 FLS 消费过的受支持文本输入；附件和二进制资产不转写。
3. 合法 UTF-8 原样复制，无法解码的字节逐个写为 TeX 十六进制输入 `^^hh`。记录每段原始字节到派生 Unicode 字符范围的映射，可逆还原，不猜字体字符。
4. 使用原引擎和同一显式支持目录编译派生副本。要求编译成功、原始输入消费集合相同、逐页去空白 PDF 文字相等；比较缺失、失败或不同都保持 partial。
5. 原始包和 `sources/` 不变。产物新增 `source-projection.json`、`projected-sources/`、`projection-build/`。
6. 改变的来源定位显式标为 `layer=projected`，字符、UTF-8 字节、行和哈希指向投影文件；`original_source` 单独给出原始哈希和包围的原始字节范围，不捏造原始 Unicode 字符坐标。
7. 只读验收重算全部允许转写和来源定位，并检查保存的原生/PDF 证据。仅修改派生字节再刷新 manifest 哈希不能通过。

主交付仍是共用语法 JSON；精确引句须组合 normalized → entry → 工作来源 → 原始字节映射，不能把投影文本当成原文。`read_material` 已返回投影报告及组装 source map，原来的 UTF-8 材料定位方式保持兼容。

当前只支持 `pdflatex`、`pdftex`、`latex`、`etex`；源码显式改变 catcode 时拒绝自动投影。4096 个错误字节是单文件上限。缺少 pdftotext 时，这条新增路径不能以“可选比较”放行。

### 2.2 Harvmac 原生语法

`hep-th/9407087v1` 可以编译，旧准备层却将 plain TeX 的结束命令按 LaTeX 环境结束解释，也把 `\eqn\ifa{...}` 所定义的公式标签 `\ifa` 当成未闭合条件。

本轮新增独立 Harvmac 适配：

- 原生构建必须实际消费已确认版本的 `harvmac.tex`，SHA-256 为 `65ff913ce13af190558fc07d161e90cf74f50ccd693ca95bb00dee2920535f1f`。支持字面 input/title/终止符及未被改写的核心语法；未知哈希、核心重定义、用条件原语充当生成标签等情况保持不支持。
- 准备后的 TeX 导出保留原生字节和引擎，不插入 article 文档类。统一的是结构字段和材料合同。
- `newsec`/`subsec` 等产生共用目录项；`eqn` 产生显式 `harvmac_eqn` 数学内容，公式字节保持不变。
- 根据明确生成语法识别公式控制词；扫描视图可避免 `ifa` 的条件误报，语法节点仍保留真实命令名和原始参数。
- `ref`/`nref`/`lref` 的原文条目必须与实际消费的 `refs.tmp` 文本唯一匹配；保留原始定义、编译条目、编号和定位。比较处理控制词后的 TeX 空白，仍区分不同单词和控制 token。
- `refs` 范围只在编译编号序列完整、唯一时展开，保留原始表达式、字面端点和展开方式；缺失或歧义不能通过。
- 只读验收重新核对原生方言证据、原文文献和编译内容、公式引用候选。不能靠修改方言版本或引用目标再刷新哈希伪造通过。

真实样本中得到 19 个目录项、33 个来源文献绑定，TeX 导出重编译后的逐页文字相同。未被引用的重复公式标签 `chikin` 仍记录警告；被引用的重复标签仍阻止 ready。

语法事实依据 [Harvmac by Paul Ginsparg](https://ctan.org/pkg/harvmac)，本机实际依赖文件头声明 CC BY 3.0；本项目新增的是识别与映射代码，没有复制 Harvmac 的 TeX 实现或将它提交为源码。

### 2.3 正文与引用分别报告能力

原来的总状态只说明“全部准备判据是否满足”。三篇重复标签论文实际上已有正文、公式和书目材料，只是部分引用不能唯一绑定。

新增 `manifest.preparation_capabilities`：

| 字段 | 含义 |
| --- | --- |
| `body_syntax` | 支持的正文语法、边界和覆盖是否完整 |
| `bibliography_bindings` | 文献条目与引用 key 的绑定是否完整 |
| `cross_reference_bindings` | 正文交叉引用是否唯一解析 |
| `unresolved_cross_references` | 未解析/歧义引用的发生节点、key、状态及完整候选节点 ID |

字段从保留证据推导，只读时独立重算。正文完整不会消除整体 partial；后续设计可以明确消费已准备的部分，同时避开不确定关联。本轮不实现那个后续消费阶段，也不推断证明依赖或作者意图。

### 2.4 显式依赖现在真正进入搜索路径

排查旧 RevTeX 时发现，旧 `--support-dir` 可以复制并记录依赖，却未保证该文件优先于系统同名包被读取。用原生 `kpsewhich --progname=pdflatex array.sty` 复现了这点。

现在支持文件位于沙箱内的 generic TeX 目录，程序自己的 `TEXINPUTS`、`BIBINPUTS`、`BSTINPUTS` 明确搜索顺序：作者包内文件 → 显式支持 → 系统默认。FLS 继续记录实际消费路径及哈希，不以“复制过文件”冒充“构建用过文件”。编译若改写显式支持文件，构建失败，原始支持目录仍不变。

真实测试同时检查显式支持能覆盖系统同名包，以及作者包内同名文件仍优先。另回放了五篇旧格式论文，全部 ready、重编译通过且文字相同。没有修改系统 TeX、下载发行版或将旧依赖全局安装。

### 2.5 代码职责

| 模块 | 职责 |
| --- | --- |
| `entries.py` | 构建入口识别；只返回路径，编译仍使用原始来源 |
| `projection.py` | 有界可逆字节转写、独立编译/文字证据、原始字节定位及核验 |
| `harvmac.py` | 固定原生方言证据、语法上下文、边界和结构 |
| `harvmac_refs.py` | 原文文献与编译文本绑定、控制词引用及有证据的编号范围 |
| `capabilities.py` | 从材料证据推导分项准备能力 |
| `build.py` / `sandbox.py` | 隔离执行、显式依赖优先级、来源/依赖改写检查 |
| `contract.py` / `view_contract.py` | 核验原始及派生来源、能力、方言、引用和已有分支证据 |
| `acceptance.py` | 从固定回放重算数量及能力，不复制旧验收结论 |

没有新增 Python 第三方依赖。原有静态准备和工作区抽取 API 保持兼容；新能力只用于编译优先路线。

## 3. 仍未解决的部分

| 论文 | 剩余阻断 | 本轮可用部分 |
| --- | --- | --- |
| `1804.03719v1` | 历史 RevTeX4/依赖编译失败 | 原始资产、源码和失败日志保留；正文语法未完成 |
| `2012.04068v1` | `lm:alpha-beta-exp` 的引用有多个目标 | 正文语法、文献、统一来源重编译完整；交叉引用 partial |
| `2102.06132v1` | `fig:bitfliplep`、`pij-approx` 重复 | 同上，候选目标全部保留 |
| `2308.07915v2` | `ABC2`、`alpha_beta_gamma_delta` 重复 | 同上；非活动 include 问题已在上一轮解决 |

后三篇需要作者修正或明确审核的消歧映射；本轮没有挑第一个/最后一个、改写标签或推断作者意图。

历史依赖本轮实际试验如下，均只作用于派生沙箱：

| 依赖组合 | 结果 |
| --- | --- |
| 系统 RevTeX4 + 系统 array/amsmath | `Eidenbenz_intro.tex:65` 报 `Extra \or` |
| array 2020-02-10 + amsmath 2018-12-01 rollback 文件 | 确认使用显式副本后，仍报 `Extra \or` |
| array 2016-10-06 + amsmath 2018-12-01 rollback 文件 | 越过原表格错误，在 `OMalley/omalled_grover.tex:24` 报 `\veqno` 未定义 |
| array 2023-11-01 + 系统 amsmath | 仍报 `Extra \or` |

因此没有把任一失败组合注册为自动兼容修复。后续需要固定相匹配的完整历史 class/kernel/package 组合，再重新验收；不能只降级某个文件就声称历史环境已复现。显式支持搜索路径已经修复，今后可以可靠地验证这些组合。

其他限制：未知 Harvmac 版本/动态定义、任意宏的语义展开、非标准 catcode、无法证明等价的编码转换仍不支持。Linux/bubblewrap、完整历史 TeX 发行版、Docker、Lean 和独立科学金标未执行；不声称支持所有 arXiv 包或证明数学正确。

固定 machine 副本的 release `aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22` 仍报 `Registry state schema mismatch`，不能给出可比知识质量指标。本轮不修 registry/migration，不读取 human、私人笔记或凭据，不改原库；固定 state 与原库同 release 的原文件字节一致。

## 4. 验证与复现

| 检查 | 实际结果 |
| --- | --- |
| 默认单元/集成/契约套件 | **611 tests OK，11 skipped**；基线为 596/8 |
| 默认覆盖率 | **84.39%**；v14 为 84.93%，没有声称覆盖率提高 |
| 原生 TeX 集成 | **11/11 OK** |
| 五篇旧格式依赖回归 | **5/5 ready**，重编译及逐页文字相等 |
| Ruff | All checks passed |
| mypy | 121 个源文件无问题 |
| Pyright | 0 errors、83 warnings，与基线相同 |
| 复杂度 | 85 个历史函数超过 10，新增回归 0；未改 baseline |
| 兼容端到端 | passed；611 项测试、4 个来源文件、29 个片段及查询/上下文复现 |
| 中英文文档契约 | 17/17 OK |
| Markdown 全仓检查 | 2 处已有 MD031，位于 2026-11-16 历史 review 的第 129、137 行；未修改旧记录 |
| 本轮修改页的 Markdown 检查 | `--no-globs` 范围检查通过，8 个文件、0 问题 |
| 原始数据/模型边界 | 原始数据库不写入，模型调用/来源上传为 0 |

默认覆盖率不包含单独显式开启的原生集成，不把测试数量增加视为科学金标。全仓 Markdown 的已有问题位于 `docs/reviews/review-2026-11-16-arxiv-prepare-2/01-implementation-review.zh-CN.md`；与基线文件逐字节相同。

### 4.1 固定语料及自动报告

```bash
.venv/bin/python tools/reproduce_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --out build/preparation-v18/final \
  --entries validation/preparation_entries.json \
  --support-dir build/compile-first/dependencies \
  --support-dir build/compile-first/historical-revtex \
  --cases validation/preparation_cases.json --jobs 2

.venv/bin/python tools/report_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/preparation-v18/final \
  --cases validation/preparation_cases.json --baseline-revision 9f4f537 \
  --machine-evaluation build/preparation-v18/machine-evaluation.json \
  --out validation/preparation_acceptance.json
```

同一报告命令加 `--check` 只读重新核对材料、计数和 probe。固定语料、来源及执行代码哈希、逐篇状态与失败原因写入 [自动验收报告](../../../validation/preparation_acceptance.json)。报告的能力计数是机械准备覆盖，不是科学答案准确率。

### 4.2 检查命令

```bash
.venv/bin/python -m coverage run -m unittest discover -s tests -v
.venv/bin/python -m coverage report
QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest tests.integration.pipeline.test_compilation -v
.venv/bin/ruff check qecgraph tests tools
.venv/bin/mypy qecgraph
.venv/bin/pyright --pythonpath .venv/bin/python
.venv/bin/python tools/check_complexity.py
.venv/bin/python tools/reproduce.py --out build/preparation-v18/reproduce
.venv/bin/python -m unittest tests.contracts.docs.test_docs tests.contracts.docs.test_docs_bilingual -v
npx --yes markdownlint-cli2@0.24.0
npx --yes markdownlint-cli2@0.24.0 --no-globs \
  CHANGELOG.md docs/README.md docs/README.zh-CN.md \
  docs/design/DESIGN.md docs/design/DESIGN.zh-CN.md \
  tools/README.md tools/README.zh-CN.md \
  docs/reviews/review-2026-11-17-compile-prepare-testing/05-native-dialects-byte-projection-and-capabilities.zh-CN.md
git diff --check
```

默认测试只使用离线 fixture/fake provider，真实 TeX 需另行显式开启。测试新增了混合 UTF-8/坏字节的可逆段、部分转写字符到原始字节的定位、非消费来源隔离、catcode 拒绝、文字不一致拒绝、派生字节伪造、Harvmac 版本/核心语法边界、重复公式歧义、文献 token 边界、入口识别、依赖优先级/改写和能力伪造等失败案例。

### 4.3 machine 副本评测命令

```bash
.venv/bin/python tools/reproduce_knowledge.py \
  --machine build/preparation-v10/machine-copy \
  --release aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22 \
  --out build/preparation-v18/machine-evaluation-raw.json
```

实际退出 1，原始错误与命令通过 `machine-evaluation.json` 附入自动报告；该失败不构成科学质量通过。

## 5. 提交与文件保护

| 提交 | 内容 |
| --- | --- |
| `ab52878` | 分别推导和独立核验正文/文献/交叉引用能力 |
| `ca071f9` | 可逆字节投影、原始定位、原生比较和对抗回归 |
| `19b3a11` | 原生 Harvmac、文献绑定、入口识别和真实测试 |
| `ac3ab22` | 显式依赖生效与改写检测、范围引用和验收能力字段；最终回放执行代码 |

本报告、当前设计/工具文档和自动验收在复验后提交并推送。`docs/reviews/` 永久保留；此前 01/02/03/04 及历史测试附件不修改。`Human.md` SHA-256 仍为 `6a95cc5aeb4a466cb58a9bc2b790319aad729ccd8b53f0733198893820a1630d`，复杂度基线和原始数据库未改变。
