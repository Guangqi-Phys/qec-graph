# 准备层读取路径优化与声明证据加固

> 状态：读取性能优化、声明遮蔽加固与固定语料行为保持完成；科学可用性未验收。日期：2026-11-17。承接 [07](07-preparation-architecture-and-behavior-preservation.zh-CN.md)。

本轮在 07 的架构重构和 v19 判据之上，检查“重新打开材料”和“生成验收报告”的实际执行路径。范围仍是离线 preparation：不开发后续提取、不调用模型、不上传来源、不修改原始论文或数据库，也不改变 `compile-prepare-v19` 的完成判据。

## 目录

- [1. 基线与结果](#1-基线与结果)
- [2. 找到的两个问题](#2-找到的两个问题)
- [3. 本轮实现](#3-本轮实现)
- [4. 性能与行为保持](#4-性能与行为保持)
- [5. 仍存在的优化空间](#5-仍存在的优化空间)
- [6. 复现命令与证据](#6-复现命令与证据)
- [7. 提交与文件保护](#7-提交与文件保护)

---

## 1. 基线与结果

基线为 `6056c6a` 的 v19 验收：46 ready、1 篇 TeX partial、1 篇 PDF-only 预期失败。固定清单 SHA-256 仍为 `153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b`。

| 指标 | v19 基线 | 当前 |
| --- | ---: | ---: |
| ready / TeX partial / PDF 预期失败 | 46 / 1 / 1 | **46 / 1 / 1** |
| 原生编译 / 来源保真 | 46 / 46 | **46 / 46** |
| 正文语法 / 书目绑定完整 | 46 / 46 | **46 / 46** |
| 交叉引用准备完整 / 唯一绑定完整 | 46 / 43 | **46 / 43** |
| 完整 normalization / 重编译 / 逐页文字相等 | 46 / 46 / 46 | **46 / 46 / 46** |
| 来源语法 probe | 20/20 | **20/20** |
| 默认测试套件 | 622 tests，12 skipped | **626 tests，12 skipped** |
| 默认分支覆盖率 | 84.84% | **84.86%** |
| 真实 TeX 集成 | 12/12 | **12/12** |

**没有改变准备判据、规则版本、ready 集合或材料 schema。** 当前新增的是读取路径性能、验收路径复用和环境声明证据的加固。

## 2. 找到的两个问题

### 2.1 环境声明扫描对无关文件做了全量语法解析

`read_material` 在只读验收时会重新核对材料。对真实书籍 `2605.29137v1` 做性能剖析时，单次读取约 6.0 秒，其中约 4.2 秒耗在 `label_declarations`：

- 它会对所有被 FLS 消费的 `.tex`、`.cls`、`.sty` 逐个调用 `pylatexenc`；
- 该材料有 36 个这类文件，解析调用在剖析中出现约 3.1 万次 `get_latex_nodes`；
- 但真正包含 tcolorbox 声明命令的文件通常只有 0–2 个，其余文件不可能产生 `newtcolorbox`/`renewtcolorbox` 声明。

这是读取路径的主要热点，而不是节点遍历或来源哈希校验。

### 2.2 `\renewcommand{\newtcolorbox}` 等遮蔽没有被识别

`_shadowed` 原先只识别 `\def`/`\gdef`/`\edef`/`\xdef`/`\let` 以及环境定义，未覆盖：

```tex
\renewcommand{\newtcolorbox}[2][]{#2}
\DeclareRobustCommand{\newtcolorbox}[2][]{#2}
\NewDocumentCommand{\newtcolorbox}{mm}{#2}
\RenewDocumentCommand{\newtcolorbox}{mm}{#2}
```

这会让后续字面 `\newtcolorbox{box}[2][]{#1}` 仍被当成有效的标签能力声明，产生**伪造的声明证据**。实测旧逻辑会对下面这段源码返回一条 `supports_label_option=True` 的 `box` 声明：

```tex
\renewcommand{\newtcolorbox}[2][]{#2}
\newtcolorbox{box}[2][]{#1}
```

对应的环境重定义也有同样问题：先声明 `box`，再 `\renewcommand{\box}`，旧逻辑仍可能保留 `box` 的标签能力。

## 3. 本轮实现

| 改动 | 位置 | 作用 |
| --- | --- | --- |
| 两阶段声明扫描 | [environments.py](../../../qecgraph/preparation/environments.py) | 所有文件只做注释遮蔽和候选字节检查；只有含 `newtcolorbox` 字面片段的文件才进入 `pylatexenc` |
| 读取作用域路径缓存 | [contract.py](../../../qecgraph/preparation/contract.py) | `_SourceEvidence` 在单次读取中缓存已校验的 span 路径，仍逐个检查哈希、字符/字节和行号 |
| 验收探针复用材料 | [acceptance.py](../../../qecgraph/preparation/acceptance.py) | `generate_report` 把已核验的材料传给 `check_cases`，probe 不再重复 `read_material` |
| 命令/环境重定义遮蔽 | [environments.py](../../../qecgraph/preparation/environments.py) | 增加 `newcommand`/`renewcommand`/`providecommand`/`DeclareRobustCommand`/`NewDocumentCommand` 等遮蔽识别；环境重定义仍通过原有环境正则拦截 |

### 3.1 两阶段扫描保持原有安全边界

候选预筛只用于决定“是否值得做完整解析”，不改变证据语义：

1. 仍对所有被消费文件做 `mask_comments`，并拼成完整 `source` 供 `_shadowed` 检查；隐藏在被注释文本中的声明不会被当成证据。
2. `"newtcolorbox" in masked` 覆盖 `newtcolorbox` 和 `renewtcolorbox` 两个控制词；不包含该字面片段的文件不可能被现有解析器识别成声明。
3. 只有候选文件进入 `_source_declarations`；其中仍执行条件区过滤、文档边界过滤、参数转发检查和 `SourceIndex` 精确定位。
4. 读取验收仍重新计算声明记录并与保存的 `environment_label_declarations` 逐项比较；优化没有放宽只读核验。

### 3.2 读取缓存是单次读取作用域的

`_SourceEvidence` 只缓存 `safe_path` 的结果，不缓存来源字节、节点、JSON 或跨材料结果。每次 `read_material` 仍重新读取 manifest 列出的文件、重新计算哈希，并逐个 span 校验：

- `sha256` 必须匹配；
- Unicode codepoint 半开区间必须有效；
- UTF-8 字节区间和 1-based 行号必须一致；
- 投影来源仍单独调用 `check_locator`。

因此这不是“信任上次读取”的持久缓存，而是避免同一文件路径在同一轮 7 万级 span 校验中反复做路径安全检查。

### 3.3 验收报告复用已核验材料

`generate_report` 现在维护一个本次报告作用域内的 `materials` 字典：

- 逐篇 `_verified_row` 只读一次材料；
- `_verify_probes` 对 probe 论文复用同一份已验证材料，不再重复读取；
- probe 仍在原始 `sources/<file>` 上核对 SHA-256 和 anchor 位置，不改变“独立重算 probe”的要求。

### 3.4 遮蔽识别是证据加固，不是规则放宽

新增遮蔽模式只让“被重定义后的声明”失去标签能力；它不会把任何原有 ready 材料变成 partial，也不会放宽重复标签、缺失引用、未知语法或编译失败。对固定语料，`2605.29137v1` 的 `stylesheet.cls` 仍按原声明路径通过；没有对该论文做 ID 特判。

## 4. 性能与行为保持

### 4.1 读取性能

在同一台 macOS + Python 3.15.2 上，对同一批保留的 v19 材料连续读取 3 次取中位数。`before` 仅把 `label_declarations` 切回旧的全量扫描逻辑，`after` 为当前代码；两组的 `_SourceEvidence` 路径缓存均启用，因此表中差异来自声明扫描，路径缓存是另一个较小的增量。

| 保留材料 | 节点数 | before 中位数（秒） | after 中位数（秒） | 变化 |
| --- | ---: | ---: | ---: | ---: |
| `2012.04068v1` | 17006 | 0.510 | 0.247 | 2.06× |
| `2209.05640v1` | 11967 | 0.462 | 0.285 | 1.62× |
| `2411.11822v1` | 8800 | 0.446 | 0.284 | 1.57× |
| `2605.29137v1` | 70128 | 3.054 | 1.414 | 2.16× |

`2605.29137v1` 的 07 报告记录为 3.135 秒；本轮同一代码路径的旧扫描基线是 3.054 秒，当前为 1.414 秒。差异来自运行负载和样本选择，不能把不同轮次的绝对值当成严格基准；同一轮 before/after 的配对比较才是本轮的结论。

`tools/report_preparation.py --check` 当前对 48 个输入重新读取并核验材料，实测约 16.2 秒；其中 5 篇 probe 论文不再被重复读取。

原始测量保存在 `build/preparation-08/read-benchmark.json`。

### 4.2 行为保持

完整重放：

```sh
.venv/bin/python tools/reproduce_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --out build/preparation-08/final \
  --entries validation/preparation_entries.json \
  --support-dir build/compile-first/dependencies \
  --support-dir build/compile-first/historical-revtex \
  --cases validation/preparation_cases.json --jobs 2
```

结果：`papers=48, ready=46, partial=1, failed=1, compiled=46`；`source_fidelity=46`，`normalized_recompiled=46`，`normalized_text_equal=46`，`syntax_probes=20/20`。

与 v19 保留材料的稳定对照：

```sh
.venv/bin/python tools/compare_preparation.py \
  --baseline build/preparation-v19/final \
  --current build/preparation-08/final \
  --out build/preparation-08/material-comparison.json
```

结果：`inputs=48, matched=48`，稳定产物、正文语法、来源映射、引用、覆盖、诊断、能力和准备结果均无差异；未出现 ready 增减。

### 4.3 测试与静态检查

| 检查 | 结果 |
| --- | --- |
| 默认单元/集成/契约套件 | `626 tests OK, 12 skipped` |
| 默认分支覆盖率 | `84.86%` |
| 真实 TeX 集成 | `12/12 OK` |
| Ruff | `All checks passed!` |
| mypy | `Success: no issues found in 125 source files` |
| Pyright | `0 errors, 83 warnings`（既有告警数不变） |
| 复杂度 | `85` 个既有函数超过 10，`0` 个新增回归 |
| 兼容端到端 | `tools/reproduce.py` 通过 |
| 中英文文档契约 | `17/17 OK` |
| 验收生成 / `--check` | 均通过，计数一致 |
| `git diff --check` | 通过 |

默认覆盖率不包含单独启用的原生 TeX 测试；真实 TeX 测试另行执行。测试增加覆盖了“无声明文件不被完整解析”“重定义命令遮蔽”“环境重定义遮蔽”“probe 复用已验证材料”四个边界。

## 5. 仍存在的优化空间

1. **JSON 重复解析仍是下一热点**
   - 在 `2605.29137v1` 当前约 1.4 秒的读取中，约 0.5 秒来自 31 次 `json.loads`；manifest、content、references、build、coverage、normalization 会被不同校验函数重复加载。
   - 可行的下一步是引入**单次读取作用域**的解析 JSON 缓存，并把它沿 `validate_material` 的校验链传递；不能做跨材料或跨进程缓存，否则会削弱“每次重新核验当前字节”的保证。

2. **观测 guard 材料仍会重复组装**
   - `view_contract.check_view` 为了核对 `build-view` 会再次 `assemble_files`，在 `2605.29137v1` 上约 0.36 秒。
   - 若把 `_check_syntax` 与 `check_view` 的组装共享，可减少一次全树组装；但需要把 `AssemblyResult` 的所有权明确为单次验证作用域，避免复用失效证据。

3. **`read_material` 仍返回完整节点数组**
   - 大论文的 7 万级节点会占用较多内存；当前没有流式/分页读取接口。
   - 如果后续消费者只关心 manifest 或分项能力，可以增加只读的轻量摘要 API，但不能让摘要替代完整来源核验。

4. **候选预筛依赖当前支持的声明命令**
   - 如果未来支持 `newtcbtheorem` 或新的 tcolorbox 声明命令，必须同步更新预筛字面表和 `_source_declarations` 的 `MacroSpec`，否则会漏扫。
   - 这是性能优化与语法支持之间的显式耦合，应通过测试固定。

5. **既有未解决项不变**
   - `1804.03719v1` 的历史 RevTeX4/array 原生编译问题仍未解决；`1208.0928v1` 仍是 PDF-only 预期负例。
   - 固定 machine release 仍报 `Registry state schema mismatch`，没有知识质量前后指标。
   - Linux/bubblewrap、历史 TeX 发行版、Docker、Lean 和独立科学金标仍未执行。
   - `2111.05176v1` 的大小写资产匹配仍是非可移植的 ready 警告。

6. **没有改变架构结论**
   - 07 的模块边界和依赖方向保持：没有新增模块，没有新增循环依赖，没有改变 `compile-prepare-v19` 材料 schema。
   - 本轮只是把读取路径中的两个局部热点收敛到单次作用域内；没有把准备层扩展成科学抽取或通用宏执行器。

## 6. 复现命令与证据

```sh
# 完整固定语料回放
.venv/bin/python tools/reproduce_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --out build/preparation-08/final \
  --entries validation/preparation_entries.json \
  --support-dir build/compile-first/dependencies \
  --support-dir build/compile-first/historical-revtex \
  --cases validation/preparation_cases.json --jobs 2

# 生成并独立检查验收报告
.venv/bin/python tools/report_preparation.py \
  --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/preparation-08/final \
  --cases validation/preparation_cases.json --baseline-revision 6056c6a \
  --machine-evaluation build/preparation-08/machine-evaluation.json \
  --out validation/preparation_acceptance.json
# 同一命令加 --check 只读复核

# 稳定材料对照
.venv/bin/python tools/compare_preparation.py \
  --baseline build/preparation-v19/final \
  --current build/preparation-08/final \
  --out build/preparation-08/material-comparison.json

# 读取基准
.venv/bin/python build/preparation-08/read_benchmark.py

# 测试与静态检查
.venv/bin/python -m coverage run -m unittest discover -s tests -v
.venv/bin/python -m coverage report
QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest tests.integration.pipeline.test_compilation -v
.venv/bin/ruff check qecgraph tests tools
.venv/bin/mypy qecgraph
.venv/bin/pyright --pythonpath .venv/bin/python
.venv/bin/python tools/check_complexity.py
.venv/bin/python tools/reproduce.py --out build/preparation-08/reproduce
.venv/bin/python -m unittest tests.contracts.docs.test_docs tests.contracts.docs.test_docs_bilingual -v
```

当前自动验收报告：[validation/preparation_acceptance.json](../../../validation/preparation_acceptance.json)。报告中的 `code_revision` 为执行代码提交 `bf5a577`，`rule_version` 仍为 `compile-prepare-v19`，`ready` 集合与基线相同。

## 7. 提交与文件保护

| 提交 | 内容 |
| --- | --- |
| `982c55e` | 两阶段环境声明扫描、读取作用域路径缓存、验收 probe 复用已验证材料 |
| `bf5a577` | 命令/环境重定义遮蔽识别和对应回归 |
| 本轮后续 | 08 报告、重新生成的验收报告和 changelog |

`docs/reviews/` 的既有文件未修改；07 报告、`Human.md`（SHA-256 仍为 `6a95cc5aeb4a466cb58a9bc2b790319aad729ccd8b53f0733198893820a1630d`）、复杂度 baseline 和固定语料清单均保持原样。原始论文、原始数据库和 `human/` 未读写；模型调用和来源上传均为 0。
