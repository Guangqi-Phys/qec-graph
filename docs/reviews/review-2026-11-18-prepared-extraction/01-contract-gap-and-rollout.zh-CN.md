# 从准备材料到知识提取的交接评审

日期 2026-11-18。准备基线为 `9d90a98` 的 `compile-prepare-v20`，材料 schema
为 `qecgraph.prepare/3`。本轮冻结准备实现、材料与验收记录。新提取只接收这一版本。
需求以系统设计和人类需求文档为准。[DESIGN](../../design/DESIGN.zh-CN.md) ·
[Human.md](../../design/Human.md)

## 当前断点

| 位置 | 实际行为与不匹配 | 改进 |
| --- | --- | --- |
| 导入入口 | `Workspace._prepare` 给 `store.ingest` 传原始 TeX 路径，后者调用 `parse_project`。工作区的语法恢复和旧规范化也从原包启动。v20 语法、实际消费的文件和编译引用没有进入提取。 | 新提取的输入固定为通过 `read_material` 复核的材料目录。文件哈希、准备状态和规则版本随提取结果绑定。 |
| 文档结构 | 旧图以单一 source span 和 block kind 为入口。v20 的 `content.json` 是节点树，跨 `\input` 的节点可能含多段来源；`reading_units` 与表格单元格也可能只有 `entry.tex` 范围。 | 在统一结果中保留节点 ID、层级、顺序和完整范围。区分 entry、原文件和可逆字节投影坐标。刊载精确引句时落实到原文件。 |
| 规范化文本 | `normalized.tex` 可能替换数学定界符或插入编译书目。v20 的语法范围始终指向 `entry.tex`。 | 使用 entry 范围读取语法与字面内容。规范化映射随材料可查询。 |
| 标签与书目 | 旧图从标签和字面书目重新计算绑定。v20 已保留同名标签的全部候选、外部标签、书目作用域和最终日志。 | 直接沿用 v20 候选和作用域。准备状态 partial 时也保留可用结构及阻断原因。 |
| 可提取数据 | 旧规则可产生参数提及，旧模型路径从另一份编号原文推导定理、假设、数据和九问。两者没有共用 v20 的范围或覆盖信息。 | 程序提取字面对象、数字候选和出处。语义任务按需使用四个有版本的技能，输入固定到同一材料的活动证据范围，模型结果仍为 proposed。 |
| 发布与人类视图 | §15 的提议约定和 §2.2 写法不完全一致。当前工作区将某些提议装入 `ai_extracted` 记录以供查询，显式研究记录和人工验收另有流程。准备层 ready 只验收机械材料。 | 分开文档覆盖、模型提议状态和研究发布状态。人工审核、MCP 和九问视图继续消费已验证且带来源的机器记录。 |

真实材料确认了这些区别。`0903.0566v1` 有可直接读取的标题宏、公式、定理环境、表格单元格
和书目。`2111.05176v1` 的 entry 来自多个源文件，语法节点逾九万。
`2012.04068v1` 是 ready，仍带有多个交叉引用候选。`2303.15933v1` 的可用正文与 BBL
运行时失败同时存在。旧流程基线命令 `.venv/bin/python tools/reproduce.py --out build/prepared-extraction/baseline`
已通过。采用相同输入评估后续修改。[准备验收数据](../../../validation/preparation_acceptance.json)

## 提取边界

| 需求 | 程序产物 | 语义任务和接受边界 |
| --- | --- | --- |
| SourceGraph 与原文阅读 | 标题、作者等字面候选，章节和阅读单位，公式、环境、图注、表格布局、附件、标签和引用证据。任何文本片段可回到绑定的材料版本。 | 语义推理另行请求。跨文件或含投影片段的文本保留分段出处。 |
| LemmaGraph | 定义、定理、假设等有显式标记的原文环境，证明文字及原引用。 | 假设范围、量词、定理陈述、适用条件和依赖的解释用 `extract_theorems`、`extract_assumptions`。提议须引原文，语法环境与引用各自保持作者标记。 |
| DataGraph | 表格和单元格、公式与字面参数元组候选，检验矩阵或电路文件在原包的位置。 | `extract_data` 根据证据提议码、噪声、decoder、实验及指标。码身份、距离界、LER 的比较条件和缺失字段继续由现有研究约束判定。 |
| ThoughtsGraph 和九问 | 提供章节、段落与原文定位。 | `extract_thoughts` 按既有问题和提议 schema 提取。证据不足保留未回答和原因。生成的人类视图读取固定机器发布。 |

统一的离线交付采用一个 JSON 文件，权威 schema 放在 `qecgraph/validators/schemas/`。
输入绑定保留 package、source tree、entry 和材料 manifest 的哈希。结构项提供语法节点
或阅读范围、TeX 文字与来源选择器。书目和引用沿用已验证的 v20 字段。字面参数作为
提及候选。每项语义任务记录运行状态、提交给模型的证据范围和经过验证的提议。
语义提议继续使用四个技能已有的响应格式和校验器。旧准备格式无需迁移。

## 分步修改与验收

1. **确立交付和读取。** 新增一份版本化提取 schema 和独立入口。固定材料 manifest 哈希，
   调用 `read_material` 验证，再检查 v20 的范围与坐标。旧版、损坏的材料或无法确定来源
   的引用给出明确状态。输出发布在材料目录外，失败保留之前已发布的提取文件。
2. **实现程序提取。** 以 entry 语法和映射生成上述字面项目，直接保留书目及候选，重用现有
   参数记法检测。选择器引用 entry 的 Unicode 半开区间及实际原始片段。可定位的 partial
   内容也可提取，覆盖与失败原因随结果交付。验证单文件、多文件、字节投影、歧义和空正文。
3. **接上语义提取。** 显式选择技能，沿用既有上传许可、客户端、输入预算、JSON Schema 和
   原文校验。程序从活动阅读范围生成编号证据，指明原文可引用区间。复用四个版本化
   技能，把其提议及引用附在同一 v20 材料版本下。无可用证据、预算不足和响应失败分别
   报告。离线 fake provider 覆盖授权、成功、伪造引用和预算边界。
4. **核对消费与移交。** 回放固定 v20 语料，检查各类结构、准备状态、来源完整性和零模型
   的机械路径。更新双语设计和使用入口，给工作区接入指定单一权威字段和验收顺序。
   发布器接入需先证明跨文件引用可精确回源、提议不晋级、失败保留原 release，再依次
   切换检索和渲染。独立科学判断按 §16.8 验收。

本次交付覆盖从已准备材料到可检验的离线提取和可选语义提议。工作区、查询、MCP 与九问
渲染的现有接口继续运作。切换机器发布输入是下一条边界，需要其读写侧语义及固定 release
验证。本次使用 v20 材料回放和固定 machine 副本评测记录这一边界的状态。

## 实施与验证

| 提交 | 交付 |
| --- | --- |
| `8b097d0` | `qecgraph.prepared_extraction/1` 的 JSON Schema。 |
| `bd5d7f1` | 实现 `tools/extract_prepared.py`、v20 输入绑定、原文字节定位和来源单元。字面图注在需要时从已准备的 macro 位置读取有界的平衡参数。 |
| `26f2ae3` | 接上四个既有语义技能。活动证据按 entry 行号编号，语义提议引用可映回原文件。显式选择和上传许可均通过后才发请求。 |
| `ae89da1` | 参数提及携带字面数值或符号以及括号形式。 |
| `293a439` | 离线复核只收集技能 schema 中用于引证的字段。 |

使用 `build/preparation-followup/final` 与同次留出回放的现存材料。每个输入的 manifest 哈希
都与 v20 回放记录相同。逐个比对所有提取单元和 entry 片段，并将片段映回已校验的原文件
或投影范围。原准备状态、书目和交叉引用候选随结果复制。

| 输入与证据 | 固定语料 | 留出语料 |
| --- | ---: | ---: |
| 可信材料交付数 | 47 | 6 |
| 材料状态 ready / partial | 44 / 3 | 4 / 2 |
| 有可用结构 | 46 | 4 |
| 无材料的输入 | 1 | 2 |
| 经逐项复核的来源单元 | 82,675 | 4,006 |
| 经逐项复核的来源片段 | 82,849 | 4,006 |
| 含字节投影的单元 | 1,258 | 0 |
| 真实模型调用 | 0 | 0 |

固定语料的来源单元包括 1,430 个标题节点、40,034 个公式、228 个显式陈述环境、
335 个表格结构、637 个图注和 416 个参数提及。两篇书目运行失败的 partial 能产出正文
单元。编译失败的 partial 交付原文件清单、阶段状态和诊断。

测试覆盖跨文件范围、引用歧义、仅接收 v20、参数字面值、无权限和预算超限。假模型
测试验证限节提取、活动原文映射、伪造引用拒绝和离线复验，协议沿用原技能版本。
启用本地 TeX 的全量测试通过 639 项。Ruff、mypy、复杂度检查和双语文档测试通过，
Pyright 为 0 errors 和 83 条既有警告。

原有工作区端到端复现通过。前后均得到 36 个节点、99 条边、11 条搜索命中和 16 个
上下文节点。合成知识评测执行 15 次查询，工具和基准错误均为 0。
固定真实 machine 副本在同一 release 上仍报
`Registry state schema mismatch`，退出 1，固定 state 哈希核对相同。
机器发布接入及 §16.8 的独立科学验收仍待完成，当前验收可确认统一文件和证据定位。

```sh
.venv/bin/python tools/extract_prepared.py build/preparation-followup/final/0903.0566v1 \
  --out build/prepared-extraction/fixed/0903.0566v1.json --check
QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/reproduce.py --out build/prepared-extraction/reproduce
.venv/bin/python tools/reproduce_knowledge.py --out build/prepared-extraction/synthetic-knowledge.json
.venv/bin/python tools/reproduce_knowledge.py --machine build/preparation-v10/machine-copy \
  --release aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22 \
  --out build/prepared-extraction/machine.json
```
