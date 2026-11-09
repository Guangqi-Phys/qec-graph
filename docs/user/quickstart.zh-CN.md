# QEC Graph 快速开始

QEC Graph 把 LaTeX 论文导入本地量子纠错数据库。记录可以追溯到论文原文，并能在 Obsidian 或只读 MCP 中查询。

按 [安装说明](../../README.md#install) 安装。再次运行同一条命令可更新。进入你想用作数据库的目录，把 LaTeX 源码包放进 `inputs/`：

```sh
mkdir -p inputs
qec-graph init --workspace .
qec-graph sync
qec-graph status
qec-graph validate
```

成功导入后，原始包留在 `archive/`，`inputs/` 中的副本会清除。失败的包保留供重试。把 `human/` 作为 Obsidian 仓库打开，从 `Index.md` 开始。

查找文献和记录：`qec-graph search HGP --workspace .`。接入 Codex 请参照 [MCP 说明](../../README.md#mcp)，或运行 `qec-graph mcp config --workspace .` 打印其他客户端所需的配置。

[进阶用法](../ADVANCED_USAGE.md) · [数据与检索](../DATA_AND_SEARCH.md)
