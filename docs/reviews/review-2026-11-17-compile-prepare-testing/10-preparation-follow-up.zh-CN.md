# 准备层修复、测量与留出验证

日期 2026-11-18。固定语料对照基线为 `9bd6e73` 的 v19，回放代码为
`cb37129` 的 `compile-prepare-v20`。本轮核验编译、受支持语法、来源坐标和
引用证据，没有调用模型。完整结果见[固定语料验收](../../../validation/preparation_acceptance.json)。

## 实现记录

| 提交 | 改动与验收边界 |
| --- | --- |
| `da5148d` | 拆开结构书目与最终运行时判定。读取原文和规范化构建各自的最终日志，并保留原 BBL、拒绝文件名和未定义引用键。 |
| `4e19546` | 回放凭本次退出状态、产物目录和 manifest 哈希验收。失败重跑读取自己的 `.attempt`。 |
| `6700fc6` | 准备阶段异常按发生阶段报告，保留原包及该阶段之前已有的编译证据。 |
| `4bc1343` | 同一文件的明确加载和定义顺序可证实 `\providecommand` 为空操作。真实或无法证实的重定义仍受限制。两种已发布的 v19 材料都可复核。 |
| `2c8671d`、`6503115` | 验收逐篇检查材料及探针。单份材料的解析器和验收器共用本次读取的 JSON 与源码证据。 |
| `215b4da` | 主 AUX、FLS 记录的辅助输出稳定且最终日志没有已知重跑请求时，两轮即可结束。证据不足时保留三轮，规范化副本独立编译。 |
| `d4cbad2` | 去掉 `content.json` 的缩进和分隔空白，保留原有字段、来源坐标及读取接口。 |
| `7369f34`、`cb37129` | 冻结留出样本。跨回放比较书目时用各自已核验的最终日志，比较结果保留状态和引用键差异。 |

## 固定语料回放

相同的 47 个 TeX 输入和 1 个 PDF 反例，保留相同入口提示、支持目录和探针。
清单 SHA-256 为 `153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b`。

| 项目 | v19 | v20 |
| --- | ---: | ---: |
| Ready | 46 | 44 |
| Partial | 1 | 3 |
| 预期拒绝的 PDF | 1 | 1 |
| 原生编译成功，有非空语法与已校验来源 | 46 | 46 |
| 规范化重编译成功，逐页去空白文字相同 | 46 | 46 |
| 来源绑定探针 | 20/20 | 20/20 |
| 保留全部交叉引用候选并达到 ready | 3 | 3 |

| Partial | 证据 |
| --- | --- |
| `1804.03719v1` | 旧 RevTeX 与本地 `array` 组合仍报 `Extra \or`，原包和失败日志已保存。 |
| `2303.15933v1` | 原文和规范化均编译完成，书目结构完整。两次最终日志拒绝所附的 BBL 格式，原文日志有 39 个未定义引用键。源包内没有可重编译的 BIB。 |
| `2605.30298v1` | 同样保留完整书目结构。两次最终日志拒绝 BBL 格式，原文日志有 19 个未定义引用键。源包内没有可重编译的 BIB。 |

逐包重新读取后，47 份材料的原包、原文件、`entry.tex`、来源映射、`normalized.tex`、
规范化映射及书目结构与基线相同。解码后的语法也一致，比较时忽略各自已核验的构建观测
哈希。对 46 组原生和规范化 PDF 文字作跨回放对照，29 组逐页相同，17 组的差异均可
由排版日期从 11 月 17 日变为 18 日精确解释。两个新增 partial 的正文、来源与书目
条目都保留。三篇保留交叉引用歧义的论文继续 ready。

## 成本测量

| 项目 | v19 | v20 |
| --- | ---: | ---: |
| 原文、规范化、插桩和投影的 TeX 进程次数 | 288 | 249 |
| 同一批构建步骤累计秒数 | 630.83 s | 565.58 s |
| `content.json` 合计 | 469.76 MiB | 264.66 MiB |
| 47 个材料包合计，含 manifest | 1058.56 MiB | 853.02 MiB |
| 验收 `--check` 墙钟时间 | 14.05 s | 8.18 s |
| 验收 `--check` 峰值 RSS | 1.79 GiB | 0.42 GiB |

编译耗时为材料中各工具步骤的累加值，v20 的双并发完整回放墙钟时间为 357.49 秒。
验收时间和 RSS 来自同机顺序执行的两次 `/usr/bin/time -l`，分别使用对应版本的
检查器与已保留的材料。对同一份 v19 书本材料 `2605.29137v1` 重复读取三次，
单次 JSON 解码从 31 次降到 10 次，耗时中位数从约 1.40 秒降到 1.04 秒。

## 独立留出验证

选取 2024 年 6 月 arXiv 量子物理月榜前八个位置，冻结论文 v1 的包清单和哈希。
用默认入口选择和本地工具回放，留出结果未参与规则调整。七个 TeX 中四个 ready，
两篇 partial，一篇有多个入口。另有一份 PDF 被预期拒绝。这里只记录八个输入的实际结果。
[留出清单](../../../validation/preparation_holdout.json) ·
[arXiv 月榜](https://arxiv.org/list/quant-ph/2024-06?skip=0&show=25)

| 输入 | 本次结果 | 证据 |
| --- | --- | --- |
| `2406.00137v1` | Failed | 同包中 `NHOptMech.tex` 和 `NHOptMechsuppl.tex` 都是入口，需要显式指定。 |
| `2406.00176v1` | Ready | 来源校验与规范化重编译通过。 |
| `2406.00193v1` | Ready | 来源校验与规范化重编译通过。 |
| `2406.00266v1` | Ready | 单文件 gzip 源通过来源校验与规范化重编译。 |
| `2406.00267v1` | Partial | 本地 PDF 引擎报缺少 `Fig1-eps-converted-to.pdf`。 |
| `2406.00268v1` | Partial | TeX 和 dvips 完成，Ghostscript 10.08.0 的 ps2pdf 步骤报 `/undefined in obj`。额外的三轮诊断复跑得到同一错误。 |
| `2406.00296v1` | 预期 Failed | arXiv 源下载返回 PDF。 |
| `2406.00350v1` | Ready | 来源校验与规范化重编译通过。 |

## 复验与未完成事项

- 启用本地 TeX 的全量单测通过 632 项。端到端 `tools/reproduce.py`、Ruff、mypy
  和复杂度检查通过，Pyright 为 0 errors 和 83 条既有警告。
- 本地 CLI 对同一源包先生成 ready，再以缺少支持目录的配置触发 partial。回放和验收
  都计入当次 `.attempt`，旧 ready 的 manifest 字节一致。
- 固定 machine 副本在固定 release `aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22`
  再次报 `Registry state schema mismatch`，退出 1。该副本的固定 state 哈希核对相同。
  研究评测、Linux 容器与 Lean 未验收。
- 保留三轮上限、两次独立构建和现有 PDF 文字证据字段。缺少 pdftotext 的轮次仍标记为未比较。
  当前验证使用 macOS 与本地 TeX Live。两篇 BBL 不兼容需要匹配的依赖版本或可重新生成
  BBL 的原始书目，新留出样本暴露的 EPS、PS 转换和多入口情况都在上表保留。

```sh
QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/reproduce.py --out build/preparation-followup/reproduce
.venv/bin/python tools/reproduce_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --out build/preparation-followup/final \
  --entries validation/preparation_entries.json \
  --support-dir build/compile-first/dependencies \
  --support-dir build/compile-first/historical-revtex \
  --cases validation/preparation_cases.json --jobs 2
.venv/bin/python tools/report_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/preparation-followup/final --cases validation/preparation_cases.json \
  --baseline-revision 9bd6e73 \
  --machine-evaluation build/preparation-followup/machine-evaluation.json \
  --out validation/preparation_acceptance.json --check
.venv/bin/python tools/reproduce_preparation.py \
  --manifest build/preparation-followup/holdout/manifest.json \
  --out build/preparation-followup/holdout/replay --jobs 2
```
