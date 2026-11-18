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
| 离线准备与提取 | `prepare_compiled.py`、`reproduce_preparation.py`、`report_preparation.py`、`compare_preparation.py`、`extract_prepared.py` | 原生编译、固定语料回放与证据绑定提取 |

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

新准备流程使用 `prepare_compiled.py`：先在本地沙箱编译原始工程，再转换为带来源映射的
TeX 语法 JSON，保留公式、作者结构、表格单元格/合并、图与资产、脚注、字面 BIB 和实际
AUX/BBL/BCF 引用绑定。不调用 AI、不执行科研抽取。详见[材料合同](../docs/design/DESIGN.zh-CN.md#54-离线来源准备)。

```sh
python tools/prepare_compiled.py /path/to/source-tree --entry main.tex --out build/material/paper
python tools/prepare_compiled.py --out build/material/paper --check
python tools/prepare_compiled.py /path/to/source-tree --entry main.tex \
  --support-dir /path/to/pinned-dependencies --out build/material/paper
python tools/reproduce_preparation.py --manifest test-sources/arxiv-sources/manifest.json --out build/material-replay
python tools/report_preparation.py --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/material-replay --out build/preparation-acceptance.json
python tools/report_preparation.py --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/material-replay --out build/preparation-acceptance.json --check
python tools/compare_preparation.py --baseline build/preparation-v19/final \
  --current build/preparation-refactor/final-verified --out build/preparation-comparison.json
```

`--engine` 选择本地引擎；可重复 `--support-dir` 指定并记录支持文件哈希。不下载依赖、
不修改系统 TeX。退出 0 表示 ready，2 表示显式 partial，1 表示输入/配置或发布失败。
partial 重试保留旧 ready 并写到 `.attempt`。`--check` 不重建，只验收产物和精确原文范围。
macOS 使用 sandbox-exec；Linux 要求 bubblewrap。隔离不支持时不会执行无约束 TeX。
编译成功后，受支持的非 UTF-8 字节可经可逆转写与额外原生/PDF 文字核验进入准备层，
保存 `source-projection.json`、`projected-sources/` 和原始字节定位。Harvmac 使用已确认
依赖版本的原生语法适配，TeX 导出保留原方言，结构与书目写入共用 JSON 合同。
`manifest.preparation_capabilities` 分开报告正文、书目、引用准备和唯一绑定。v19 将完整
保留的交叉引用歧义视为准备完成；`status=ambiguous` 与全部候选保留，唯一绑定仍为
partial，缺失目标仍阻止 ready。`--support-dir` 的搜索顺序为作者包内文件、显式支持、系统文件，
编译若改写显式依赖则失败；支持目录需固定内容并保留哈希。

`report_preparation.py` 只读完整回放和归档材料，重新计算计数及来源 probe；拒绝代码/语料
哈希过时、缺失输入或摘要与材料不一致。回放使用 `--cases` 时，报告也须传相同 `--cases`。
可用 `--baseline-revision <commit>` 固定比较基线，`--machine-evaluation <json>` 附加
独立评测的成功或失败证据；`--check` 不编译、不修改报告、不调用模型。

交付为带 `content.json` 的 `qecgraph.prepare/3`，不是研究记录或 workspace 快照；尚无任意宏展开。

流程导出 `normalized.tex` 和 `normalized-map.json`，再用同一引擎/支持文件重编译派生副本。
支持的表面改写包括宏/分组参数之外的数学定界符，以及唯一声明、运行时 key 已确认的引用宏展开。
仅对标准 article/report/book 类内联实际使用的经典 BBL；RevTeX 延迟文献/脚注和 Biblatex
保留外部调用及内容。未知宏、作者文档类与资产保留。`normalization.json` 独立记录语法检查、
重编译和可选的 pdftotext 逐页去空白文字比较。检测到不一致时材料保持 partial；文字一致
不代表像素一致或数学等价。`content.json` 坐标指向 `entry.tex`；派生片段必须先通过已验证的
统一格式映射定位原文。`--check` 不会重新编译。

中断的发布可在下次写入时恢复，也可以显式恢复。

```sh
python tools/prepare_compiled.py --out build/material/paper --recover
```

发布器核对日志记录的 manifest 与产物哈希。发生冲突时保留恢复证据，退出 1。
已验证的材料可供提取。

```sh
python tools/extract_prepared.py build/material/paper --out build/extracted/paper.json
```

重构时用 `compare_preparation.py` 独立重新打开两组保留回放，比较稳定的来源、语法、
引用、映射、诊断、能力和结果。易变的原生日志/PDF 字节和已验证构建/投影报告哈希不
参与对照，输出明确列出这些限制；存在差异时退出 2，不重新编译或调用模型。
