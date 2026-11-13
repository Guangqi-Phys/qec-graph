# 工作区维护

> 状态：当前。

> [English](maintenance.md) · **中文**

在工作区目录运行以下命令，检查归档和发布状态，然后按需重建。

```sh
qec-graph doctor
qec-graph validate
qec-graph rebuild
```

重建会从已登记归档重新生成机器发布。原始材料保存在 `archive/`。研究工具固定读取一个机器发布。

替换已退役格式的发布时，先用 `qec-graph init` 准备空工作区。将原归档的
`archive/blobs/` 和 `archive/receipts/` 复制到新工作区，重新应用显式来源元数据及
编码设置，再运行 `qec-graph rebuild --no-human` 和 `qec-graph validate`。
更新 MCP 配置以固定新的发布。
