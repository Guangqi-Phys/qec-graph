# 0.3.0 验收与复现

从独立的 Git checkout 执行下列命令。使用本地 POSIX 文件系统、Python 3.11+ 与 SQLite FTS5。
Python 的精确依赖见 `requirements-lock.txt`。产物输出到新目录；历史报告保留其实际提交、环境和运行结果。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python tools/reproduce.py --out build/reproduce
.venv/bin/python tools/reproduce_incremental.py --out build/reproduce-incremental
.venv/bin/python tools/reproduce_mcp.py --out build/reproduce-mcp
```

第一条复现流程运行回归、切割与三视图、来源校验、查询、Schema 和有限 HGP 计算。
增量流程对比全量重建并演练备份、恢复和故意损坏检测。MCP 流程使用实际 stdio 子进程，
检查固定版本、作用域、预算、状态和 CLI/Python 结果一致性。

验证 wheel 中包含 Schema、命令入口和依赖，并在独立环境回放注册、迁移、审核与查询：

```bash
mkdir -p build
sed '/^-e /d' requirements-lock.txt > build/constraints.txt
.venv/bin/python -m pip wheel --wheel-dir build/wheelhouse --constraint build/constraints.txt .
python3 -m venv build/installed
build/installed/bin/python -m pip install --no-index --find-links build/wheelhouse --constraint build/constraints.txt qec-graph==0.3.0
.venv/bin/python tools/reproduce_installed.py --bin-dir build/installed/bin --out build/reproduce-installed
```

Lean 使用 [固定的 4.19.0 工具链](adr/0003-lean-boundary.md)。安装到环境或传入实际 Lake 二进制路径；
Python 安装不会安装 Lean。先构建并检查信任反例，再使用结果中 fixed 项的 report 路径回放映射：

```bash
.venv/bin/python tools/reproduce_lean_checks.py --out build/lean-checks --lake /path/to/toolchain/bin/lake
# <report.json> 为 build/lean-checks/results.json 中 fixed.report 相对于 build/lean-checks 的路径。
.venv/bin/python tools/reproduce_lean_mapping.py --report <report.json> --out build/lean-mapping
```

可在运行中核对的状态和回退方法见 [维护](06_MAINTENANCE.md) 和 [恢复演练](11_INCREMENTAL.md)。
Git 保存代码与证据报告；原始用户论文、已有 corpus 和受管理资产仍需独立备份。
Docker 模板未完成运行验证，仓库中的验收以随附示例为输入。Lean 只覆盖有限 Bool 向量边界，
保留单独的公理审计和待审核语义状态。
