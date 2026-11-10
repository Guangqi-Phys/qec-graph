# 本仓库验证记录

本页记录历史运行。当前实测和完整原始证据的恢复方式见[验证索引](README.md)。

RFC-QEC-002 / 0.4.0rc1 的独立报告见 [候选版验收](workspace-0.4.0rc1/report.md)；
下方保留 0.3.0 的历史记录。


0.3.0 的复现步骤保留在 Git 历史；当前文档入口见 [文档索引](../docs/README.md)。

交接复核修正了距离论断证据绑定、实验未知配置的可比性、Lean 提议与有效审核状态区分。修正后的 Python、增量、MCP、Lean 构建和映射复验均已通过。[交接复核](release-0.3.0/recheck.json)

在独立 checkout 中复验了固定提交 `34ce4f24d7dc0f95fdd2e40188c37e862f0c5b44`。Python 回归、独立安装、Lean 构建、信任检查和图谱映射均通过。复验记录包含命令、产物哈希以及安装依赖的许可证核对。[固定提交复验](release-0.3.0/fixed/replay.json)

| 验收 | 实际结果与证据 |
|---|---|
| Python、TeX 和 QEC 示例 | [87 项回归及全流程报告](release-0.3.0/python/results.json)：3 源文件、26 原文片段；sidecar 图 36 节点、97 边；Schema 和 HGP 有限穷举通过 |
| 独立 wheel 安装 | [19 条命令](release-0.3.0/installed/results.json)通过，安装包内 5 份 Schema；注册、10 条旧记录迁移、机器决定后仍待审和幂等 apply 通过 |
| 增量和恢复 | [全量等价、严格 partial、备份恢复与损坏检测](release-0.3.0/incremental/results.json)通过；仅为本机生成负载 |
| MCP | [22 项实际 stdio 客户端断言](release-0.3.0/mcp/results.json)通过，另存 transcript |
| Lean P5 | [实际导入和映射](lean-experimental/mapping-replay/mapping-replay.json)、[10 个真实构建及失效场景](lean-experimental/trust-checks/results.json)通过；固定版本 4.19.0，实际允许 propext；语义待审 |

Docker daemon 在验收环境不可用，未构建容器。未测试外部桌面客户端或用户私有论文。
Python HGP `[[13,1,3]]` 距离是有限计算结果；Lean 结果覆盖独立的有限 Bool 向量例。

以下为阶段历史，继续保留各次运行的实际范围。

P0 基线命令：`.venv/bin/python tools/reproduce.py --out build/reproduce`，退出码 0。

本次运行结果位于 `p0/results.json`；24 项测试日志和安装报告一并保存。
3 个源文件、26 个片段；sidecar 图 36 节点、97 边。
完整 JSON Schema 检查和有限 HGP [[13,1,3]] 穷举通过。
运行环境为本机 Python 3.15.2，准确 SQLite/依赖版本记录在结果和安装报告中。
历史 Python 环境锁定见 Git 历史（本项目当前使用 `pip install -e .` 与 `pyproject.toml` 依赖组）。

`handoff/` 是历史交付证据。后续阶段须增加自己的测试及报告。
本次 P0 未运行 Docker、Lean、真实用户论文或 MCP 客户端。

P1：35 项全量回归通过，日志和实际 10 条记录的迁移/import 报告见 p1/。

P2：完整复现 `.venv/bin/python tools/reproduce.py --out build/reproduce-p2` 退出 0，58 项回归、原型流程及有限 HGP 计算通过。准确环境、输入、命令及结果见 p2/results.json；审核提案、AI 决定、幂等应用及 CSS 检查均独立保存在 p2/。未运行 Docker 或 Lean。

P3：71 项回归与完整 reproduce-p3 通过；13 源文件、96 lemma 的实际增量/恢复演练及 watch --once 证据见 p3/。全量与增量语义一致；测量仅为本机生成工作负载。

P4：81 项回归、原型完整复现及真实 MCP stdio 客户端 22 项端到端断言通过。CLI/Python/MCP envelope 一致，版本固定、预算和状态策略可验证。报告及完整协议记录见 p4/；没有改写外部客户端设置或部署服务。

P5：官方 Lean 4.19.0 实际编译、导出类型/实际依赖和公理；6 个完整声明、361 个仅引用名称在导入中区分保存。已执行 87 项 Python 回归及独立 Lean 反例。保留了零公理策略拒绝、固定提交构建、同名异型拒绝等证据，见 p5/。
