# 工作区使用说明

> **Status: Current (0.6.x).** Workspace configuration, Obsidian and provider handoff.

> [English](workspace.md) · **中文**

`0.6.0` 是当前 release。已有的 `qecgraph`、`qec-latex-split`、
`qecgraph-mcp` 及 SourceGraph、LemmaGraph、DataGraph 命令继续可用；Lean 为延期实验能力，见[系统设计](../design/DESIGN.zh-CN.md#10-lean延期不支持)。
本说明描述受支持的工作流；[系统设计](../design/DESIGN.zh-CN.md)定义契约。
[验证索引](../../validation/README.zh-CN.md)列出当前可执行检查；历史运行产物保留在
Git history。

> [!WARNING]
> `human/notes/` 是私有笔记。生成器、查询和 MCP 都不会读取它；不要把它当作检索输入。

## 本页目录

- [建库和日常操作](#建库和日常操作)
- [研究查询和审核](#研究查询和审核)
- [Obsidian 和机器访问隔离](#obsidian-和机器访问隔离)
- [从旧库迁移](#导入现有-corpus)

## 建库和日常操作

在 Python 3.11+ POSIX 环境中安装实际 wheel。无需 API key。

```bash
python -m pip install /path/to/qec_graph-0.6.0-py3-none-any.whl
mkdir -p ~/qec
cd ~/qec
qec-graph init
# Add downloaded source packages to inputs/ before syncing.
qec-graph sync --dry-run
qec-graph sync
qec-graph status
qec-graph rebuild
qec-graph validate
```

### AI 配置

`init` 会写入 `[ai]` 表和 OpenAI、Anthropic、OpenRouter、Claude Code 的接入点。
默认选中 OpenRouter，模型为 `deepseek/deepseek-v4.1-flash-1017`；`api_key` 留空，
由用户填写，或设置 `OPENROUTER_API_KEY` 环境变量。凭据可用后，`sync` 可以规范化
多个 TeX 根文档、恢复符合条件的解析失败并抽取语义提案。
直接写入 `qecgraph.toml` 的 key 受 `0600` 权限保护，但不应提交。

```toml
[ai]
enabled = true
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash-1017"
max_parallel_packages = 2
structure_fallback = true
extract_proposals = true

[ai.providers.openrouter]
kind = "openai_compatible"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
api_key = ""
```

`qec-graph ai status` 只报告当前 provider，不联网；`qec-graph ai test` 发出一次
带 schema 的连接探针。`qec-graph init` 不会自动调用这两个命令。

`structure_fallback` 默认开启，同时要求 provider 可用且允许上传来源。回退请求只包含
已选入口的带行号正文。正文边界必须独占行且唯一，正文也必须独立于外部 TeX 输入。
方案失败或被拒绝时，归档和收件箱副本仍可用于重试。状态报告显示回退结果。
回退成功的快照标为 `recovered_proposed`。读取含有此状态的发布前，先升级机器读取端。
升级后的 CLI 和 MCP 继续读取历史快照。

`extract_proposals` 默认开启。凭据可用后，`sync` 自动生成定理、假设、数据和研究思路提案。
设置为 `false` 可跳过语义抽取；设置 `[ai].enabled = false` 可关闭 AI。
已有配置中明确填写的接入点、模型和开关保持原值；新默认值用于新生成的配置及省略的选择项/开关。
skill、审核边界与升级行为见[研究思路抽取流程](data-and-search.zh-CN.md#提取与阅读研究思路)。
`max_parallel_packages` 限制该可选抽取的并发包数，发布和输入
消费仍串行。

Claude Code provider 使用 bare 模式，禁用工具、MCP 和会话持久化。
曾使用本地订阅登录的工作区升级时，请设置 `ANTHROPIC_API_KEY` 并移除自定义 CLI 参数。

结构发布提交后，失败的 AI 抽取仍保留为待处理。下次 `sync` 从归档重试失败的 skill。
即使禁用 AI，重建也会校验并复用已提交的归一化映射。旧版归一化方案与归档能逐字节复现
原投影时，重建可补齐发布绑定。未经确认的回退仍需要显式入口或新方案。

日常使用 `qec-graph sync`、`qec-graph status` 和 `qec-graph validate`。
终端更新同一条进度行，结束时显示成功或错误。`sync` 在成功归档并发布后清理 `inputs/` 中的副本，失败件留待重试。
加 `--json` 可查看详细报告。除 `init` 外，命令优先使用显式的 `--workspace`，
其次查找当前目录及其父目录，最后使用环境变量 `QECGRAPH_WORKSPACE`。
`init` 只使用当前目录，除非用 `--workspace` 指定其他目录。

再次 init 不覆盖配置，也不抽取；导入由 `sync` 执行。`--keep-inputs` 保留成功件，
`--no-human` 跳过人类渲染。
`rebuild` 检查整个归档库存和收据，包括此前解析失败或入口未决的材料。
归档和展开文件都通过核对时，可以复用与当前处理器、运行环境和配置完全匹配的快照。
`rebuild --include-inputs` 先做 sync，然后按归档重建。

来源默认登记，无发表或质量门槛。成功件在哈希校验、机器发布及提交登记后才消费；
部分批次退出 2，失败件留在收件箱或可恢复认领处。语义未知不妨碍保留来源，
但不会作为已知参数满足精确过滤。不要用仓库工作区替代用户数据的备份。

如包内有多个入口，从 `status --json` 查 `source_tree_hash` 和候选。
只有上游身份确有证据时才填写 `[sources]`。例如：

```toml
[entrypoints]
"实际来源树的 SHA-256" = "paper/main.tex"

[sources."实际来源树的 SHA-256"]
work_id = "arxiv:quant-ph/0610153"
upstream_version = "v1"
title = "Subsystem Codes"
```

包名、论文标题或 `archive_sha256` 不替代上游版本。相同声明版本出现不同来源树时保留并标冲突。
项目仅解析源码；不执行 TeX、包内脚本、软件安装或 Lean 构建。
TAR 扩展元数据（如 PAX 和 GNU 长文件名）单条最多 256 KiB，整包最多 4 MiB，连续扩展最多 32 条。
超限包会保留归档并报告 `limit_exceeded`，原始投递件也会留待处理。

## 研究查询和审核

```bash
qec-graph review list
qec-graph software import-seed
qec-graph software coverage
qec-graph software refresh --project-id software:stim  # 显式联网，仅公开元数据
qec-graph mcp config --workspace ~/qec
qec-graph mcp serve --workspace ~/qec
```

`mcp-config` 生成固定 release 的客户端配置。Codex、Claude Code 和 OpenCode 的
配置示例见 [MCP 设置](../../README.zh-CN.md#mcp)。源查询通过登记的 occurrence ID 和
Unicode 代码点半开区间定位；MCP 资源 URI 是固定标识，不能改写成文件路径。
CLI 可用 `query-tool TOOL --workspace ~/qec --arguments request.json` 调用同一查询层。
性能查询返回具体实验和曲线修订、未决条件、实际坐标；不会跨实验给出统一排名。
研究记录只使用当前 `qecgraph.research` 格式。
通过 `asset-add` 登记非 human 资产；只有被可见记录绑定的资产可按字节查询。

`extract-request SOURCE_ID` 导出有预算的摘录及确切定位。
可将该文件交给自行选定的 provider，按 `research` 输出
`{"provider":{"model_id":"…","processor_version":"…","prompt_sha256":"…"},"records":[…]}`。
`extract-submit REQUEST_ID response.json` 校验并暂存，
`extract-review PROPOSAL_ID --reviewer NAME --decision approve --rationale "…"`
才将确切草稿发布，并记录审核范围。拒绝或失效的草稿不进入默认结果。
这条审核只作用于新增语义断言；原始材料无须批准即可发现。
没有内置外部模型调用或曲线数字化，数据缺失会显示为待提取或未决。

## Obsidian 和机器访问隔离

在 Obsidian 中打开 `~/qec/human` 为 vault，从 `Index.md` 进入。
`human/generated` 是可重建页面；把个人内容放在 `human/notes`。
生成器不读取 notes，旧实体页可留 tombstone。多页更新按文件原子替换；
中途失败显示 `human_stale`，可运行 `qec-graph human build`，不会回滚机器发布。

单独授予 agent 和 MCP 机器发布目录，避免授予整个工作区。
Linux 可用仓库的 `compose.mcp-isolated.yaml`。从已安装 QEC Graph 的 Python 环境
运行 `python tools/reproduce_linux_isolation.py --out build/linux-isolation.json`
可用临时工作区复验只读挂载、网络隔离和实际 MCP 查询。
macOS 可用仓库中的实测隔离启动器：

```bash
python tools/mcp_isolated_macos.py --python /path/to/installed-venv/bin/python --machine ~/qec/machine
```

容器配置用 `compose.mcp-isolated.yaml`，设置 `QEC_MACHINE_DIR`、
`QEC_MCP_UID` 和 `QEC_MCP_GID`，仅只读挂载 machine。Linux 配置已用本地
替代 Ubuntu 基础镜像验证；[验证索引](../../validation/README.zh-CN.md)列出当前隔离
检查命令。这不构成通用 Docker Hub 构建的声明。不要把 MCP roots 或普通的 `--workspace` 参数
当作操作系统隔离。

## 导入现有 corpus

```bash
qec-graph validate-corpus --corpus /path/to/legacy-corpus
qec-graph workspace migrate --corpus /path/to/legacy-corpus --workspace /path/to/new-workspace
qec-graph rebuild --workspace /path/to/new-workspace
```

目标必须是独立的新目录。迁移保存旧修订、来源快照、资产和审核绑定，
报告缺少准确界类型、噪声、计数定义或实验上下文的旧记录。
原库保持可用；不合适时继续用原目录。旧库不含原始下载包时不会伪造这些资产。
升级程序与切换数据位置是独立操作；公开 PyPI 发行未执行。
