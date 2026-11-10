# 运维与维护

> **状态：当前。** 日常工作区用法在[用户指南](../user/README.zh-CN.md)。
> 本节覆盖受支持的旧 store/corpus 接口、审核和证据。

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
| [旧 store 与 corpus 维护](maintenance.zh-CN.md) | 旧 store/corpus | How-to | 导入、验证或恢复单篇 store/corpus |
| [Corpus](corpus.zh-CN.md) | corpus | Reference | 注册 work/version、映射来源、执行固定版本查询 |
| [审核](review.zh-CN.md) | corpus | How-to / reference | 验证类型化记录、绑定证据、应用已审核提案 |
| [工作区说明](../user/workspace.zh-CN.md) | 工作区 | How-to | 当前日常流程（方便链接） |
| [进阶用法](../user/advanced-usage.zh-CN.md) | 工作区/CLI | How-to / reference | 发布检查、退出码和命令分组 |

## 验证

验证报告是其所记录输入、命令和提交的证据。把报告用于更新的构建前，
先检查报告的作用范围。

- [验证索引](../../validation/README.zh-CN.md)
- [工作区验收报告](../../validation/workspace-0.4.0rc1/report.md)
- [固定 arXiv 样例说明](../../tests/golden/README.md)

## 基准

运行 `python tools/bench.py --out build/benchmark.json` 生成增量负载。
传 `--archive-dir` 可测量六个固定 arXiv 输入。报告记录原始样本、中位数、
运行时版本和查询设置；“fresh”表示在普通 OS 缓存下的新应用 store。
参见[实测基线](../../validation/audit/0.4.0rc1/benchmark.json)。
