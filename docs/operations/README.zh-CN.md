# 运维与维护

> **状态：当前（0.6.x）。** 日常工作区用法在[用户指南](../user/README.zh-CN.md)。
> 本节覆盖受支持的 store/corpus 接口、审核和证据。

> **中文** · [English](README.md)

> [!IMPORTANT]
> 这些页面假设你已经有代码 checkout 和可用的 Python 环境。它们不替代
> 工作区说明中的日常操作。

## 本页目录

- [运维地图](#运维地图)
- [验证](#验证)
- [基准](#基准)

## 运维地图

| 页面 | 接口 | 类型 | 适用场景 |
|---|---|---|---|
| [store 与 corpus 维护](maintenance.zh-CN.md) | store/corpus | How-to | 导入、验证或恢复单篇 store/corpus |
| [工作区说明](../user/workspace.zh-CN.md) | 工作区 | How-to | 当前日常流程（方便链接） |
| [进阶用法](../user/advanced-usage.zh-CN.md) | 工作区/CLI | How-to / reference | 发布检查、退出码和命令分组 |


## 验证

验证报告是其所记录输入、命令和提交的证据。把报告用于更新的构建前，
先检查报告的作用范围。

- [验证索引](../../validation/README.zh-CN.md)
- [固定 arXiv 样例说明](../../tests/golden/README.md)

## 基准

运行 `python tools/bench.py --out build/benchmark.json` 生成增量负载。
传 `--archive-dir` 可测量六个固定 arXiv 输入。报告记录原始样本、中位数、
运行时版本和查询设置；“fresh”表示在普通 OS 缓存下的新应用 store。
生成的 benchmark 报告记录该次运行的实测基线。
