# 仓库工具

> **中文** · [English](README.md)

辅助脚本从仓库根目录运行。它们是开发/发布工具，不属于安装后的 `qecgraph` 包。

| 分组 | 脚本 | 用途 |
|---|---|---|
| 复现 | `reproduce.py`、`reproduce_workspace.py`、`reproduce_mcp.py`、`reproduce_golden.py`、`reproduce_incremental.py`、`reproduce_installed.py` | 核心、workspace、MCP、固定来源、增量和安装包的端到端回归 |
| 隔离 | `reproduce_isolation.py`、`reproduce_linux_isolation.py`、`mcp_isolated_macos.py` | OS 级 MCP 隔离检查 |
| 发布 | `check_distribution.py`、`qec-graph.spec` | 分发包元数据检查和 PyInstaller spec |
| 性能 | `bench.py` | 生成增量负载和固定来源基准 |
| 知识证据 | `reproduce_knowledge.py` | 对比完整阅读、原文搜索和任务上下文；不执行 LLM |
| 离线准备 | `prepare_arxiv.py` | 识别入口、组装字面 include，写出 `document/2`；不调用 AI、不执行 TeX |

标准门禁：

```sh
python tools/reproduce.py --out build/reproduce
python tools/check_distribution.py dist
```

`tools/reproduce_*` 脚本把机器可读报告写到 `build/`；`validation/` 索引当前可执行检查。

运行离线证据对照，或只读使用已登记的 machine release：

```sh
python tools/reproduce_knowledge.py --out build/knowledge-synthetic.json --include-payloads
python tools/reproduce_knowledge.py --machine /path/to/machine --out build/knowledge-real.json --include-payloads
```

`--release` 固定旧 release。`--cases` 接受 JSON 列表，每项含 `name`、`query`、
`kind`、`purpose`、`source_version_id` 和 `expected_evidence`（精确段落字符串）。
未提供题目时，从现有来源生成机械探针，不是经过整理的科学问题。报告披露检索覆盖和
回退。`--include-payloads` 将精确工具返回保存在本地；省略时只保存哈希和测量。
A/B/C 测量证据检索，不评定模型回答质量或数学正确性。

## 离线准备

`tools/prepare_arxiv.py` 按内容识别 LaTeX 入口，把字面 include 组装成
`entry.tex`，并写出带 section 层级、block 文本和来源区间的 `document/2`。
不调用 AI、不执行 TeX、不要求工程可编译。

```bash
python tools/prepare_arxiv.py /path/to/source-tree \
  --entry main.tex --out build/prepared/paper --json
```

`--no-parser-recovery` 和 `--no-transparent-containers` 可关闭可选的 partial
结构恢复。退出码 `0` 表示 `document_complete`；`2` 表示正文完整但结构 partial，
或正文未解析完整。

输出目录作为一个整体管理：产物先暂存，再通过带 journal 的 rename 发布，普通
失败会保留上一份完整产物；已存在但没有 prepare manifest 的目录会被拒绝。只有
显式传 `--overwrite` 才会整体替换该目录，包括其中无关的文件。如果进程在两次
目录 rename 之间被终止，目标路径会暂时消失，下一次写入或 `--recover` 会从 journal
恢复上一份结果并清理遗留的暂存目录。恢复会对比目标 manifest 与 journal 记录的
版本；如果目标被别处重新创建，会报告冲突（退出码 `1`）并保留 backup 与 journal：

```bash
python tools/prepare_arxiv.py --out build/prepared/paper --recover
```
