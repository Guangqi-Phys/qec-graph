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

增量解析和 watch 在后续步骤补入本页。
