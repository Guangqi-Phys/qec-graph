# Corpus：注册、身份与查询

> **状态：当前，适用于旧 corpus 接口。** The workspace surface is the primary product; see the [workspace guide](../user/workspace.zh-CN.md).

> [English](corpus.md) · **中文**

> [!NOTE]
> This is the legacy multi-document corpus surface. The workspace has its own
> machine release format; do not point both at the same directory.

## On this page

- [规范记录与来源映射](#规范记录与来源映射)
- [固定版本查询](#固定版本查询)
- [显式迁移和资产](#显式迁移和资产)

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

## 规范记录与来源映射

```bash
qecgraph record-add examples/claim.example.json --corpus build/corpus
qecgraph claim-link examples/claim-link.example.json --corpus build/corpus
```

P1 引入 `qecgraph.record.v2`；P2 新写入使用严格的 `qecgraph.record.v3`，迁移见 [10](review.zh-CN.md)。
`id` 和 `revision` 由作者指定；内容哈希及协议由程序补齐。
同一 ID/revision 不能覆盖不同内容；新修订保留旧文件。不同 ID 即使标题和参数相同也独立保存。
自动输入默认 `review.status=proposed`；导入或语法解析不构成人工审核。

`normalizes_to` 是新增的 registry 关系，表示来源块与独立 claim 的显式映射，
每个映射绑定 source version、snapshot、准确节点和双方哈希、claim revision、假设和记号作用域。
可多对多映射；它不把来源 lemma 改为 claim，也不宣称两种陈述等价。原 graph.v1 关系含义不变。
未知 Schema 被拒绝，必须先走显式迁移；新记录不重解释旧格式。

## 固定版本查询

```bash
qecgraph search HGP --corpus build/corpus --limit 10
qecgraph show 'version:demo:1::thm:hgp-length' --corpus build/corpus
qecgraph context claim:demo:hgp-length --corpus build/corpus --include-candidates
qecgraph show thm:hgp-length --corpus build/corpus --source-version-id version:demo:1
```

跨文档 label/原始节点 ID 使用 `source_version_id::selector`；返回的 occurrence ID
包含来源版本命名空间，可直接复用。不同版本即使原节点 ID 相同，也保留独立来源出现。
实体 ID 不加来源命名空间。未请求候选时不将 proposed 的来源映射作为确认关系加入上下文。
claim 修订后，旧映射保留且为 stale，候选开关不能使其复活。

每个 corpus 查询先固定一次 registry revision，再构建只读投影并调用共享 query 层。
返回 scope 列出来源版本、精确 snapshot 和实体修订。用 `--registry-revision <返回值>` 重放历史查询；
原 store 查询增加 `--snapshot <snapshot_id>`，不跟随后续 CURRENT。
Python 使用 `corpus.execute(...)`、`Registry.read(revision)` 或 `store.pin_snapshot(...)`。

Corpus 搜索当前采用确定性的大小写无关子串匹配，并报告 limit 截断；原单 store 保留 SQLite/FTS5。
空结果只表示固定作用域内未命中。查询不会写记录、运行来源代码或提升数学证据。

## 显式迁移和资产

```bash
qecgraph migrate legacy/knowledge_starter/records --source-root legacy/knowledge_starter --out build/migration
qecgraph migration-import build/migration --corpus build/corpus
qecgraph context code:rep3-hgp:13 --corpus build/corpus
```

迁移输出必须是独立的新目录。`migration-report.json` 记录输入字节哈希、Schema、
ID/修订映射、接受及拒绝项；原始字节保存到 `originals/`，未知版本只保留为不透明输入并拒绝解释。
任一拒绝项使迁移返回退出码 2，import 拒绝有未解决拒绝项的批次。

旧 `0.1.0` 记录进入当前版本独立信封；保留原 ID、原记录全部字段、原证据类别和未执行状态。
旧 refs 采用 `catalog:` 前缀，避免隐式提升为审核依赖。旧 claim 未说明量词时为 null 并注明原因。
`qecgraph.graph.v1` 与 `qecgraph.annotations.v1` 采用逐字节 passthrough 适配，
保持来源块和审核绑定原义，不将原文 theorem 转为 claim；完整 store 的跨文档接入使用 register。

旧记录的相对资产路径必须明确提供 `--source-root`，不能相对于新 store 猜测。
迁移校验旧字节哈希及旧 ensure_ascii=True canonical 哈希，保留旧协议标识，
将资产复制为 `qecasset:sha256:<digest>`。记录中的实际路径替换为受管理 URI，原字段仍在 legacy_record 中。
import 复制完整资产后原子发布 registry 状态；搬迁 corpus 不影响 URI 解析。
`Registry.asset_bytes(uri)` 核对准确字节，损坏或缺失会报错。迁移不会运行任何导入脚本。
旧原件和迁移报告一并备份；回滚读取旧 registry revision，不删除新对象。
