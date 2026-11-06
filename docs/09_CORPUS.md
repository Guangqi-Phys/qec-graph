# Corpus：注册、身份与查询

原有单工程 store 和 CLI 保持兼容。Corpus 用独立目录维护多文档身份：

```bash
qecgraph ingest examples/paper/main.tex --project-id demo --out build/demo
qecgraph register --corpus build/corpus --store build/demo --work-id work:demo --source-version-id version:demo:1
```

`work_id`、`source_version_id` 必须由调用者明确指定。标题不是唯一键。
同一个 source version 不能重绑到变化后的输入；论文更新需注册新 version ID。
同一工作可保留多版本，每个版本固定项目 ID、输入哈希和 snapshot ID。

`CURRENT.json` 仅指向一个不可变 `states/<revision>.json`；状态内容采用原型
`ensure_ascii=False,sort_keys=True,separators=(',',':')` 的 JSON SHA-256。
`Registry.read(revision)` 可读取历史状态。写者锁和原子指针保证发布边界。
进程崩溃可能留下不可达的完整对象；原指针不会指向半成品。

导入时完整复制并验证现有提取快照到 `source_snapshots/<snapshot_id>/`。
原 store 或论文随后搬迁，不改变已归档的定位。这里保留的是实际提取的来源，
仍需另存未读取的原始工程文件。旧 catalog 外部资产由迁移器显式接入，注册不宣称已复制这些资产。

运行边界：本地 POSIX 文件系统（macOS/Linux），单写者、多快照读者；
不宣称支持分布式文件系统或 Windows 文件锁。
