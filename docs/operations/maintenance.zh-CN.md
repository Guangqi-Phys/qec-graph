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
