# QEC 知识库起步模板

这是一份面向 AI 查询、QEC 数学数据与 Lean 规划的最小运行示范。推荐的长期架构是：**Git 中的结构化记录和数学源码 + 独立持久资产 + 可重建的查询索引 + 单独维护的 Lean 项目**。

这里提供 10 个关联记录、2 个 JSON Schema、6 个二元矩阵文件、计算证据、4 份待填模板和一个 Python CLI。示例是由两个长度为 3 的重复码生成的普通 HGP 码 `[[13,1,3]]`。它的对易性、GF(2) 秩、逻辑配对和 X/Z 距离经过有限枚举检查；形式化状态明确为 `not_started`。

## 1. 先运行一个完整的数据闭环

要求 Python 3.11+，并带有 SQLite FTS5。除完整 JSON Schema 校验外，命令仅使用 Python 标准库。在解压后的本目录运行：

```bash
python tools/qec_kb.py verify
python tools/qec_kb.py index
python tools/qec_kb.py search HGP
python tools/qec_kb.py codes --n-max 20 --distance-at-least 3
python tools/qec_kb.py context claim:rep3-hgp:distance --depth 2
```

完整 Schema 校验另需 `jsonschema`。本模板使用 `jsonschema 4.26.0` 检查过，可在隔离环境中安装后运行：

```bash
python tools/qec_kb.py verify --json-schema
```

`verify` 检查记录 ID、引用、显式证明依赖的无环性、文件校验和以及具体示例的数学条件。它对每个 X/Z 扇区枚举 8192 个二元向量，排除稳定子行空间，得到距离 3。该枚举器限制 `n <= 20`，用于检查小例子。它没有实现适合大码的距离求解器。

`index` 从记录生成 `derived/index.sqlite`。查询时会检查输入指纹；数据或检查器变化后，旧索引会被拒绝，须重新构建。FTS 示例预置了少量分词后的中英检索词，完整中文分词和语义搜索应按实际资料另行实现。

## 2. 各目录的职责

| 目录/文件 | 内容 | 权威性 |
|---|---|---|
| `records/` | 来源、定义、码族、构造、实例、表示、论断、证据、形式化映射 | 人工或程序审核后维护的事实记录；Git 跟踪 |
| `schemas/` | 格式和类型约束 | Git 跟踪；修改语义需要迁移 |
| `assets/matrices/` | 本例种子、HX/HZ、逻辑代表 | 本例小文件随仓库保存；大资产另存持久目录 |
| `evidence/` | 对准确输入执行检查所得的报告 | 保留方法、输入和工具哈希；不是 Lean 证明 |
| `templates/` | 论文、定理、实验、SEC 的待填 YAML 草稿 | 不属于有效记录；填完后转换或纳入验证流程 |
| `tools/` | 验证、索引、检索和证据包导出示例 | Git 跟踪；示例投影专用于当前一个 HGP 实例 |
| `derived/` | SQLite 等缓存 | 可重建，不作为独有事实来源 |
| `docs/` | 领域、形式化、运维和实施建议 | 维护规范 |
| `AGENTS.md` | 给 AI 的编辑和查询约定 | 随项目一同演进 |

源码不依赖 pickle 或任意 Python 对象序列化。矩阵采用显式 `GF(2)`、形状、零基索引和坐标列表。`sha256` 表示文件字节；`canonical_sha256` 使用排序键、紧凑 JSON 和固定矩阵序列化规则，表示这一带标签矩阵。二者都不表示量子码等价类。

主动记录 JSON 是本模板的唯一可编辑真本。YAML 仅作为便于人填写的模板；实际项目可改用 YAML 真本，但应只选一种编辑入口，并对解析结果执行同一份 Schema。避免让 Markdown、YAML 和 SQL 同时成为同一参数的独立真本。

## 3. 建模原则

论文、某个论文版本、定理、码族、码实例、校验矩阵表示、SEC、噪声、decoder 和实验运行分别具有稳定 ID。引用通过 ID 连接，修订用 Git 提交或明确的不可变 revision 绑定，原文件以哈希定位。

例如，换一组稳定子生成元可能保持码空间不变，却改变 check weight、Tanner 图和 syndrome extraction circuit。应增加 presentation 记录并连接到原码实例，不能把这些实验相关差异消掉。

距离使用定义 ID、上下界和证据。看到一个重量为 12 的逻辑算符只得到 `upper_bound: 12`；启发式搜索没有找到更轻的算符，不能自动写 `lower_bound: 12`。`review_status` 与 `verification_level` 分开，Python 检查不能自动晋级为 Lean 证明。

原始论文文件按版本保留；自动抽取先作为草稿。人工修正过的公式和假设需要单独保存，避免以后重新解析时覆盖。重要论断同时保留原始陈述、标准化陈述和符号映射。

## 4. 下一步实施顺序

1. 选取正在研究的 5–10 篇论文，先登记版本和原始文件，不要求抽取所有句子。
2. 为每篇挑选 1–3 个会在研究中再次使用的定理、构造或实验结果，补齐位置、假设、定义和证据。
3. 用真实的 HGP/BB 实例替换本例或增加记录，扩展逐种构造验证器及参数查询投影；避免把 demo 的枚举器用于大码。
4. 建立稳定的参数查询、来源定位、依赖展开接口；准备 10–20 个真实问题检查召回与引用质量。
5. 评估兼容的现有 Lean 定义，固定工具链和 mathlib 提交，再实现第一条一般性的 CSS/HGP 引理。
6. 根据实际检索失败增加向量搜索；根据并发写入和服务需求迁移数据库。每次升级保持原始记录可导出。

没有必要在第一阶段同时部署向量数据库、图数据库和多项后台服务。`docs/OPERATIONS.md` 说明了 SQLite、PostgreSQL、持久资产和按需 Docker 构建环境的取舍。

## 5. Lean 与现有项目

本模板没有运行 Lean，也没有提供已完成的 Lean 证明。`formalization:rep3-hgp:distance` 仅登记一个计划；其实际声明、工具链、构建结果和公理依赖均为空。后续项目应分别审核形式化陈述是否符合原意、证明是否构建、传递公理依赖是否符合项目策略。

可参考 [Lean-QECert](https://github.com/QudeLeap/Lean-QECert) 的 `MAIN_RESULTS.json`，用精确声明名、模块、源码和文献引用辅助 AI 定位；实际复用前仍需固定提交并审查完整类型与假设。详细路线见 `docs/LEAN_ROADMAP.md`。

## 6. 阅读顺序与适用边界

先读 `docs/ARCHITECTURE.md`，再按需阅读 `QEC_DATA_MODEL.md`、`LEAN_ROADMAP.md` 和 `OPERATIONS.md`。所有模板中的 `REPLACE_ME` 必须以真实资料替换；缺失信息保持 `null` 并注明原因。

本包未实现 PDF 批量解析、embedding、远程 API、部署或通用 Lean 导出。它演示的是可维护的数据边界、可核对的有限计算与可重建索引，供后续工程实现扩展。

文献来源是明确标为 `reference_only` 的书目指针；包内没有下载或复制原论文全文。数学例子的数值结果来自本包记录的有限枚举。
