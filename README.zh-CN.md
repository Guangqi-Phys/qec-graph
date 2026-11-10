# QEC Graph

> 保留来源的 LaTeX → QEC 知识工作区，带 CLI、本地只读 MCP 服务和 Obsidian 视图。

> **中文** · [English](README.md)

QEC Graph 归档原始 LaTeX 源包，按精确来源区间抽取结构，把类型化的 QEC 研究记录
和字段级证据链接起来，并发布不可变机器 release。同一个 release 同时服务 CLI、
只读 MCP 服务器和生成的 Obsidian 视图；人类视图不是权威来源，`human/notes/`
永不被读取。

## 安装

```sh
curl -fsSL https://raw.githubusercontent.com/Guangqi-Phys/qec-graph/main/install.sh | sh
```

再次运行同一命令即可更新。单文件可执行程序内置 Python。
下载支持 macOS（Apple Silicon）以及 Linux（x86_64 和 arm64）。
[GitHub Releases](https://github.com/Guangqi-Phys/qec-graph/releases)

## 快速开始

在一个空目录中运行，或只保留 `inputs/`。有其他条目时 `init` 会在写入前停止。

```sh
mkdir my-qec
cd my-qec
qec-graph init
# The command creates inputs/ and qecgraph.toml.
# Optional AI: edit [ai] in qecgraph.toml, then:
qec-graph ai status
qec-graph ai test
# Put downloaded LaTeX source packages in inputs/, then run:
qec-graph sync
qec-graph status
qec-graph validate
```

`init` 不抽取、不调用 AI，只准备收件箱和配置；导入由 `qec-graph sync` 执行。
AI 是可选的：在 `sync` 前配置 `[ai]` 并运行 `qec-graph ai test`，即可启用多根
文档规范化和 proposal 抽取；不配置 AI 时，单根包仍走确定性路径。

成功导入后原始包留在 `archive/`，收件箱副本被清除。把 `human/` 作为 Obsidian
vault 打开，从 `Index.md` 开始。反复失败的包用
`qec-graph inputs quarantine <name>` 处理。

## AI 抽取

AI 是可选能力。配置后，`sync` 会把多根 TeX 包规范化为一个入口，并提议定理、
假设和数据记录。原始包仍是权威来源；AI 结果在审核前保持 `proposed`。

`qecgraph.toml` 会预置以下接入点：

| 接入点 | 类型 | 默认凭据 |
|---|---|---|
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| OpenRouter | `openai_compatible` | `OPENROUTER_API_KEY` |
| Claude Code | `cli` | bare 模式下的 `ANTHROPIC_API_KEY` |

设置 provider、model 和 key。`api_key` 可以直接填，也可以留空并用
`api_key_env`：

```toml
[ai]
enabled = true
provider = "openrouter"
model = "your-model-id"
max_parallel_packages = 2

[ai.providers.openrouter]
kind = "openai_compatible"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
api_key = ""
```

先检查配置（不会发送论文文本），再导入：

```sh
qec-graph ai status
qec-graph ai test
qec-graph sync
```

如果 `inputs/` 中有多个 TeX 根文档，normalizer 会提议一个带来源映射的
`main.tex`，然后由 parser 提取。AI 不可用时，多根包会保持归档并提示需要入口。

## 工作流程

流水线是单 writer；每个节点都为下一节点留下具名产物。实现文档位于 `docs/user/`、`docs/design/` 和 `docs/operations/`。

| 节点 | 目的 | 实现文档 | 输入 | 输出 |
|---|---|---|---|---|
| `inputs/` | 接收候选源包 | [快速开始](docs/user/quickstart.zh-CN.md)、[工作区说明](docs/user/workspace.zh-CN.md) | `.tex`、`.tar`、`.tar.gz`/`.tgz`、`.zip`、`.gz` | 已认领的收件箱文件和 `.processing/<job>/job.json` |
| `archive/` | 保存原始字节和 receipt | [系统设计](docs/design/DESIGN.zh-CN.md#7-工作区事务与发布协议)、[工作区说明](docs/user/workspace.zh-CN.md) | 已认领的源包 | `archive/blobs/sha256/<sha256>`、`archive/receipts/<job>.json` |
| `source tree` | 验证、解包并选择或规范化入口点 | [工作区说明](docs/user/workspace.zh-CN.md)、[切割器](docs/user/splitter.zh-CN.md)、[AI 抽取](#ai-抽取) | 归档 blob | `sources/<tree-hash>/...`；可选派生 `machine/derived/normalizations/.../main.tex` |
| `parser` | 抽取 sections、environments、labels、refs 和区间 | [切割器](docs/user/splitter.zh-CN.md)、[系统设计](docs/design/DESIGN.zh-CN.md#5-来源抽取) | 已验证的 `.tex` 树 | store：`snapshots/<snapshot-id>/`；workspace：`machine/source_snapshots/<snapshot-id>/`；两者都含 `graph.json`、`manifest.json`、`report.json`、`graph.sqlite`、`nodes/<kind>/` |
| `research records` | 保存类型化 QEC 对象和字段证据 | [数据与检索](docs/user/data-and-search.zh-CN.md)、[系统设计](docs/design/DESIGN.zh-CN.md#4-数据契约) | 来源快照和 `research` JSON | `machine/research/<hash(id)>/<hash(revision)>.json`，含 `schema: qecgraph.research` |
| `review` | 把提案和决定绑定到精确内容 | [审核](docs/operations/review.zh-CN.md)、[系统设计](docs/design/DESIGN.zh-CN.md#6-审核证据和查询资格) | proposal JSON 和显式决定 | `machine/proposals/<hash>.json`、`machine/reviews/<hash>.json`、`machine/states/<revision>.json` |
| `release` | 验证全部内容并发布不可变 release | [系统设计](docs/design/DESIGN.zh-CN.md#7-工作区事务与发布协议)、[维护](docs/operations/maintenance.zh-CN.md) | staged records 和 snapshots | 含 `format`、`revision` 的 `machine/CURRENT.json`；`machine/states/<revision>.json` |
| `CLI` | 读取固定 workspace、store 或 corpus 作用域 | [进阶用法](docs/user/advanced-usage.zh-CN.md)、[数据与检索](docs/user/data-and-search.zh-CN.md) | `--workspace`、`--machine`、`--store` 或 `--corpus`；`query-tool` 的 JSON 参数 | 终端文本或版本化 JSON |
| `MCP` | 通过本地 stdio 提供只读工具 | [MCP 设置](#mcp)、[数据与检索](docs/user/data-and-search.zh-CN.md) | stdio 上的 JSON-RPC 2.0；固定一个 release；13 个工具 | JSON-RPC 帧、text/structured content、`qec://source/...` resources |
| `human/` | 渲染 Obsidian 视图，绝不回写 | [工作区说明](docs/user/workspace.zh-CN.md)、[系统设计](docs/design/DESIGN.zh-CN.md#9-人类视图) | 已发布机器 release | `human/Index.md`、`human/generated/**/*.md`、`human/generated/.qecgraph-manifest.json`；`human/notes/` 不变 |

单个 writer 拥有整条流水线。读取端固定一个 `CURRENT` release；验证失败时旧
release 保持可读。`human/notes/` 永不被读取。

> [!NOTE]
> QEC Graph 不是 TeX 引擎、PDF/OCR 流水线、大规模码距求解器或 Lean 验证器。
> Lean 是**延期/实验性**能力；数据库、查询和 MCP 路径不导入也不调用它。

## 一览

| 能力 | 已实现内容 |
|---|---|
| 导入 | TeX/gzip/tar/tar.gz/ZIP 识别、安全解包、SHA-256 blob 和 receipt、入口点选择 |
| 来源保真 | UTF-8 字节哈希、Unicode codepoint 半开区间、行号从 1 开始、稳定 ID 和修订 |
| 研究模型 | `qecgraph.research` 记录、26 kinds、41 typed relations、字段证据、显式 unknown/conflict 状态 |
| 审核 | proposal/diff、显式 decide、哈希绑定 apply、stale review 检测 |
| 查询 | 精确过滤、有界上下文、依赖/影响遍历、code/performance/software 查询 |
| MCP | 13 个固定作用域只读工具、`qec://source/...` resources、budgets、每会话固定 release |
| AI 辅助 | 可选 provider 配置、多 TeX 根的来源映射规范化、定理/假设/数据提议 |
| 人类视图 | 带稳定链接和 tombstone 的生成 Obsidian 页面；`human/notes/` 私有 |
| 接口面 | workspace 为主；单篇 store 和多篇 corpus 仍可用 |

## 已实现接口面

| 接口面 | 当前实现 |
|---|---|
| 工作区事务 | claim → archive → unpack → entry point → extract → stage → validate → publish → consume，带 POSIX writer lock 和崩溃恢复 |
| 来源抽取 | `pylatexenc==2.10`、来源保真区间、include/resource 解析、显式 diagnostics、内容校验的增量 AST cache |
| 研究记录 | `qecgraph.research` kinds，例如 `quantum_code`、`check_matrix`、`distance_estimate`、`performance_curve`、`experiment` 和 `software_usage` |
| 审核与证据 | `proposal` / `review` envelope、字段级证据、reviewed dependency closure；stale/unbound 默认排除 |
| 读取查询 | `search`、`show`、`deps`、`impact`、`context`、`codes`、`performance`、`software`；SQLite/FTS5 加确定性 fallback |
| MCP 服务 | 本地 stdio JSON-RPC `2025-06-18`、只读工具、source resources、每调用 budget、不接受路径或 shell 参数 |
| 人类视图 | 确定性的 `human/Index.md` 和 `human/generated/` 页面、逐页原子写、tombstone、`human_stale` 恢复 |
| AI 层 | provider 适配、schema 校验 client、版本化 skills、来源映射规范化、可审核 proposal |
| 分发 | wheel/sdist、standalone executable、research Compose profile 和只读 MCP 隔离 profile |

## MCP

MCP 服务器是固定到一个机器 release 的本地 stdio 进程。它只读：工具不能传入
文件系统路径、SQL、shell 命令、其他 workspace 或其他 release。来源文本作为
数据处理，绝不作为指令。

### 启动服务器

在工作区根目录：

```sh
qec-graph mcp config --workspace .
```

它会打印一个 `mcpServers.qecgraph` 对象，command 和 `--machine` 路径指向当前
固定 release。把这个对象放进客户端配置，或直接启动：

```sh
qec-graph mcp serve --machine "$PWD/machine"
```

严格部署只挂载 `machine/` 并传 `--machine`。`--workspace` 在本地方便，但不是
操作系统隔离边界。严格部署中 `human/`、`inputs/`，尤其是 `human/notes/`，必须
不可读。

### 读取工具

| 工具组 | 可用工具 |
|---|---|
| 图读取 | `qecgraph_search`、`qecgraph_show`、`qecgraph_context`、`qecgraph_deps`、`qecgraph_impact` |
| Workspace 记录和来源 | `qec_workspace_status`、`qec_get_entity`、`qec_get_context`、`qec_get_source`、`qec_get_asset` |
| 结构化 QEC 查询 | `qec_find_codes`、`qec_find_performance`、`qec_find_software` |

所有工具都接受会话 budget 内的 `max_chars`。Search 和三个 `qec_find_*` 还接受
`limit`/`offset`。来源文本使用半开 Unicode codepoint 区间；受管理资产字节使用
byte offset。结果说明 scope、证据状态和是否截断。无结果只表示固定作用域内无匹配，
不表示定理或码不存在。

### 接入客户端

下面的例子使用 shell command；把 `/absolute/path/to/qec-graph` 和
`/absolute/path/to/machine` 换成已安装可执行文件和 workspace 的 machine 目录。
要固定特定 release，加 `--release <release-id>`。

#### Codex

```sh
codex mcp add qecgraph -- "$(command -v qec-graph)" mcp serve --machine "$PWD/machine"
codex mcp list
```

等价的 `~/.codex/config.toml`：

```toml
[mcp_servers.qecgraph]
command = "/absolute/path/to/qec-graph"
args = ["mcp", "serve", "--machine", "/absolute/path/to/machine"]
```

添加后打开新的 Codex 会话。Codex 启动 stdio 进程，把只读工具暴露给 agent。

#### Claude Code

```sh
claude mcp add --transport stdio qecgraph -- "$(command -v qec-graph)" mcp serve --machine "$PWD/machine"
claude mcp list
```

等价的项目 `.mcp.json`：

```json
{
  "mcpServers": {
    "qecgraph": {
      "type": "stdio",
      "command": "/absolute/path/to/qec-graph",
      "args": ["mcp", "serve", "--machine", "/absolute/path/to/machine"]
    }
  }
}
```

Claude Code 每会话启动服务器；出现提示时批准项目级 `.mcp.json`。

#### OpenCode

```sh
opencode mcp add qecgraph -- qec-graph mcp serve --machine "$PWD/machine"
opencode mcp list
```

等价的 `opencode.json` 或 `opencode.jsonc`：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "qecgraph": {
        "type": "local",
        "command": ["/absolute/path/to/qec-graph", "mcp", "serve", "--machine", "/absolute/path/to/machine"]
      }
    }
  }
}
```

用 `disabled: true` 可以保留配置但不连接。

### 固定和刷新

`qec-graph mcp config --workspace .` 默认带 `--release`，客户端得到生成配置时的
当前 release。`qec-graph sync` 发布新 release 后，重新运行该命令并替换客户端
条目；已有会话在重启前保持旧 release。只用 machine 挂载时使用
`qec-graph mcp config --machine /path/to/machine`。

## 文档地图

| 我想…… | 阅读 |
|---|---|
| 运行最短示例 | [快速开始](docs/user/quickstart.zh-CN.md) |
| 配置工作区、归档或 Obsidian | [工作区说明](docs/user/workspace.zh-CN.md) |
| 搜索记录、码或性能点 | [数据与检索](docs/user/data-and-search.zh-CN.md) |
| 查命令、退出码或发布检查 | [进阶用法](docs/user/advanced-usage.zh-CN.md) |
| 理解身份、证据和发布 | [系统设计](docs/design/DESIGN.zh-CN.md) |
| 浏览文档索引 | [docs/README.zh-CN.md](docs/README.zh-CN.md) |
| 运维 store 或 corpus | [运维](docs/operations/README.zh-CN.md) |

## 许可证

MIT。开发与文档规则见 [LICENSE](LICENSE) 和 [CONTRIBUTING](CONTRIBUTING.md)。
