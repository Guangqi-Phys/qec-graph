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
| 离线准备 | `prepare_compiled.py`、`reproduce_preparation.py`、`report_preparation.py`、`prepare_arxiv.py` | 先编译的来源材料与固定语料回放；保留静态兼容工具 |

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
python tools/reproduce_preparation.py --manifest test-sources/arxiv-sources/manifest.json --out build/material-replay
python tools/report_preparation.py --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/material-replay --out build/preparation-acceptance.json
python tools/report_preparation.py --manifest test-sources/arxiv-sources/manifest.json \
  --replay build/material-replay --out build/preparation-acceptance.json --check
```

`--engine` 选择本地引擎；可重复 `--support-dir` 指定并记录支持文件哈希。不下载依赖、
不修改系统 TeX。退出 0 表示 ready，2 表示显式 partial，1 表示输入/配置或发布失败。
partial 重试保留旧 ready 并写到 `.attempt`。`--check` 不重建，只验收产物和精确原文范围。
macOS 使用 sandbox-exec；Linux 要求 bubblewrap。隔离不支持时不会执行无约束 TeX。
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

下面保留的静态接口独立存在；先编译路线不会自动回退到这里。

`tools/prepare_arxiv.py` 按内容识别 LaTeX 入口，把字面 include 组装成
`entry.tex`，并写出带 section 层级、block 文本和来源区间的 `document/2`。
默认不调用 AI；始终不执行 TeX、不要求工程可编译。

```bash
python tools/prepare_arxiv.py /path/to/source-tree \
  --entry main.tex --out build/prepared/paper --json
```

失败或不完整的输入可使用来源格式转换后备；所选配置须明确允许 AI 和来源上传：

```sh
python tools/prepare_arxiv.py /path/to/source-tree \
  --out build/prepared/paper --json \
  --ai-prepare --ai-config-root /path/to/config-directory
```

字面语法适配器先在本地运行，已完整通过的输入跳过模型。`prepare_input` v9 skill 只提交入口、编码、语法方案，
程序在派生副本上转换，再由独立下游解析器检查。模型不分类定理/证明，不提取科学内容。
失败保留旧输出；`normalization.json` 保存原始字节、哈希、操作与映射，来源坐标明确
标记派生层。既有 `document.json` 来自下游校验。`--ai-structure` 是弃用别名。
预算、超时与响应缓存使用所选配置；本工具不发布 workspace release。
`--ai-reasoning-effort low` 可仅为本次工具调用覆盖推理强度；OpenAI-compatible
provider 配置也可设 `reasoning_effort`。默认仍由 provider 决定，不同设置隔离响应缓存。

`--no-parser-recovery` 和 `--no-transparent-containers` 可关闭可选的 partial
结构恢复。退出码 `0` 表示 `document_complete`；`2` 表示正文完整但结构 partial，
或正文未解析完整。

输出目录作为一个整体管理：产物先暂存，再通过带 journal 的 rename 发布，普通
失败会保留上一份完整产物；已存在但没有 prepare manifest 的目录会被拒绝。只有
显式传 `--overwrite` 才会整体替换该目录，包括其中无关的文件。如果进程在两次
目录 rename 之间被终止，目标路径会暂时消失，下一次写入或 `--recover` 会从 journal
恢复上一份结果并清理遗留的暂存目录。恢复会对比目标 manifest 与 journal 记录的
版本及每个产物摘要；如果目标被别处重新创建，或 manifest 正确但产物缺失/被改写，
会报告冲突（退出码 `1`）并保留 backup 与 journal：

```bash
python tools/prepare_arxiv.py --out build/prepared/paper --recover
```
