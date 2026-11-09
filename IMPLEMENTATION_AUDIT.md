# RFC-QEC-002 实施审计

基线：`main` / `origin/main`，`0fd1b23`，审计时工作树无未提交改动。
[附件原始规范](docs/rfc-002/QEC_GRAPH_DESIGN_UPDATE.md)按附件校验清单逐字节核对后保存。
附件中的验证报告是设计包自检；以下是当前仓库基线，后续成果见 [实施进度](docs/rfc-002/IMPLEMENTATION.md)。

| 阶段 | 已有实现（0.3.0） | RFC 差距 |
|---|---|---|
| U0 | `START_HERE.md`、原 P0–P5 实施及验收记录 | 本审计建立 U0–U6 新基线，不重置旧阶段 |
| U1 | `records.py` / `validators/schemas/record.v3.schema.json`；版本、资产、审核、构造、经典种子、CSS 呈现、实验/指标和部分证据约束 | 缺可机器校验的字段证据、准确修订的性能条件、软件目录与使用绑定；距离方向已有但覆盖有限 |
| U2 | `qecgraph`、`qec-graph`、`qec-latex-split`、`qecgraph-mcp` 已声明；`ingest/register/watch/recover-store`；`store.py`/ `registry.py` 有单写者、不可变快照和归档源版本 | 缺工作区 init/sync/rebuild/status，压缩包识别、安全解包、收据、批处理与消费恢复 |
| U3 | `parser.py` 识别语法结构；`review/review-decide/apply` 有确切绑定；`check-css/check-experiment` 有有限验证 | 缺两遍领域归属、规则/LLM 提案、曲线点选与覆盖；不能以结构提取代替领域审核 |
| U4 | `search/show/context/deps/impact/codes`；`ai_tools.py`/ `mcp_server.py` 有真实 stdio、固定作用域和预算 | 缺工作区快照、来源读取、运行投影、性能/软件工具及 human 隔离负例 |
| U5 | 无 human 渲染入口 | 生成 Obsidian 页面、链接、独立更新与恢复均缺 |
| U6 | `migrate/migration-import` 有旧 Schema 导入；已有 `tools/reproduce_installed.py` 和历史 wheel 证据；Lean 构建、映射和审核已有实际验收 | 缺 RFC 升级验证、新包端到端、macOS/Linux 双平台和真实论文 golden 数据 |

保留 `source_work/source_version`、`family/construction/classical_seed/code_instance/presentation`、
`circuit/noise/decoder/experiment/metric` 和全部 Lean 映射。新对象须显式区分使用、数值点、
噪声实例和运行记录；复用 v3 的字段时采用独立契约版本，避免给旧记录强加新语义。
旧数值 d 无边界类型时保持未判定；没有证据的 idle=false 不作为筛选条件；
旧算法别名只作未决提及；深度计数和实验配置缺失不得凭空补齐。迁移不得就地重写记录，
应输出映射、拒绝项及无法继承的审核。

F5 基线：A01–A11 工作区行为缺失（旧 store 原子性及并发仅可复用）；
D02 已有受证据约束的下界筛选；D01/D03–D14 只有部分类型/校验基础；
M01/M02 部分实现于现有固定 store/corpus MCP；M03/M04、H01–H03 无专门实现；
P01/P02 旧命令和旧迁移有历史证据，RFC 新工作流未验收。

实测：在 macOS arm64、Python 3.15.2 执行
`.venv/bin/python tools/reproduce.py --out build/reproduce`，退出 0；87 项单元测试通过，
3 个 TeX 来源文件、26 个切割片段、样例三视图、JSON Schema 及有限 HGP 检查通过。
报告：`build/reproduce/results.json`。此轮基线没有重跑 Docker、Lean 构建、真实论文或外部软件包。
