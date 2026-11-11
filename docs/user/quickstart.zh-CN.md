# QEC Graph 快速开始

> **状态：当前（0.6.x）。** 从安装到首次查询的最短路径。

> [English](quickstart.md) · **中文**

> [!TIP]
> 需要完整配置、退出码或 MCP 细节时，转到 [进阶用法](advanced-usage.zh-CN.md)
> 或 [工作区说明](workspace.zh-CN.md)。

## 本页目录

- [最短路径](#最短路径)
- [接下来做什么](#接下来做什么)

## 最短路径

| 步骤 | 操作 | 期望结果 |
|---|---|---|
| 1 | 按 [安装说明](../../README.zh-CN.md#安装) 安装 | `qec-graph --version` 有输出 |
| 2 | 进入空目录，运行 `qec-graph init` | 创建 `inputs/` 和 `qecgraph.toml`，不抽取内容 |
| 3 | 可选：配置 `qecgraph.toml` 的 `[ai]`，运行 `qec-graph ai test` | provider 返回成功的 schema 探针 |
| 4 | 放入 LaTeX 源包，运行 `qec-graph sync` | 成功包写入 `archive/`，`inputs/` 副本清除 |
| 5 | 运行 `qec-graph status` / `validate` | 显示索引数量与完整性检查结果 |

```sh
mkdir my-qec
cd my-qec
qec-graph init
# Optional: configure [ai] in qecgraph.toml before syncing.
qec-graph ai status
qec-graph ai test
# Add downloaded TeX source packages to inputs/, then:
qec-graph sync
qec-graph status
qec-graph validate
```

## 接下来做什么

| 目标 | 命令 / 入口 |
|---|---|
| 搜索来源与记录 | `qec-graph query search HGP --workspace .` |
| 浏览人类视图 | 在 Obsidian 中打开 `human/`，浏览 `YYYY/MM/*_thoughts.md` |
| 接入只读 MCP | `qec-graph mcp config --workspace .` |
| 处理失败包 | `qec-graph inputs list`，再 `qec-graph inputs quarantine <name>` |

成功导入后，原始包留在 `archive/`；失败包保留在 `inputs/` 以便重试。把 `human/`
作为 Obsidian 仓库打开，按年月阅读每篇论文的一份 thoughts 问答。人类笔记不作为检索
输入。此布局已随 v0.6.3 发布，迁移会直接删除旧受管理 human 内容、不做备份；
详见[布局说明](workspace.zh-CN.md#obsidian-和机器访问隔离)。

[进阶用法](advanced-usage.zh-CN.md) · [数据与检索](data-and-search.zh-CN.md) · [工作区说明](workspace.zh-CN.md)
