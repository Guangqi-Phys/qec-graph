# 单写者发布、增量和 watch

## 发布策略与恢复

ingest/split 共用输出目录保护和 POSIX writer lock。不同进程不能同时写同一 store；
进程退出或崩溃由内核释放锁，不以残留 PID 文件判断仍有写者。CURRENT 通过 fsync 文件和原子替换发布。
来源项目标识另存管理文件，初次 strict partial 没有 CURRENT 时也不会让其他项目占用该 store。

旧默认不变：partial 产生完整性合格的快照、发布 CURRENT，CLI 退出 2。
显式 `--strict` 将 partial 放入 `staging/<snapshot_id>/`，不更新 CURRENT，仍退出 2。
完整结果正常发布；strict 只决定发布策略，不改变相同语义输入的 snapshot ID。

```bash
qecgraph ingest examples/paper/main.tex --project-id demo --out build/strict --strict
qecgraph validate-staged --store build/strict --snapshot <partial_snapshot_id>
qecgraph recover-store --store build/strict
qecgraph recover-store --store build/strict --remove-abandoned
```

恢复先验证已有 CURRENT；工具识别标记过的 `.building-*` 未完成目录和已完整验证的未发布目录。
只有显式 remove-abandoned 才清理这些工具对象；未知同名目录、用户文件和历史快照保留。
崩溃可能留下完整但尚未发布的快照；重新 ingest 可验证后复用。不会自动挑一个半成品更新 CURRENT。
这里验证的是本机进程崩溃与原子发布，不声称分布式锁或断电后的跨文件系统持久性协议。

## 逐文件 AST 缓存

```bash
qecgraph ingest examples/paper/main.tex --project-id demo --out build/incremental --incremental
qecgraph split examples/paper/main.tex --project-id demo --out build/split-incremental --incremental
```

缓存对象是 pylatexenc 的逐文件 AST，采用受限 JSON 编码、源文本哈希、解析上下文、
配置、处理器源码与 pylatexenc 版本绑定，不使用 pickle 或任意类加载。
损坏缓存重解析；无诊断的成功 AST 才可写入缓存。每次仍重新发现 include、解析资源，
重建语义块、引用、审核状态、图视图及 SQLite，故 AST 命中不会让旧审核复活。

普通叶文件修改只重解析变化的 AST；宏/环境声明、include 所在文件、源文件集合、
配置或处理器变化，以及上次未解析依赖时，保守回退全量解析。
此策略按包含结构声明的整份文件失效，允许多算，不猜测宏影响范围。
变更检测读取内容 SHA-256，不信任 mtime；资源哈希每次重算。
发布前再次核对实际读过的原文、资源、config、sidecar 和 catalog，编辑器再次保存会拒绝旧构建发布并要求重试。

`cache/incremental-state.json` 保存内容清单、处理器、配置、快照和实际 include/resource 依赖；
快照 manifest 继续绑定 sidecar/catalog 与完整工具指纹。
结果 incremental 字段报告 hit/miss、回退原因、变化输入和实际耗时，属于运行信息，
不进入语义图或快照身份。全量/增量对相同最终输入必须得到相同 snapshot、图、来源和查询结果。
这里只承诺正确复用，不承诺固定加速比例；实测见后续恢复/测量步骤。

watch 在下一步骤补入本页。
