# 本交付包实际验证报告

验证对象：`qec-graph 0.2.0` 的源码、切割入口、图谱原型和随附有限 QEC 示例。

执行日期：2026-11-06 UTC。详细机器可读结果见 `results.json`，单元/集成测试日志见 `unit-tests.log`，独立安装入口检查见 `install-report.json`。

## 实际环境

| 项目 | 实际值 |
|---|---|
| Python | 3.12.14 |
| SQLite | 3.53.1，FTS5 可用 |
| pylatexenc | 2.10 |
| jsonschema | 4.26.0 |
| 平台 | Linux x86_64 |

本包声明 Python 3.11+；此次实际测试覆盖上表环境，没有运行 Windows/macOS 或全部 Python 小版本矩阵。

## 完整复现

在已经可导入依赖的项目根目录执行：

```bash
python tools/reproduce.py --out build/reproduce
```

本次临时环境通过 PYTHONPATH 提供 pylatexenc，功能行为与正常安装的依赖一致。随后另在独立目标目录构建并安装 wheel，确认命令使用的是安装后的包。

| 检查 | 实际结果 |
|---|---|
| 原有 parser/graph 回归 + 新 splitter 集成测试 | 24 项通过 |
| LaTeX 示例切割 | 3 个源文件、26 个语义片段 |
| source-only 图 | 34 个节点、93 条边 |
| 加入显式 sidecar 的图 | 36 个节点、97 条边 |
| 导入已有 QEC catalog 并连接来源 | 44 个节点、110 条边 |
| HGP 检索 | 16 个命中 |
| 显式 proof 的定理上下文 | 20 个节点，包含完整 proof 来源块 |
| 码实例的 catalog 上下文 | 17 个节点，包含实例、校验呈现及距离 claim |
| 三份快照的来源/哈希/边端点/SQLite 检查 | 通过 |
| graph、annotations 和知识样例的 JSON Schema | 通过 |

示例的 `custom_macros_not_expanded` 为预期 warning；完整状态表示受支持语法已处理，不代表完整 TeX 引擎语义。

随包 `example_output/` 保存的是上述 sidecar 演示图的原始快照，其 ID 为：

```text
a264208b233dc89330505caa1effdb26c55d8e0bf8c8cd49fcef95550f6e8a78
```

原始运行报告中的绝对路径记录了当时环境；解压到其他位置后，使用 `example_output/CURRENT.json` 中的相对路径，或重新运行命令取得当前绝对路径。快照内的 source/node 路径可移植。

## 有意义的失败与边界案例

测试覆盖了：Unicode 与 CRLF 保真、源片段区间、嵌套公式标签归属、注释/verbatim 假标签、重复标签歧义、缺失/循环/越界 include、重复导入幂等、显式 proof 与候选绑定、引用与依赖分离、资源哈希变动使审核失效、失效 proof 依赖不得重新提升、最终 context 的状态过滤、DataGraph 关联展开。

新增 splitter 检查了：实际生成的分类文件、文件清单对应原文、复用现有查询、外部非空目录保护、symlink 快照目录保护、partial 时保存可用片段并退出 2、两个模块入口相同结果、自定义环境映射。测试不声称覆盖所有可能的 TeX 宏和编译条件。

## 独立安装验证

实际使用 `pip install --no-deps --no-build-isolation --target ... .` 构建并安装了 `qec_graph-0.2.0-py3-none-any.whl`，然后从源码目录之外运行安装后的：

1. `qec-latex-split` 切割示例。
2. `qecgraph split` 对相同输入重复切割。
3. `qec-graph show` 查询定理。
4. `qecgraph validate` 检查生成快照。

四条命令均退出 0；两种切割入口返回完全相同的 JSON，并与源码运行得到相同的 source-only snapshot ID。`install-report.json` 保存了包实际路径、版本和运行摘要。安装时复用了已有依赖，并未验证任意网络环境的依赖下载过程。

## 有限 QEC 示例

实际运行 `knowledge_starter/tools/qec_kb.py verify --json-schema`：10 条记录及矩阵/证据通过检查。重复码种子的普通 HGP 示例计算得到：

- `n = 13`，`rank_GF(2)(HX) = rank_GF(2)(HZ) = 6`，`k = 1`。
- `HX HZ^T = 0`，逻辑 X/Z 配对满足示例要求。
- 对每个距离扇区的 8192 个二元候选向量进行有限穷举，得到 `dX = dZ = 3`。
- 结果与随包归档证据一致；形式化状态仍为 `not_started`。

这验证的是本示例的 Python 计算及记录一致性，不是 Lean 证明、通用大规模距离算法或一般 HGP 参数定理。

## 没有执行或没有实现的项目

- 没有用户提供的真实论文工程，测试使用包内演示与失败案例。
- 未执行 LaTeX/PDF 编译、Docker 构建或跨平台兼容矩阵。
- 未 checkout、复制或复用外部 CodeGraph 源代码；已核对公开架构文档，固定 commit/许可证核对留在后续任务。
- 未实现并测试 MCP 服务、向量检索、多论文注册表、真正增量 watcher。
- 未运行 Lean、导出真实声明/证明依赖，或审计任何 Lean 定理。

未来阶段的验收见 `docs/08_ROADMAP_ACCEPTANCE.md`。本报告的通过范围不会自动扩展到那些阶段。
