# QEC Graph 快速开始

> **状态：当前（0.5.x）。** 从安装到首次查询的最短路径。

> [English](quickstart.md) · **中文**

> [!TIP]
> 需要完整配置、退出码或 MCP 细节时，转到 [进阶用法](advanced-usage.zh-CN.md)
> 或 [工作区说明](workspace.zh-CN.md)。

## On this page

- [最短路径](#最短路径)
- [接下来做什么](#接下来做什么)

## 最短路径

| 步骤 | 操作 | 期望结果 |
|---|---|---|
| 1 | 按 [安装说明](../../README.zh-CN.md#安装) 安装 | `qec-graph --version` 有输出 |
| 2 | 进入工作目录，创建 `inputs/` | 目录中能看到 `inputs/` |
| 3 | 放入 LaTeX 源包，运行 `qec-graph init` | 终端显示发布成功或部分批次 |
| 4 | 运行 `qec-graph sync` | 成功包写入 `archive/`，`inputs/` 副本清除 |
| 5 | 运行 `qec-graph status` / `validate` | 显示索引数量与完整性检查结果 |

```sh
mkdir -p inputs
# Put downloaded TeX source packages in inputs/
qec-graph init --workspace .
qec-graph sync
qec-graph status
qec-graph validate
```

## 接下来做什么

| 目标 | 命令 / 入口 |
|---|---|
| 搜索来源与记录 | `qec-graph query search HGP --workspace .` |
| 浏览人类视图 | 在 Obsidian 中打开 `human/`，从 `Index.md` 开始 |
| 接入只读 MCP | `qec-graph mcp config --workspace .` |
| 处理失败包 | `qec-graph inputs list`，再 `qec-graph inputs quarantine <name>` |

成功导入后，原始包留在 `archive/`；失败包保留在 `inputs/` 以便重试。把 `human/`
作为 Obsidian 仓库打开，从 `Index.md` 开始。**不要**把 `human/notes/` 当作检索输入。

[进阶用法](advanced-usage.zh-CN.md) · [数据与检索](data-and-search.zh-CN.md) · [工作区说明](workspace.zh-CN.md)
