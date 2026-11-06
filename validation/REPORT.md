# 本仓库验证记录

P0 基线命令：`.venv/bin/python tools/reproduce.py --out build/reproduce`，退出码 0。

本次运行结果位于 `p0/results.json`；24 项测试日志和安装报告一并保存。
3 个源文件、26 个片段；sidecar 图 36 节点、97 边。
完整 JSON Schema 检查和有限 HGP [[13,1,3]] 穷举通过。
运行环境为本机 Python 3.15.2，准确 SQLite/依赖版本记录在结果和安装报告中。
`requirements-lock.txt` 保存本次 Python 环境（本项目 editable 安装使用 `pip install -e .`）。

`handoff/` 是历史交付证据。后续阶段须增加自己的测试及报告。
本次 P0 未运行 Docker、Lean、真实用户论文或 MCP 客户端。

P1：35 项全量回归通过，日志和实际 10 条记录的迁移/import 报告见 p1/。
