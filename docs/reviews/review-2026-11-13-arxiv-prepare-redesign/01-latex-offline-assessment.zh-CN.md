# LaTeX 包离线归一化评估与实施方案

> 状态：评估记录与实施建议，尚未实施。日期：2026-11-13。本文不代表改造已完成，也不替代当前系统设计。

本文整理本轮对 test-sources 的离线评估、实测结果、统一格式建议、实施步骤和验收标准。评估阶段没有修改项目代码、正式配置、原始包或解压后的来源文件；本次仅将评估写入 Markdown。没有调用真实 AI provider，没有上传论文来源。

当前实现以 [系统设计](../../design/DESIGN.md) 为准；样本说明和来源清单见 [测试来源说明](../../../test-sources/arxiv-sources/README.md) 与 [manifest.json](../../../test-sources/arxiv-sources/manifest.json)。

## 目录

- [1. 结论与目标边界](#1-结论与目标边界)
- [2. 评估对象与可复现基线](#2-评估对象与可复现基线)
- [3. 离线试跑结果](#3-离线试跑结果)
- [4. 影响方案的关键发现](#4-影响方案的关键发现)
- [5. 建议的统一输出格式](#5-建议的统一输出格式)
- [6. 离线处理流程与格式适配](#6-离线处理流程与格式适配)
- [7. 分阶段实施方案](#7-分阶段实施方案)
- [8. 成功率定义与验收标准](#8-成功率定义与验收标准)
- [9. 逐包结果与失败案例](#9-逐包结果与失败案例)
- [10. 实际执行命令与证据](#10-实际执行命令与证据)
- [11. 未完成的验证与后续限制](#11-未完成的验证与后续限制)
- [12. 外部依据](#12-外部依据)

## 1. 结论与目标边界

可以实施默认离线的包识别、文件组织、正文读取和参考文献抽取。现有样本已经证明，程序能快速处理大量常见格式；需要补齐的是文档边界、依赖展开、参考文献适配和内容完整性检查。

建议把机械导入与可选的 AI 语义抽取分开。离线导入不应依赖 API key，也不应等待研究问题、方法、贡献或隐含假设等语义提议的生成。后者可以在导入完成后按需执行，结果继续保持 proposed，不自动成为人工审核或 verified 事实。

应分别理解三种目标：

| 目标 | 本轮判断 |
| --- | --- |
| 把不同包统一为可读取、可追溯的研究输入 | 可行，建议实施 |
| 生成 Markdown、书目导出、图片及支持文件 | 可行，但必须标明缺失和转换限制 |
| 对任意包恢复字段齐全的原始 BIB，并保证重新编译等价 | 无法普遍保证，需要单独验收 |

这里的“统一”主要指稳定的目录、文档模型、引用范围和来源接口。一个包可以包含主文、独立补充材料或其他文档，不应为了只留下一个文件而强行抹去这些边界。

本轮得到的是工具执行率和结构导入率，尚未得到经独立人工核对的完整转换率。83.0% 不能直接宣传为未来生产导入成功率，90% 也只是可考虑的工程目标。

## 2. 评估对象与可复现基线

### 2.1 样本与范围

样本目录为 `test-sources/arxiv-sources/`，包含 48 个原始下载包：

| 类型 | 数量 | 处理范围 |
| --- | ---: | --- |
| gzip 压缩的 tar 来源包 | 43 | 纳入 TeX 评估 |
| gzip 压缩的单个 TeX 文件 | 4 | 纳入 TeX 评估 |
| PDF | 1 | 非 TeX 对照，不计入转换率分母 |
| 合计 | 48 | TeX 评估分母为 47 |

47 个 TeX 包中包含两篇论文的多个版本。因此，这不是 47 篇相互独立、随机抽样的论文。样本是刻意覆盖不同格式的开发材料，不能直接估计任意未来投稿的成功概率。

已覆盖的主要情况包括单文件、嵌套章节、独立补充材料、subfiles、subimport、宏构造路径、旧式 documentstyle、Plain TeX、内嵌文件、传统 BBL、biblatex/Biber、多段参考文献、旧编码和 XeLaTeX 元数据。

本轮没有读取 QEC-database 的 human、私人笔记或凭据，也没有改动原库。

### 2.2 版本与身份

| 项目 | 固定值 |
| --- | --- |
| 评估日期 | 2026-11-13 |
| 代码 commit | `41f9b9211a0f33a8105ed8d174e9bf3e44f8f712` |
| 样本 manifest SHA-256 | `153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b` |
| 本轮临时工作区 release | `4227292310531f08a0fdf7fd8f662233dd9ca472005b567797dd97de50b47a2a` |
| 随样本保存的 smoke commit | `c3eda05edd3a360ebf01a260f1b7783f11ae8d69` |
| 随样本保存的 smoke release | `837de9f1cb45cab37a9419b23b96554e654f24be2f81dac2a2296a21d98af885` |
| Pandoc | 3.13 |
| latexpand | 1.7.2 |
| 测试解释器 | Python 3.15.2，项目 .venv |
| pylatexenc | 2.10 |
| jsonschema | 4.26.0 |
| SQLite | 3.54.1，FTS5 可用 |
| 运行平台记录 | macOS-27.2.1-arm64-arm-64bit-Mach-O |

运行环境值来自实际复现报告。转换工具耗时为本机单次探测，使用普通文件系统缓存，不是稳定性能承诺，也没有与在线 AI 耗时进行可比基准测试。

### 2.3 来源完整性

试验后再次校验：

- 48 个原始包的 SHA-256 全部与 manifest 一致。
- 1,664 个解压后的普通文件全部与对应归档成员的原始字节一致。
- 评估结束时 Git 工作区保持干净；后续保存本记录及整理评审目录属于文档变更。
- 转换输出和诊断全部位于临时目录，原始来源未被重写。

## 3. 离线试跑结果

### 3.1 当前 qec-graph 的基线

当前实现已经是程序优先，AI 只在配置允许时参与可选恢复或语义抽取。不能把现有流程描述为完全依赖 AI 才能导入。

本轮在新建的临时工作区中关闭 AI、关闭来源上传、关闭 human 渲染，复制 47 个 TeX 包后执行 sync：

| 状态 | 数量 | 占 47 个包的比例 |
| --- | ---: | ---: |
| processing_completed | 26 | 55.3% |
| needs_entrypoint | 12 | 25.5% |
| parse_failed | 5 | 10.6% |
| unsupported_encoding | 2 | 4.3% |
| damaged_archive | 2 | 4.3% |

每个包的状态均与样本目录保留的 smoke 记录一致。

- sync 耗时 17.34 秒，退出码 2，状态为 partial_batch。
- 47 个 TeX 包均登记，26 个完成现有结构处理。
- 本轮输出含 179 个规则生成的 code_mention_proposals，不代表已验证的码实例。
- workspace validate 通过，耗时 1.31 秒，退出码 0。
- 现有复现脚本通过，内部执行的单元测试共 376 项通过。

processing_completed 表示当前支持语法下的结构导入完成。工作区校验通过表示发布完整性和引用等检查通过；两者都不证明完整读取了所有论文内容，也不证明数学正确性。

### 3.2 三种工具路径的对照

| 路径 | 包级结果 | 分母与通过条件 | 本机耗时 |
| --- | ---: | --- | ---: |
| 当前 qec-graph，AI 关闭 | 26/47，55.3% | 原始包完成现有严格结构导入 | 17.34 秒 |
| Pandoc 普通 LaTeX reader | 39/47，83.0% | 已解压包的全部所选入口均生成 Markdown | 4.20 秒 |
| latexpand 后接 Pandoc | 35/47，74.5% | 已解压包的全部所选入口均完成展开并通过 Pandoc 解析 | 8.25 秒 |

后两种工具路径使用三个并发转换进程。它们没有执行完整的归档、来源映射、图谱构建、发布和质量验收，不能与第一行直接解释为改造前后性能或质量提升。

### 3.3 Pandoc 普通 LaTeX reader

入口选择借助已有样本清单和来源目录，规则如下：

| 入口依据 | 包数 |
| --- | ---: |
| arXiv 00README.json 明确指定顶层入口 | 15 |
| 清单中只有一个词法文档候选 | 22 |
| 多入口未消歧，逐个尝试所有候选 | 8 |
| 无现代文档根，尝试唯一旧式来源 | 2 |

合计尝试 57 个文档入口：

- 49 个入口生成 Markdown。
- 39 个包的全部所选入口生成 Markdown。
- 41 个包至少有一个入口生成 Markdown；这个较弱条件不能作为包导入成功标准。
- 7 个成功入口仍有警告，包括缺失 include、宏重复定义和编码回退。
- 48 个成功入口的 AST 仍含原始 TeX 成分。原始 TeX 可能是必要保留，也可能代表没有结构化处理，必须分别检查。
- 本轮没有对所有结果执行独立正文金标、公式等价、引用解析、资产完整性或重新编译验收。

### 3.4 显式开启 raw_tex 的诊断对照

使用 `latex+raw_tex` 时，52/57 个入口生成 Markdown，42/47 个包的全部所选入口返回成功，耗时约 3.24 秒。

这个数字高于普通 reader，但它保留了许多没有展开的 include 指令，不能据此认为转换更完整。

QEC 教程 `2605.29137v1` 的对照非常明显：

| 指标 | latex+raw_tex | 普通 latex |
| --- | ---: | ---: |
| Markdown 字节数 | 4,801 | 740,725 |
| 原样残留的 subfile 指令 | 14 | 此项未单独统计 |
| AST 标题节点 | 14 | 162 |
| AST 数学节点 | 0 | 5,643 |

较小的输出保留了章节调用，却没有读入章节正文。两个命令都成功退出。字节数和节点数本身也不是完整性金标，但这个例子证明了退出码不能替代内容检查。

### 3.5 latexpand 加 Pandoc

执行 `latexpand --keep-comments --fatal`：

- 50/57 次展开返回零退出码。
- 43/57 次同时通过后续 Pandoc 解析。
- 35/47 个包的全部所选入口通过两个步骤。
- 问题包括宏构造的输入路径、宏定义内部的 input、缺失依赖和旧式 TeX。
- latexpand 会读取本机安装的 TeX 资源，因此这一结果也依赖本地 TeX 环境，不代表已经生成完全自包含的工程。

不能把所有输入都无条件交给 latexpand 后再交给 Pandoc。官方资料还明确说明 latexpand 不处理 includeonly；其本地帮助列出了 verbatim、注释环境等已知限制。

### 3.6 BIB 与 BBL 盘点

按是否存在独立书目文件划分，三类互不重叠：

| 独立书目资产 | 包数 |
| --- | ---: |
| 存在 .bib，无论是否也有 .bbl | 27 |
| 无独立 .bib，但存在 .bbl | 9 |
| 既无独立 .bib，也无 .bbl | 11 |

27 个包共有 38 个独立 .bib 文件。另一个包 `2605.30298v1` 在 filecontents 中内嵌了 `\jobname.bib`；它已包含在“只有独立 BBL”的 9 个包中，不能再次作为额外的第 48 个 TeX 包计数。

9 个只有独立 BBL 的包中，3 个使用 biblatex/Biber BBL，6 个使用传统 BBL。

Pandoc 的 BibLaTeX reader 接受了 33/38 个 .bib 文件：

- 4 个失败文件含 REVTeX 的 @CONTROL 控制记录，属于控制或 notes 辅助文件，不能直接按普通参考文献数据库处理。
- 另一个失败是 `CP_violation_refs.bib`，引用键含 reader 不接受的特殊字符。
- 有些文件存在重复键；不同数据库、主文和补充材料之间也有相同键。
- 文件可解析不代表全部字段被正确保留，也不代表引用已经全部解析。

## 4. 影响方案的关键发现

### 4.1 正确入口不等于正文完整

`2605.29137v1` 的 00README.json 明确指定 main.tex，现有入口逻辑却把许多 subfiles 章节也当成候选。

进一步直接指定 main.tex 后，现有解析器只读取：

- main.tex；
- supporting-files/macros.tex；
- supporting-files/references.bib。

14 个 subfile 章节正文没有读入，而且没有对应错误。输出的 362 个块中，319 个是 bib_entry；块数较多不能证明正文覆盖充分。

因此，需要同时解决根识别、实际依赖展开和覆盖检查，不能仅靠自动填写 entrypoint。

### 4.2 BBL 无法普遍恢复完整原始 BIB

传统 BBL 是按样式生成的参考文献表示，部分原始字段可能已被省略。例如 `1208.2317v1/ft-def25.bbl` 中有条目只保留作者、期刊、卷页和年份，没有文章标题。

离线程序可以保留条目全文，并抽取明确存在的作者、DOI、年份等字段，但不能凭空恢复缺失标题或原始数据库内容。

建议按材料类型处理：

| 来源类型 | 离线策略 | 必须保留的限制 |
| --- | --- | --- |
| 原生 BibTeX、BibLaTeX | 解析字段、字符串和来源 | 重复键、宏和冲突不能静默覆盖 |
| filecontents 内嵌 BIB | 提取原始字节并记录来源区间 | jobname 与文件名解析需有依据 |
| biblatex/Biber BBL | 按其结构读取已有字段和范围 | 不宣称恢复全部原始数据库语义 |
| 传统 BBL、内联 bibitem | 保存完整原文，抽取字面字段 | 缺失字段保持 unknown |
| 信息不足的条目 | 导出部分记录，必要时使用 @misc | 不能把占位或原始文本伪装成完整元数据 |

可提供统一 references.bib，但应同时保留 references.json，以容纳原始条目、字段缺失、来源位置和解析状态。

### 4.3 多文档与引用范围必须保留

`2408.13687v1`、`2412.14256v1` 等包包含独立主文和补充材料，各有导言区、编号、引用和书目。

不能简单删除第二份导言区或 end{document} 后拼接。合并可能造成宏定义冲突、标签冲突、重复引用键和编号变化。

建议在同一论文来源版本下建立多个 document scope，明确主文、补充材料和未判定文档。书目键和标签应绑定文档及 refsection 等范围。没有证据时不把补充材料变成另一篇论文，也不靠文件名猜定主次。

### 4.4 编码、旧格式和缺失依赖各自处理

- `2607.00262v1` 的 utf8x 声明被现有白名单拒绝，可评估显式编码别名适配。
- `2209.05640v1` 有未明确声明的非 UTF-8 字节。Pandoc 给出警告后回退到 Latin-1；这不是正确解码已经得到确认的证据。
- 两个旧 tar 被现有严格 reader 拒绝，应单独研究有界、可审计的兼容读取，不能静默放松归档校验。
- `2308.07915v2` 缺少 packages.tex。材料缺失不能通过选择一个能返回成功的入口来掩盖。
- 系统 TeX 宏包与作者应随包提供的正文依赖需要区分，不能将所有缺失都直接忽略。

## 5. 建议的统一输出格式

建议生成以下派生包。文件名和字段布局是实施建议，尚未成为当前协议：

~~~text
normalized/
  main.tex
  documents/
    <document-id>/
      main.tex
  paper.md
  document.json
  references.bib
  references.json
  assets/
  support/
  manifest.json
  source-map.json
  diagnostics.json
~~~

| 产物 | 用途与约束 |
| --- | --- |
| main.tex | 主文的规范化来源表示；保留到原始文件的映射 |
| documents/ | 独立补充材料等文档；保留各自作用范围 |
| paper.md | 阅读和文本检索的派生视图，可按主文与补充材料顺序组织 |
| document.json | 共用的结构化结果，包含章节、段落、公式、定理环境、标签和引用 |
| references.bib | 面向外部工具的书目导出；允许明确标记的部分记录 |
| references.json | 原始条目、字段值、缺失状态、范围、来源和解析限制 |
| assets/ | 原始图片、图形和其他资产；保留原始字节及路径映射 |
| support/ | cls、sty、bst、def、TikZ 等支持材料；不能因不认识而丢弃 |
| manifest.json | 文档清单、角色、入口、依赖、工具版本、哈希和处理状态 |
| source-map.json | 派生内容到原始来源的映射，合成标记与原始内容明确区分 |
| diagnostics.json | 未解析语法、缺失依赖、歧义、编码和转换限制 |

需遵守以下原则：

1. 原始归档保持权威地位；规范化产物可重建，不覆盖原始来源。
2. main.tex、Markdown、JSON 和 BIB 导出由共用解析结果生成，不形成多份可双向编辑的事实来源。
3. 图谱直接消费共用结构化结果与原始来源映射，避免先做有损 Markdown 转换，再从 Markdown 猜回原结构。
4. 保留 UTF-8 原始字节、原始哈希、稳定身份及位置约定：Unicode codepoint 半开区间、行号从 1 开始。
5. 编码投影需记录原始编码和对应关系。派生文本位置不能冒充原文位置。
6. 资产搬移或重命名时同步维护引用映射，不将同名文件无条件覆盖。
7. 论文身份不能因入口改名为 main.tex 或归一化内容哈希变化而被重新解释。

规范化阅读用 main.tex 不自动等于可重新编译、排版等价的工程。编译还可能依赖宏包版本、字体、引擎、jobname 和额外资源，应作为独立验收维度。

## 6. 离线处理流程与格式适配

~~~mermaid
flowchart TD
    A["不可变原始包"] --> B["内容识别与有界解包"]
    B --> C["文档根、角色和依赖图"]
    C --> D["离线解析与来源映射"]
    D --> E["共用文档结构与书目模型"]
    E --> F["main.tex / Markdown / BIB / 资产"]
    E --> G["结构图谱与检索"]
    F --> H["覆盖检查与诊断"]
    G --> H
    H --> I["验证并原子发布"]
    I --> J["按需执行可选语义抽取"]
~~~

### 6.1 解包、入口与依赖

复用现有内容识别、有界解包、哈希归档和编码投影。入口判定优先考虑：

1. 已有明确用户配置；
2. 经校验的 00README 元数据；
3. 现代或旧式文档声明；
4. 实际文件依赖关系及文档范围。

元数据中的编译用 ignore 标记不应被直接解释为“可以删除该文件”；实际被正文引用的依赖仍需处理。

需要支持普通及无括号 input、include、subfile、import、subimport，明确根目录与当前文件目录的解析规则。对常量路径宏做有界处理，对动态路径、无法判断的条件和结构宏明确报告限制。

不按 arXiv 编号写逐篇补丁，不按“最长文件”或“叫 main.tex”自动消歧。多个合理入口可以先以多文档形式完整保留；未确认的角色维持未确认状态。

### 6.2 来源正文

需处理或明确诊断：

- 注释、verbatim 和宏定义内部的伪 include；
- 活跃与非活跃的附录、章节和条件分支；
- 嵌套相对路径；
- filecontents 中的 BIB 或图片；
- 定理、证明、公式、表格和图片边界；
- 不支持的自定义宏与环境；
- 独立补充材料被正文再次 include 的情况。

对可判定的情况应用确定规则；不能解析的正文保留原始材料并标记 partial，不能悄悄丢弃后声称 complete。

### 6.3 书目与引用

书目适配器应覆盖：

| 类型 | 样本或覆盖点 |
| --- | --- |
| 原生 BIB、多 BIB | 2012.04068v1、2207.06431v1 |
| 只有传统 BBL | 1208.2317v1、1907.02554v1 |
| 显式 input BBL | 1907.02554v1、2009.07851v3 |
| BBL 与主文件不同名 | 2510.06495v2 |
| 内联 thebibliography | 2202.13641v1 |
| 独立 references.tex | 2605.29554v1 |
| 旧 references 环境 | quant-ph/0110143v1 |
| mcitethebibliography | 2410.02885v1 |
| biblatex/Biber BBL | 2303.15933v1、2512.07737v1 |
| 内嵌 BIB 与 jobname | 2606.30447v1、2605.30298v1 |
| multibib、bibunits | 2606.00045v1、2607.00222v1 |
| 多 refsection | 2607.00262v1 |

引用解析先确定 document scope 和 bibliography scope，再处理键与字段。重复键保持歧义；同名条目不能被无声覆盖；来源主张冲突应保留。只有明确存在的字段才作为抽取值，缺失不等于不存在。

### 6.4 工具选择

Pandoc 适合继续作为快速离线转换候选，但需要适配层、参数约束和来源映射整合。它的 AST 并不自动满足本项目的精确来源要求。

latexpand 可用于部分普通工程的展开探测，不适合作为所有输入必经的通用步骤。本轮它对宏路径和依赖的处理降低了通过率。

LaTeXML 可作为复杂宏和旧格式的离线候选后端另行评测。其处理依赖包对应的 binding，不能预先承诺全覆盖。本机未安装，本轮没有测试其成功率或耗时。

若将来为了编译核对而执行 TeX，应使用固定的离线工具链、受限文件系统、禁用 shell escape 并设置资源上限。编译检查与静态来源抽取分别报告，不能用编译通过代替来源映射和内容验收。

## 7. 分阶段实施方案

### 7.1 阶段一：固定验收口径与样本预期

先定义每个包应包含哪些文档、正文、附录、引用和资产。对主要格式建立人工核对的预期，再开始调整适配器，避免用当前输出反过来定义正确答案。

交付内容：

- 固定版本与哈希的样本清单；
- 主文、补充材料和章节依赖预期；
- 引用键、重复键和缺失字段预期；
- 内容覆盖与来源保真检查；
- 与开发样本分离的新包测试集；
- ZIP、实际 includeonly、chapterbib 和确认的 LuaLaTeX 缺口样本。

本阶段的完整率指标需要先约定，再用于调优和发布判断。

### 7.2 阶段二：确定性入口与依赖归一化

复用归档和来源模型，新增或完善元数据读取、旧式根识别、多文档范围、include 关系及有界宏路径处理。

优先解决收益明确的场景：00README 指定入口、subfiles 章节、普通嵌套输入、独立补充材料和 filecontents。

验收不仅检查选中了正确主文件，还必须核对所有应读入的章节。QEC 教程漏 14 章的案例应成为必须防止的真实回归。

### 7.3 阶段三：分范围的书目归一化

实现原生 BIB、嵌入 BIB、传统 BBL、结构化 BBL 和内联条目的适配，保留文档和参考文献段落范围。

输出统一中间记录，再生成 references.bib 和 references.json。不能长期让两种格式分别成为同一字段的可编辑权威。

验收覆盖重复键、原文缺字段、宏字符串、控制记录、多个参考文献区和正文引用无法解析的情况。允许 partial，但必须可解释。

### 7.4 阶段四：共用结构生成阅读与机器产物

让文件切割、图谱、Markdown 和书目导出共用解析结果。对 Pandoc 等后端的输出增加来源追踪与覆盖检查。

保留公式、定理/证明边界、标签和引用键；不支持的原始构造必须可见。生成阅读文档时不能把原始引用或来源坐标丢掉。

对重编译、图形渲染等能力单独记录，不与“已完成正文抽取”混用一个成功标志。

### 7.5 阶段五：接入工作区并分离 AI

接入现有归档、stage、validate、原子发布、失败恢复和消费流程，保持旧 CLI 兼容。

建议的行为：

- 默认机械导入可完全离线运行，不依赖 AI。
- 可选语义任务在导入完成后按需执行，不阻塞结构发布。
- 来源上传仍需显式配置，不因存在 API key 而启用。
- 保留旧 release、旧证据和审核绑定，不为了消除 stale 刷新哈希。
- 解析语义或依赖变化时提升相应 PARSER_VERSION/RULE_VERSION 并回放来源。
- 新协议在实施时同步更新唯一的 DESIGN 文档；破坏性变化提供显式迁移。

完成导入、解析或检索相关修改后，在固定 release 的 QEC-database machine 副本上运行适用评测。只读取已登记的机器数据，不读取 human、私人笔记或凭据，不修改原库，也不因评测默认调用模型。

## 8. 成功率定义与验收标准

### 8.1 分开统计各层结果

| 指标 | 成功含义 |
| --- | --- |
| 归档接收率 | 原始包可验证地保存并按已支持格式读取 |
| 入口识别率 | 所有应处理文档均被识别，角色歧义明确 |
| 依赖覆盖率 | 应纳入的章节、附录和支持资源均有处置结果 |
| 正文完整率 | 独立核对的正文和补充材料无静默遗漏 |
| 书目覆盖率 | 活跃引用可解析到对应范围内条目，或明确标为未解析 |
| 资产完整率 | 引用的图片等资产可追溯，缺失明确报告 |
| 来源保真率 | 原始字节不变，返回的来源位置可核对 |
| 编译通过率 | 在指定工具链下成功编译，单独统计 |
| 完整离线处理率 | 包满足预先定义的全部必要条件，而非仅退出码为零 |

可使用 complete、partial、ambiguous、missing dependency、unsupported 等区分结果；具体字段和值在实施时纳入版本化协议。

### 8.2 建议目标

- 原始归档与来源字节保真要求 100%。
- 独立核对的案例中，静默漏正文或漏补充材料应为零。
- 被标记 complete 的结果必须覆盖应处理依赖，并交代引用、资产和不支持语法；关键缺失应降级为 partial。
- 可把完整离线处理率至少 90% 作为首轮工程目标，但这不是本轮测得的结果或已经保证的能力。
- 达到开发集目标后，必须用独立新包检验，不能只在这批格式样本上继续调参后报告同一数字。
- 对确实缺材料、编码无法确认或超出支持语法的包，保留原始归档和诊断，不能为了通过率制造信息。

### 8.3 科学与检索验收

结构转换完成不等于知识服务已经 Usable。后续仍遵守 DESIGN §16.8：

- 固定实际代码、数据与 release。
- 对实际论文进行来源、标题作者、章节和抽取覆盖核对。
- 检索可用性需要独立人工标注的问题集；现有工程 smoke 不能替代。
- 科学回答质量、语义抽取准确性和人工审核身份单独记录。
- 对语义提议不自动提升审核状态。
- 在相同输入和固定 release 上报告可比较的前后数字；没有金标的项目明确记为未验收。

## 9. 逐包结果与失败案例

### 9.1 逐包执行记录

“Pandoc 成功/尝试入口”仅表示普通 LaTeX reader 生成了 Markdown。它不证明正文、参考文献、公式或资产完整。多入口包可能包含模板和单独编译片段，不能只凭这个表判断论文角色。

| 来源包 | 当前结构导入状态 | Pandoc 成功/尝试入口 |
| --- | --- | ---: |
| 0903.0566v1 | parse_failed | 1/1 |
| 1208.0928v1 | PDF 对照 | 未纳入 |
| 1208.2317v1 | processing_completed | 0/1 |
| 1302.3428v1 | processing_completed | 1/1 |
| 1804.03719v1 | needs_entrypoint | 1/2 |
| 1907.02554v1 | processing_completed | 1/1 |
| 1907.11157v1 | processing_completed | 1/1 |
| 2009.07851v3 | processing_completed | 1/1 |
| 2012.04068v1 | processing_completed | 1/1 |
| 2012.09271v1 | processing_completed | 1/1 |
| 2102.06132v1 | processing_completed | 1/1 |
| 2103.02202v1 | processing_completed | 1/1 |
| 2103.06309v1 | needs_entrypoint | 2/2 |
| 2104.01180v1 | processing_completed | 1/1 |
| 2111.05176v1 | needs_entrypoint | 4/4 |
| 2201.08309v1 | parse_failed | 1/1 |
| 2202.13641v1 | processing_completed | 1/1 |
| 2207.06431v1 | processing_completed | 1/1 |
| 2209.01119v1 | processing_completed | 1/1 |
| 2209.05640v1 | unsupported_encoding | 1/1 |
| 2303.15933v1 | processing_completed | 1/1 |
| 2308.02321v1 | needs_entrypoint | 2/2 |
| 2308.07915v1 | needs_entrypoint | 2/2 |
| 2308.07915v2 | needs_entrypoint | 1/2 |
| 2408.13687v1 | needs_entrypoint | 2/2 |
| 2410.02885v1 | processing_completed | 0/1 |
| 2411.11822v1 | processing_completed | 1/1 |
| 2412.14256v1 | needs_entrypoint | 2/2 |
| 2509.03613v1 | processing_completed | 0/1 |
| 2510.06495v2 | processing_completed | 1/1 |
| 2511.01062v1 | parse_failed | 1/1 |
| 2511.01062v2 | needs_entrypoint | 1/1 |
| 2512.07737v1 | processing_completed | 1/1 |
| 2605.29137v1 | needs_entrypoint | 1/1 |
| 2605.29554v1 | processing_completed | 1/1 |
| 2605.29774v1 | processing_completed | 1/1 |
| 2605.30298v1 | processing_completed | 1/1 |
| 2606.00045v1 | processing_completed | 1/1 |
| 2606.30447v1 | processing_completed | 1/1 |
| 2607.00222v1 | processing_completed | 1/1 |
| 2607.00262v1 | unsupported_encoding | 1/1 |
| 2607.29382v2 | parse_failed | 0/1 |
| 2609.22572v1 | processing_completed | 1/1 |
| hep-th/9407087v1 | damaged_archive | 0/1 |
| quant-ph/0001106v1 | parse_failed | 1/1 |
| quant-ph/0110143v1 | needs_entrypoint | 1/1 |
| quant-ph/9604034v1 | damaged_archive | 0/1 |
| quant-ph/9605021v1 | needs_entrypoint | 1/1 |

### 9.2 普通 Pandoc 的失败入口

| 来源包 | 入口 | 观察到的失败 |
| --- | --- | --- |
| 1208.2317v1 | ft-def25.tex | 非常规 cite 参数，line 302 的 reader 语法错误 |
| 1804.03719v1 | rrqp.tex | global/long/def 组合，line 48 解析失败 |
| 2308.07915v2 | arXiv_v2.tex | 补充文件缺 packages.tex，随后报文档结束结构错误 |
| 2410.02885v1 | main.tex | mcitethebibliography 结束处解析失败 |
| 2509.03613v1 | main.tex | introduction.tex 中的数学语法解析失败 |
| 2607.29382v2 | main.tex | 宏与文档结构解析失败 |
| hep-th/9407087v1 | 9407087.tex | Plain TeX input 等旧式语法解析失败 |
| quant-ph/9604034v1 | tqecp | 旧式 input 等语法解析失败 |

### 9.3 对实施有代表性的案例

| 来源包 | 观察 | 对实现的要求 |
| --- | --- | --- |
| 2605.29137v1 | 元数据有明确主文件，现有解析器仍漏 subfile 章节 | 根识别与章节覆盖分别验证 |
| 2511.01062v2 | 元数据能区分主文和 cover letter，指定主文件后现有 parser 仍失败 | 元数据解决入口，不自动修复正文语法 |
| 2111.05176v1 | 宏路径、模板、分章节编译入口并存 | 依赖图和文档角色不能只用 documentclass 计数 |
| 2408.13687v1、2412.14256v1 | 主文与补充材料独立 | 保留导言区、标签和引用范围 |
| 2308.07915v2 | 独立结构的补充文件同时被主文 include，部分材料缺失 | 防止重复收录和静默丢失 |
| 1208.2317v1 | qec-graph 接受，Pandoc 因 cite 语法失败 | 不用单一后端是否接受代替来源有效性判断 |
| 2410.02885v1 | mcitethebibliography | 需要专门的书目适配 |
| 2607.29382v2 | 现有 parser 与 Pandoc 均遇到语法问题 | 保留原始片段和具体诊断 |
| 2607.00262v1 | utf8x 白名单限制 | 编码别名与内容解码分别确认 |
| 2209.05640v1 | 未声明的非 UTF-8 字节 | 不把 Latin-1 回退当作正确解码 |
| hep-th/9407087v1 | 归档被拒绝，且使用 Plain TeX/Harvmac | 旧归档与旧语法分别处理 |
| quant-ph/9604034v1 | 归档被拒绝，入口没有 tex 扩展名 | 不能仅靠扩展名识别来源 |
| quant-ph/0110143v1、quant-ph/9605021v1 | documentstyle 旧入口 | 支持有依据的旧式根识别 |
| quant-ph/0001106v1 | 无括号 input BoxedEPS，依赖缺失 | 明确外部支持资源与缺失状态 |

## 10. 实际执行命令与证据

### 10.1 项目基线复现

在项目根目录执行：

~~~sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reproduce.py \
  --out /tmp/qec-offline-assess-50voaejf/reproduce
~~~

该脚本内部执行了：

~~~sh
.venv/bin/python -m unittest discover -s tests -v
~~~

结果为 376 项测试通过；复现脚本还检查了切割、示例工作区发布、校验、搜索和上下文读取。

### 10.2 临时工作区试跑

实际使用以下命令：

~~~sh
.venv/bin/python -m qecgraph init \
  --workspace /tmp/qec-offline-assess-50voaejf/workspace \
  --json

.venv/bin/python -m qecgraph sync \
  --workspace /tmp/qec-offline-assess-50voaejf/workspace \
  --json --progress off --no-human

.venv/bin/python -m qecgraph validate \
  --workspace /tmp/qec-offline-assess-50voaejf/workspace \
  --json --progress off
~~~

init 后只在该临时工作区的配置中设置 `[ai].enabled = false`，并验证 `allow_source_upload = false`。使用 Python shutil.copyfile 将测试目录中的 47 个 gzip 包复制进临时 inputs。没有修改项目或真实数据库的配置。

### 10.3 转换探测脚本

本轮临时编写并执行的探测脚本：

~~~sh
.venv/bin/python /tmp/qec-offline-assess-50voaejf/probe_pandoc_default.py \
  /tmp/qec-offline-assess-50voaejf/pandoc-default

.venv/bin/python /tmp/qec-offline-assess-50voaejf/probe_pandoc.py \
  /tmp/qec-offline-assess-50voaejf/pandoc

.venv/bin/python /tmp/qec-offline-assess-50voaejf/probe_latexpand.py
~~~

这些脚本是评估探针，不是已集成的产品实现或长期维护的项目工具。它们位于临时目录，清理后不能假定仍然存在。

每个入口的主要子命令如下，其中 entry 和 bib-file 是待替换的占位参数：

~~~sh
pandoc -f latex -t json -s "<entry>"
pandoc -f latex+raw_tex -t json -s "<entry>"
pandoc -f json -t markdown+raw_tex+tex_math_dollars+citations \
  -s --wrap=none
latexpand --keep-comments --fatal "<entry>"
pandoc -f biblatex -t csljson "<bib-file>"
~~~

Pandoc 从相应来源树目录读取入口；其 JSON AST 再转换成 Markdown。latexpand 的 stdout 作为后续 Pandoc 输入。源码未在原地展开或覆写。

### 10.4 临时证据清单

完整探测产物位于 `/tmp/qec-offline-assess-50voaejf/`，macOS 上对应 `/private/tmp/qec-offline-assess-50voaejf/`：

| 文件 | 内容 |
| --- | --- |
| current-sync.json | 47 个 TeX 包的本轮结构导入结果 |
| current-validate.json | 固定 release 的校验结果 |
| current-timings.json | sync 和 validate 的退出码与耗时 |
| reproduce/results.json | 376 项测试及端到端复现汇总 |
| pandoc-default/results.json | 普通 LaTeX reader 逐入口结果 |
| pandoc/results.json | 显式 raw_tex 模式逐入口结果 |
| latexpand-results.json | 展开与后续解析结果 |
| bib-probes.json | 38 个 BIB 文件的探测结果 |
| entrypoint-probes.json | 指定部分入口后的现有 parser 诊断 |
| source-integrity-check.json | 48 个包和 1,664 个文件的完整性核对 |
| ASSESSMENT.md | 本轮最初整理的英文临时评估 |

临时目录可能被系统清理。本文件已保留关键版本、哈希、数字、命令和失败案例；正式实施时应将可复现评测工具和适用证据纳入受管理的评测流程。

## 11. 未完成的验证与后续限制

以下项目未执行或未验收：

| 项目 | 状态 |
| --- | --- |
| 新离线归一化流程实现 | 尚未实施 |
| 完整正文、附录、公式与引用的独立人工核对 | 未验收 |
| 全部图片与支持文件的可用性 | 未验收 |
| 原始与规范化工程的 TeX/PDF 编译对照 | 未执行 |
| LaTeXML 转换及基准 | 未安装、未执行 |
| Docker | 未执行 |
| Lean | 未执行 |
| 真实模型语义抽取 | 未执行 |
| QEC-database machine 副本上的下游检索评测 | 本轮未执行，实施后按适用范围执行 |
| 实际 chapterbib、includeonly、ZIP 与确认的 LuaLaTeX 真实包覆盖 | 现有材料未建立完整覆盖 |

本轮没有代码改造，所以没有“改造前后完整率提升”的数据。已有工具间的比较只能用于选择实施方向，不能代替新流程上线前的内容与科学验收。

## 12. 外部依据

以下文档已在本轮评估中核对；只引用能力边界，不沿用其性能宣传作为本项目承诺。

| 来源 | 支持的判断 |
| --- | --- |
| [Pandoc User’s Guide](https://pandoc.org/MANUAL.html) | 通过中间表示转换，复杂格式之间可能有损；可保留原始 TeX |
| [CTAN latexpand](https://ctan.org/pkg/latexpand) | 展开 input/include，明确不处理 includeonly |
| [arXiv 00README 规范](https://info.arxiv.org/help/00README.html) | 顶层入口、编译信息和文档顺序可作为确定性识别依据 |
| [LaTeXML 转换文档](https://math.nist.gov/~BMiller/LaTeXML/manual/usage/conversion/) | 支持宏处理，但依赖包对应的 binding，不保证所有样式自动适配 |
