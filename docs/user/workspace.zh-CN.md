# 工作区使用说明

> **Status: Current (0.6.x).** Workspace configuration, Obsidian and provider handoff.

> [English](workspace.md) · **中文**

本说明对应已发布的 `0.6.3` 版本。已有的 `qecgraph`、`qec-latex-split`、
`qecgraph-mcp` 及 SourceGraph、LemmaGraph、DataGraph 命令继续可用；Lean 执行功能已移除，见[系统设计](../design/DESIGN.zh-CN.md#10-lean-路线已移除)。
本说明描述受支持的工作流；[系统设计](../design/DESIGN.zh-CN.md)定义契约。
[验证索引](../../validation/README.zh-CN.md)列出当前可执行检查；历史运行产物保留在
Git history。

> [!WARNING]
> 人类笔记不作为检索输入。新布局迁移时直接删除旧生成器管理的整个 `human/`，不做备份；详见下文。

非 UTF-8 TeX 支持显式的 Latin-1、Latin-9 和 Windows-1252 声明。也可在工作区配置的 `[encodings]` 中用归档 SHA-256 作键、受支持的编码名称作值，再运行 `rebuild`。原始归档保持原样。来源读取会标明 UTF-8 派生文本，并给出原始字节范围。

## 本页目录

- [建库和日常操作](#建库和日常操作)
- [研究查询和审核](#研究查询和审核)
- [Obsidian 和机器访问隔离](#obsidian-和机器访问隔离)
- [从旧库迁移](#导入现有-corpus)

## 建库和日常操作

在 Python 3.11+ POSIX 环境中安装实际 wheel。无需 API key。

```bash
python -m pip install /path/to/qec_graph-0.6.3-py3-none-any.whl
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

例如设置 `[ai].max_parallel_packages = 3`，即可同时抽取最多三篇论文；同一论文内的
各个 skill 仍按顺序运行。校验后的思路提议先发布到 machine release，ThoughtsGraph
与 `human/` 读取同一份结果。Markdown 生成器不会再次调用 AI；
`qec-graph human build` 可以离线从固定发布重新生成笔记。

多文件 TeX 论文同样默认进入 AI 抽取：请求包含已选主文件，以及通过其 include
登记的正文和附录文件。每个文件提供明确行号和内容哈希，引用指向实际文件。
同一压缩包中无关的稿件不会一起送出；缺文件或超预算明确报错，不静默截断。
思路引用只保留便于全文搜索的关键短句（建议少于 240 字符，最多 480 字符），
解释和适用条件留在 AI 回答中。新抽取使用 skill v5，已有提议仍可读取。
生成的数据和 human 笔记统一使用英文，包括九问、回答、主题词、书目信息、缺失说明与
软件目录。含中文的 AI 输出在缓存和发布前被拒绝。运行 `sync` 会重新抽取旧中文提案，
已完成的英文提案继续复用；human 从同一个新 release 离线生成。原始证据不做翻译。
无效响应最多进行一次使用相同证据和校验的纠错请求；再次失败则保留待处理，供以后 sync 重试。

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

在 Obsidian 中打开 `~/qec/human`，按年月目录浏览。每篇论文只有一个
`human/YYYY/MM/一作姓_文章前两个词_thoughts.md`，正文放九个 ThoughtsGraph 问题、
AI 回答及原文依据。文件最前面是 Obsidian YAML：

```yaml
---
tags:
  - surface-codes
  - erasure-decoding
link: "https://example.org/paper"
title: "Surface codes under erasure"
author:
  - "Ada Lovelace"
---
```

这只是格式示例。实际属性来自登记材料与有引用的 AI 元数据：tags 是论文主要主题，
author 按原文顺序保留完整姓名，文件名只取一作姓氏与标题按空白分隔的前两个词，
如 Diego Ruiz 对应 `Ruiz_Entropy_threshold_thoughts.md`。年月优先取 arXiv 原始包名：
`arXiv-2611.12971v2.tar.gz` 对应 `2026/11/`，与论文正文日期、下载时间无关；v2 等版本
后缀不改变首次提交年月。非 arXiv 包名才回退到来源日期，缺少或冲突的年月用 `unknown`。
sync/rebuild 会将回执包名纳入机器快照；旧库先运行一次 `qec-graph sync` 补齐，再由
`human build` 读取固定快照。新路径发布后删除旧的全名笔记。
未知作者/标题用 `UnknownAuthor`/`Untitled_Paper`，
同名论文追加 work ID 短哈希。同一 work 的多个版本共用一份文件，回答保留各自的版本。
[完整契约](../design/DESIGN.zh-CN.md#9-人类视图)

`qec-graph human build` 只从当前固定 machine release 渲染，不调用 AI；配置的 AI 抽取
发生在 `sync`，升级 skill 不会自动重抽已经完成的批次。没有答案时明确显示缺失。
不再生成索引、实体页、原文预览、墓碑页或 `notes/`。个人笔记放在 `human/` 外面。

**从 v0.6.2 旧布局迁移：** v0.6.3 首次渲染时识别旧管理历史，直接删除整个
旧 `human/`，包括原有 `notes/`，不读取其中内容，也不生成备份，然后只输出论文笔记。
没有管理记录的外部 vault 会被拒绝。之后文件名变化时删除旧的受管理笔记。
状态和恢复日志放在 `.qecgraph/`；每份文件原子写入，中断显示 `human_stale`，重新运行
`qec-graph human build` 即可继续完成，不回滚 machine release。

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
