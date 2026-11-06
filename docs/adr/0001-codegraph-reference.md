# ADR 0001 · 固定架构参考与独立实现

核对日期：2026-11-06。参考仓库：[colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)。
实际 checkout：`f72c9d2efb14454ff4f9fd7b8460abd82f19a287`（浅克隆，不作为本项目依赖）。
许可证：该提交根目录 `LICENSE`，MIT，Copyright (c) 2026 Colby Mchenry；
原文件 SHA-256：`e6d98f98c666bebe065ac2492a0a19232cc318d4d67bac3ca42ffb77bacc8809`。
本项目只参考架构，未复制实现代码，也不使用上游性能数据。

实际阅读的边界与本项目决定：

| 上游文件／符号 | 核对结果 | qec-graph 的实现决定 |
|---|---|---|
| `src/extraction/index.ts` / `ExtractionOrchestrator`, `hashContent`, 文件 bundle 写入流程 | 内容哈希确认变更；文件替换和入边恢复在同一事务；失败标记不能阻止重试 | 保留 parser/graph/store 分层；缓存不得发布失败结果；以完整不可变快照发布 |
| `src/extraction/extraction-version.ts` / `EXTRACTION_VERSION` | 提取语义版本与数据库 Schema 版本分离 | 保留工具源码指纹；缓存协议单独版本化 |
| `src/db/index.ts` / `configureConnection`，`src/db/schema.sql` | 外键、索引及 SQLite 投影；写争用与 WAL 生命周期独立处理 | 权威 JSON 和资产保持不变；本地锁串行化写者；不引入上游数据库格式 |
| `src/resolution/index.ts` / `parseModuleConfigSnapshot`, `moduleConfigSnapshot` | 配置参与解析失效，包含缺失配置状态 | include、宏、环境配置发生变化时保守重建，不能仅以 mtime 判断 |
| `src/graph/traversal.ts` / `GraphTraverser` | 有方向、有边种类和预算的遍历 | 精确保留引用、声明、候选和审核依赖区别；硬状态先过滤再遍历 |
| `src/context/index.ts` / `ContextBuilder` | 查询、扩展、源码块、输出格式有独立边界 | 所有传输复用 query 层；保留完整定理，预算不足时明确遗漏 |
| `src/sync/index.ts`, `src/sync/watch-policy.ts`, `src/sync/watcher.ts` / `FileWatcher` | 事件过滤、debounce、锁争用重试和退化状态 | 首版使用内容核对的 polling watch，调用同一 ingest；失败不推进已接受输入指纹 |

官方 [How It Works](https://colbymchenry.github.io/codegraph/core-concepts/how-it-works/)
也已读取。代码参考绑定以上提交；在线说明仅作导航，不作为固定版本证据。

程序符号替换为来源出现、规范 claim、实体修订与证据。代码调用与文献证明依赖不具有相同证据标准。
Python 主实现和 pylatexenc==2.10 保持；上游 TypeScript/Rust 及其依赖不引入本项目。

当前直接运行依赖 pylatexenc==2.10 的安装元数据声明 MIT（不内嵌其源码）；
开发验证依赖与本次准确版本保存在 requirements-lock.txt 和 validation/p0/install-report.json。
