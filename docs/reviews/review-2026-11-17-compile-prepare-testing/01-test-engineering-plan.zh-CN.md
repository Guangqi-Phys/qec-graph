# TeX 编译优先文献准备管线（`compile-prepare`）测试工程方案报告

> 状态：测试工程设计方案，已于同日落地实施。日期：2026-11-17。对应实现记录见 [02-test-implementation-and-verification.zh-CN.md](02-test-implementation-and-verification.zh-CN.md)。

本文针对基于原生 TeX 编译与无损语法转换的文献准备管线（[qecgraph/preparation/](../../../qecgraph/preparation/)、[qecgraph/source/syntax.py](../../../qecgraph/source/syntax.py)、[tools/prepare_compiled.py](../../../tools/prepare_compiled.py)、[tools/reproduce_preparation.py](../../../tools/reproduce_preparation.py)），结合主流 Agent QA / 编译器测试方法论，制定系统化的测试工程方案与代码边界审计报告。

## 目录

- [1. 测试方法论](#1-测试方法论)
- [2. 现有测试覆盖盘点与代码审计盲区](#2-现有测试覆盖盘点与代码审计盲区)
- [3. 待实现的测试矩阵](#3-待实现的测试矩阵)
- [4. 交付与分层执行策略](#4-交付与分层执行策略)

---

## 1. 测试方法论

针对“**原生 TeX 编译 + 无损语法树转换 + 源码字节映射（Source Map）+ 派生 `normalized.tex` 往返重编译验证**”这一编译器/转译器管线，单纯依赖固定样例（Example-based Testing）容易出现“测试只复述实现逻辑”的盲区。参考 `advanced-qa-test-planner` Skill 与编译器/Source-Map 测试方法论，本方案采用四层测试范式：

1. **属性测试（Property-Based Testing, PBT）**：验证对任意合法或局部损坏的 LaTeX 语法树与多文件包含结构都必须成立的**数学不变量**（如根节点与子节点无缝铺满 `entry.tex`、跨文件拼接分隔符偏移回映恒等、`normalized-map.json` 双向投影守恒、`SourceIndex` UTF-8 多字节字符/字节/行号三元一致）。
2. **蜕变测试（Metamorphic Testing, MT）**：解决复杂 LaTeX 文档缺乏人工金标的“测试预言机难题（Oracle Problem）”。对同一篇源码施加保语义变换（如注入 `%` 注释、在 `\if 0...\fi` 与 `\end{document}` 后注入坏语法、将单文件拆成 `\input` 子文件、在 `.bib` 中增加未引用条目与 `@CONTROL`），验证输出之间的**确定性蜕变关系**。
3. **差分与交叉预言机测试（Differential & Cross-Oracle Testing）**：利用 TeX 编译器实际产生的 `.fls`、`.aux`、`.bbl`、`.bcf` 及 `pdftotext` 页面文本作为运行态预言机，与静态 `convert_source` / `normalize_latex` 的语法分析结果进行交叉核对。
4. **对抗与故障注入测试（Adversarial & Fault-Injection Testing）**：模拟恶意或畸形投稿包（如 `.fls` 路径穿越、`.bcf` XML 实体注入、编译期自修改源码、软链接替换、超深层花括号嵌套、伪造 `ready` 清单状态），验证**零未捕获崩溃（Zero Unhandled Exceptions）**与**已发布 `ready` 产物保护**。

---

## 2. 现有测试覆盖盘点与代码审计盲区

### 2.1 现有测试覆盖盘点

| 测试文件 | 现有测试数 | 已覆盖的主路径 | 主要缺失面 |
| --- | ---: | --- | --- |
| [test_compilation.py](../../../tests/unit/parsing/test_compilation.py) | 6 | `quantumarticle` 哈希绑定重试、保留已有同名 `.bbl`、引擎白名单、`.fls` 绝对路径过滤 | 子目录 `entry`、命令行参数注入拦截、编译期源码被篡改检测（`_check_source_copy`）、`.fls` 超 32,768 行限制、`--support-dir` 软链接与同名冲突拦截 |
| [test_compiled_references.py](../../../tests/unit/parsing/test_compiled_references.py) | 7 | `externaldocument` 隔离、`bibunits`/`multibib` 命名空间、BibLaTeX `refsection`、ACM `\bibitem` 注释 | `\nocite{*}` 空请求导致的空真（Vacuous Truth）边界、`bibunit` 内联 `\bibitem`、`.bcf` 含 `<!DOCTYPE`/`<!ENTITY` 拒绝、非 UTF-8 `.aux`/`.bbl`/`.bib` 诊断降级 |
| [test_material_contract.py](../../../tests/unit/parsing/test_material_contract.py) | 3 | 字节/字符/行号一致性、缺失尾部检测、`safe_path` 逃逸 | 节点父子重叠/乱序/环路（`_validate_children`/`_validate_roots`）、伪造 `status="ready"` 但前置条件未完成拦截 |
| [test_material_conversion.py](../../../tests/unit/parsing/test_material_conversion.py) | 20+ | `\end{document}` 尾部掩码、`\if 0`、布局/文献条件守卫、位置绑定宏签名、引用/标签包装宏、表格跨行跨列、大小写不敏感图片匹配 | 多文件拼接边界插入分隔符（`EntryCoordinates` 偏移回映）、节点深度 >128 超限安全降级、随机混合语法树全覆盖铺满 |
| [test_normalized_latex.py](../../../tests/unit/parsing/test_normalized_latex.py) | 8 | `$`/`$$` 替换、单参引用包装展开、`article` 内联 `.bbl`、映射完整性校验 | 随机复合编辑下的双向投影与逆向还原守恒 |
| [test_compilation.py (integration)](../../../tests/integration/pipeline/test_compilation.py) | 5 | 真实 TeX 编译（需 `QECGRAPH_TEST_TEX=1`）、沙箱禁网与禁外部文件、`normalized.tex` 往返编译 | `etex` $\to$ `dvips` $\to$ `ps2pdf` 短路控制、`pdftotext` 页面文本不一致阻断 `ready`、`pdftotext` 失败/超时降级 |
| [test_material.py (integration)](../../../tests/integration/pipeline/test_material.py) | 6 | `.attempt` 保护已发布 `ready`、编译前快照原包、禁止调用科学解析器与 LLM | CLI `tools/prepare_compiled.py` 的 `--check`/`--recover`/退出码 `0/1/2` 端到端契约 |

### 2.2 代码静态审计发现的潜在边界问题

1. **子目录入口（`entry="sub/main.tex"`）的 `.bbl` 路径匹配**：[build.py](../../../qecgraph/preparation/build.py) 第 114、209 行使用 `job = Path(entry).stem` 检查 `job + ".bbl" in tree.files`，当入口位于子目录且附带 `sub/main.bbl` 时无法命中根目录 `main.bbl`。
2. **`\nocite{*}` 空真（Vacuous Truth）边界**：[references.py](../../../qecgraph/preparation/references.py) 第 147、222 行过滤掉 `"*"` 后，若全文无其他显式 `\cite{key}`，`requested` 为空集合，`all(r["status"] == "resolved" for r in references)` 对空列表恒为 `True`。
3. **包内残留旧子文件 `.aux` 清理范围**：[build.py](../../../qecgraph/preparation/build.py) 第 211–224 行仅清理主任务名 `job + ".aux"`，未清理归档包内可能附带的旧子文件 `.aux`。
4. **非主作用域（`bibunit` / `multibib`）的内联 `\bibitem`**：[references.py](../../../qecgraph/preparation/references.py) 第 187 行 `_inline_entries` 仅扫描 `active.get("0", "")`。
5. **无前缀 `\externaldocument` 与主文同名标签**：[crossrefs.py](../../../qecgraph/preparation/crossrefs.py) 第 40–55 行将主文内部标签匹配数与外部导入标签匹配数直接相加，同名时判为 `ambiguous`。
6. **引用包装宏含注释时的正则差异**：[citations.py](../../../qecgraph/preparation/citations.py) 使用 `group()` 跳过注释，而 [normalized.py](../../../qecgraph/preparation/normalized.py) 第 153 行使用 `re.fullmatch` 匹配调用切片。

---

## 3. 待实现的测试矩阵

### 3.1 属性测试套件（`tests/unit/parsing/test_preparation_properties.py`）

| 测试编号 | 目标模块 | 核心不变量（Invariant） | 预期断言 |
| --- | --- | --- | --- |
| **PBT-01** | `convert.py` + `contract.py` | **源码全覆盖无重叠铺满（Full Tiling Invariant）**：随机生成含章节、定理、表格、TikZ、数学公式、UTF-8 字符及未闭合花括号尾部的文档，`roots` 首尾相接精确覆盖 `[0, len(entry.tex))`。 | `validate_material` 通过；所有根节点 `source_spans` 原始字节拼接严格等于 `entry.tex`。 |
| **PBT-02** | `assembly.py` + `convert.py` | **跨文件拼接与分隔符回映不变量（Include Splice Coordinate Composition）**：多层 `\input` 子文件末尾含无换行注释或控制词、触发 `EntryCoordinates` 插入分隔符时，所有节点坐标精确回映原文件。 | 每个节点的 `source_spans` 原文件字节切片拼接严格等于 `entry.tex[start:end]`。 |
| **PBT-03** | `normalized.py` | **双向投影守恒与逆向还原（Normalized Bijective Tiling & Inverse）**：混合 `$`/`$$`、宏参数内数学、`verbatim`、引用包装宏与 `.bbl` 内联。 | `validate_normalized` 通过；按 `segments` 的 `input_range` 逆向拼接 100% 还原 `entry.tex`。 |
| **PBT-04** | `contract.py` (`SourceIndex`) | **UTF-8 多字节字符/字节/行号三元映射不变量**：随机组合 1～4 字节 UTF-8 字符与 `\n`/`\r\n` 换行。 | `raw[low:high].decode("utf-8") == text[a:b]` 且行号精确匹配。 |

### 3.2 蜕变测试套件（`tests/unit/parsing/test_preparation_metamorphic.py`）

| 测试编号 | 蜕变关系（Metamorphic Relation） | 预期输出关系 |
| --- | --- | --- |
| **MT-01** | **注释注入不变性（Comment Injection Invariance）**：在文件头、章节、`\cite{k1, k2}` 内部、`\ref` 后注入含伪造 `\cite`/`\label`/`\ref` 的 `%` 注释。 | `outline`、`citations`、`labels`、`cross_references` 解析结果与基准完全一致。 |
| **MT-02** | **死分支噪声隔离（Inactive Branch Mutation Invariance）**：在 `\if 0 ... \fi` 内部及 `\end{document}` 之后注入未绑定 `\cite`、缺失 `\ref`、重复 `\label` 与未闭合 `\end{broken}`。 | 保持 `coverage["complete"] == True`、`syntax_complete == True`，激活区零污染。 |
| **MT-03** | **子文件拆分与内联等价性（Include Factoring Equivalence）**：将单文件 `main.tex` 的章节拆分为多个子目录 `.tex` 并通过 `\input` 引入。 | 组装后的 `entry.tex`、`outline`、`citations`、`cross_references` 完全等价。 |
| **MT-04** | **未使用 `.bib` 条目与 `@CONTROL` 增删不变性**：向 `refs.bib` 注入未引用条目及 RevTeX `@CONTROL` 记录。 | `references["bindings"]` 与 `complete` 状态不变，`excluded_control_keys` 与 `original_bib_entries` 精确记录。 |
| **MT-05** | **位置受限宏重定义局部性（Positional Macro Redefinition Locality）**：在文档中段通过 `\renewcommand` 或声明别名链改变宏参数个数。 | 重定义位置之前的宏调用参数列表严格不变，之后的调用按新签名解析。 |

### 3.3 对抗、安全边界与差分测试套件（`tests/unit/parsing/test_preparation_adversarial.py`）

| 测试编号 | 目标模块 | 测试场景与载荷 | 预期响应 |
| --- | --- | --- | --- |
| **ADV-01** | `references.py` | `.bcf` 含 `<!DOCTYPE` 或 `<!ENTITY`（XXE / Entity 注入） | 抛出 `ValueError("BCF document types and entities are unsupported")` |
| **ADV-02** | `build.py` | 编译期间 `.tex`/`.sty` 被篡改字节 | `_check_source_copy` 置 `build.success = False` 并记录 `source_changed_during_build` |
| **ADV-03** | `build.py` | `entry` 含 `-shell-escape`/`../`；`.fls` 含路径穿越或超过 32,768 行 | 拒绝非法 `entry`；忽略沙箱外 `.fls` 路径；超行数抛 `ValueError` |
| **ADV-04** | `build.py` | `--support-dir` 为软链接、内含软链接文件、或多目录含同名冲突文件 | `_support` 抛出对应 `ValueError` 拒绝 |
| **ADV-05** | `convert.py` + `pipeline.py` | 超过 128 层深层嵌套花括号 `{ { ... } }` | 捕获 `Material token depth/count limit exceeded`，安全降级为 `partial` 且保留原文件 |
| **ADV-06** | `contract.py` | 篡改 `manifest.json` 将失败构建伪造为 `status: "ready"` | `validate_material` 抛出 `ValueError` 拦截 |
| **ADV-07** | `tools/prepare_compiled.py` | CLI 正常构建、`--check`、`--recover` 及篡改产物后的 `--check` | 退出码严格为 `0`（成功/校验通过）与 `1`（篡改校验失败） |
| **DIFF-01/02** | `roundtrip.py` | 原包与 `normalized.tex` 的 `pdftotext` 页面文本不一致，或 `pdftotext` 失败/超时 | `pdf_text` 记为 `"different"` 或 `"failed"`，`report["complete"] == False` |
| **DIFF-03** | `build.py` | Harvmac 触发 `etex`（含 `stdin="b\n"`）$\to$ `dvips` 失败时的短路控制 | 自动选 `etex`，`dvips` 失败后绝不继续调用 `ps2pdf` |
| **DIFF-04** | `references.py` | `.aux`、`.bbl`、`.bib` 含非 UTF-8 字节（`\xff\xfe`） | 不崩溃，`complete == False` 并记录 `bibliography_encoding` 与 `bib_encoding` |

---

## 4. 交付与分层执行策略

- 将上述三类测试拆分为三个独立测试模块置于 `tests/unit/parsing/` 下，全部使用 Python 标准库与确定性随机种子实现，无需额外安装第三方依赖，单次全量运行控制在 `0.5s` 以内。
