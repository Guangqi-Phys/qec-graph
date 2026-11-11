# 进阶用法

> **状态：当前（0.6.x）。** 安装、工作区、查询和发布说明。

> **中文** · [English](advanced-usage.md)

安装命令、日常流程和 MCP 配置见[根 README](../../README.zh-CN.md)。

## 本页目录

- [安装选项](#安装选项)
- [试运行自带论文](#试运行自带论文)
- [维护工作区](#维护工作区)
- [退出码和脚本输出](#退出码和脚本输出)
- [管理 Obsidian vault 和研究记录](#管理-obsidian-vault-和研究记录)
- [从 CLI 查询工作区](#从-cli-查询工作区)
- [处理单篇论文和旧 corpus](#处理单篇论文和旧-corpus)
- [复现检查](#复现检查)

> [!TIP]
> 除非某节另有说明，命令都在工作区根目录运行。`--workspace PATH`
> 覆盖当前目录；`--json` 是脚本使用的机器可读模式。

## 安装选项

安装器根据操作系统和 CPU 从 GitHub 最新稳定 release 选择可执行文件；
没有稳定 release 时使用最新的预发布版。它会校验可执行文件的 SHA-256 和版本，
然后替换 `~/.local/bin/qec-graph`。如果该目录被加入 `PATH`，请打开新终端。
Linux 构建由 release workflow 在 Ubuntu 22.04（glibc 2.35）上测试。
[Release 资产](https://github.com/Guangqi-Phys/qec-graph/releases/latest)

从 checkout 安装需要 Python 3.11 或以上、带 FTS5 的 SQLite 和本地 POSIX 文件系统。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

本地 wheel 则把 wheel 路径传给 `python -m pip install`。本地导入和查询不需要 API key。

构建单文件可执行程序时，在目标操作系统和 CPU 上运行下面的命令。Linux 上请安装
`binutils`，并在你计划支持的最老 glibc 发行版上构建。

```sh
python3.13 -m venv build/standalone-venv
build/standalone-venv/bin/python -m pip install . 'PyInstaller==6.22.3'
PYINSTALLER_CONFIG_DIR="$PWD/build/standalone-cache" \
  build/standalone-venv/bin/python -m PyInstaller --noconfirm \
  --distpath dist/standalone --workpath build/standalone tools/qec-graph.spec
```

直接运行 `dist/standalone/qec-graph`，或把它安装到 `PATH` 中的用户目录。

> [!NOTE]
> Lean 在 0.6.x 中延期。实验性的 `lean` 命令组和 Lean fixtures 不属于受支持流程；
> 见[设计说明](../design/DESIGN.zh-CN.md#10-lean延期不支持)。

## 试运行自带论文

在已安装 `qec-graph` 并放入 `PATH` 的 checkout 中运行。示例每次都在 `build/`
下创建新工作区。

```sh
mkdir -p build
workspace="$(mktemp -d "$PWD/build/qec-workspace.XXXXXX")"
mkdir -p "$workspace/inputs"
COPYFILE_DISABLE=1 tar -czf "$workspace/inputs/qec-demo.tar.gz" -C examples/paper .

qec-graph init --workspace "$workspace"
qec-graph sync --workspace "$workspace"
qec-graph status --workspace "$workspace"
qec-graph validate --workspace "$workspace"
qec-graph query search HGP --workspace "$workspace" --limit 2
```

在重定向终端中，自带论文产生以下结果行。

```text
[################] init: OK (0/0 packages indexed)
[################] sync: OK (1/1 packages indexed)
[################] status: OK (1/1 packages indexed)
[################] validate: OK
```

前两个搜索结果是公式 `eq:hgp-checks` 和 `eq:hgp-commutation`。它们的 `source`
区间把结果定位到 LaTeX。响应还标识固定 release，并说明还有更多匹配。
[如何读取和复现查询](data-and-search.zh-CN.md#读取和复现查询结果)

把 `[ai].max_parallel_packages` 设为小值（例如 `2`），可以让 `sync` 并发准备多个文献包。只有 AI 调用重叠；registry 发布和输入消费仍保持串行。

## 维护工作区

除 `init` 外，命令从当前目录及其父目录查找工作区。用
`--workspace /path/to/workspace` 显式选择。`init` 只使用当前目录，除非显式传入
`--workspace`。日常命令 `sync`、`status` 和 `validate` 在当前目录不在已初始化
工作区时，可用 `QECGRAPH_WORKSPACE` 作为回退。

工作区维护命令默认打印一行结果。终端中，较长操作还会在这一行显示进度。
脚本中请传 `--json` 获取完整报告，包括使用 `--workspace` 或重定向输出时。
partial 状态在两种模式下都退出 2。无效命令语法退出 64。命令选项用
`qec-graph help <command>`，已安装版本用 `qec-graph --version`。

| 任务 | 从工作区根目录运行的命令 |
| --- | --- |
| 创建工作区和 AI 配置，不抽取内容 | `qec-graph init` |
| 不联网查看当前 AI provider | `qec-graph ai status` |
| 用一次探针测试 AI 接入 | `qec-graph ai test` |
| 列出待审核的 AI proposals | `qec-graph ai proposals --json` |
| 记录 AI proposal 审核决定 | `qec-graph ai decide PROPOSAL --workspace . --actor-id ada --actor-kind human --decision approve --rationale "checked" --checked-scope statement --checked-scope hypotheses --checked-scope dependencies` |
| 列出 AI 审核决定 | `qec-graph ai decisions --json` |
| 预览待处理输入 | `qec-graph sync --dry-run` |
| 导入并保留收件箱副本 | `qec-graph sync --keep-inputs` |
| 查看包和失败详情 | `qec-graph status --json` |
| 列出待处理和隔离文件 | `qec-graph inputs list` |
| 移走失败包 | `qec-graph inputs quarantine broken.zip` |
| 把包放回收件箱 | `qec-graph inputs restore broken.zip` |
| 重新检查整个归档并重建派生工作区 | `qec-graph rebuild` |
| 先导入收件箱，再从归档重建 | `qec-graph rebuild --include-inputs` |
| 导入或重建但不生成 Obsidian 页面 | `qec-graph sync --no-human` 或 `qec-graph rebuild --no-human` |

成功导入在归档、验证和发布后清除收件箱副本。失败包保留以便重试，partial 批次
退出码为 2。用 `status --json` 查找有歧义的来源树和入口候选。工作区说明展示
如何固定入口并登记显式上游版本。[工作区配置](workspace.zh-CN.md#建库和日常操作)

隔离会保留文件、归档 blob 和收据。status 用哈希标识已归档内容，并单独列出
被隔离输入。`sync` 读取收件箱，显式 `rebuild` 仍检查整个归档。

用 `qec-graph doctor --json` 诊断配置、CURRENT 和收件箱问题，不做修改；它报告
工作区元数据和计数。用 `validate` 校验归档和快照哈希。
`qec-graph snapshot list` 显示当前工作区 release 和本地保存的 registry 状态，
包括可能从未发布的候选。用 `--store` 或 `--corpus` 列出对应范围的快照或状态。

## 退出码和脚本输出

在命令前或后传 `--json`，请求详细工作区报告和带版本的 CLI 错误。成功 JSON
报告保留各命令自己的字段。partial 工作区操作仍返回完整报告，包括计数和单个
失败，并退出 2。`status --json` 包含所选 release 的库存计数和 Obsidian 视图
状态。没有匹配观察时视图为 `unknown`。视图新鲜度与包状态、退出码分开报告。
用 `qec-graph version --json` 读取 JSON 格式的已安装版本。

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功完成 |
| `1` | 输入、存储、验证或内部错误 |
| `2` | partial 操作，或带失败的验证报告 |
| `4` | 找不到必需文件或精确查询目标 |
| `5` | 写者持有锁，或收件箱移动会覆盖文件 |
| `64` | 无效命令语法 |
| `130` | 被中断 |

例如，`qec-graph --json check-css --hx missing.json --hz hz.json` 返回
`envelope_version: 1` 和 `ok: false`。其 `error` 包含 `code`、`message`、
`hint`、`details`、`command` 和 `scope`；可选字段可以为 `null`。这些错误写到
stdout，脚本在成功和失败时都解析同一流。`mcp serve` 把 stdout 留给 MCP 帧，
启动错误写到 stderr。不加 `--json` 时，`query-tool` 保留 read tool 的响应；
加 `--json` 时，查询错误还包含 command、hint 和 envelope 版本，固定 release
或 snapshot scope 仍然附带。用 `--verbose` 把工作区阶段写到 stderr，或用
`--debug` 查看意外 CLI 失败的 traceback。工作区配置或 CURRENT 指针损坏时，
错误给出路径；运行 `qec-graph doctor` 做只读检查。

给 `mcp serve` 传 `--verbose`，或在 MCP 服务器环境设置
`QECGRAPH_LOG_LEVEL=DEBUG`，可把请求帧大小写到 stderr。内部错误诊断包含
数字请求 ID 或字符串 ID 的短哈希。请求文本、工具参数和来源段落不进入诊断。

相关命令也有分组名。例如 `workspace sync`、`query search` 和 `mcp serve`
与 `sync`、`search`、`serve-mcp` 使用相同选项和处理器。`lean` 组是实验性/
延期的，不属于受支持流程。用 `qec-graph help mcp serve` 查看分组命令的选项
和示例。`qec-graph help errors` 和 `qec-graph help json` 描述脚本输出。
原来的 `review <file>` 仍可用；分组形式用 `review propose <file>`。如果 review
文件名与动作同名，传 `./filename` 明确意图。

`qec-graph help aliases` 列出旧名称及替代命令。旧名称仍受支持，并在交互式
stderr 或 `QECGRAPH_DEPRECATIONS=1` 时发出提示。设置
`QECGRAPH_DEPRECATIONS=0` 关闭提示。`sync`、`status`、`validate` 和 `search`
等常用快捷命令不提示。

`--quiet` 隐藏进度和成功报告，保留失败及显式 `--json` 报告。`--color never`
关闭摘要颜色，`--color always` 强制开启。默认 `auto` 下，非空 `NO_COLOR`
关闭颜色，`FORCE_COLOR=1` 即使在重定向输出中也开启。动画需要交互式终端。

## 管理 Obsidian vault 和研究记录

把工作区的 `human/` 目录作为 Obsidian vault 打开，按 `YYYY/MM/` 浏览
`一作名_文章前两个词_thoughts.md`。每篇论文只有一份笔记，包含九个 ThoughtsGraph 问题、
AI 回答和原文依据。最前面依次放 YAML 的 `tags`、`link`、`title`、`author`，
tags 是文章主要主题。运行 `qec-graph human build` 从当前 machine release 重建，不调用 AI。

这是 main 上的 Unreleased 布局，替代 v0.6.2 的实体页 vault。首次迁移直接删除整个旧
受管理 `human/`，包括 `notes/`，不做备份。不再生成索引、墓碑页或其他文件，个人笔记
请放在别处。管理状态保存在 `.qecgraph/`。
[布局、缺失元数据与迁移规则](workspace.zh-CN.md#obsidian-和机器访问隔离)

用 `qec-graph review list` 查找 proposal ID，用 `qec-graph review show PROPOSAL_ID`
读取 provider 草稿及已记录决定。用 `qec-graph software import-seed` 加载自带软件
目录，用 `qec-graph software coverage` 查看覆盖。工作区说明覆盖显式资产登记、
软件元数据刷新和提取提案。用 `qec-graph review import REQUEST_ID response.json`
验证 provider 响应并作为草稿排队。审核者用 `qec-graph extract-review` 单独记录
决定。[研究和审核流程](workspace.zh-CN.md#研究查询和审核)

## 从 CLI 查询工作区

```sh
qec-graph search 'hypergraph product' --workspace "$workspace" --limit 10
qec-graph show "$identifier" --workspace "$workspace"
qec-graph context "$identifier" --workspace "$workspace" --depth 2
```

`show` 和 `context` 使用精确结果 ID。`deps` 和 `impact` 遍历已登记的图依赖。
传 `--release` 把查询固定到特定工作区 release。这些命令返回与工作区 MCP 工具
相同的 JSON envelope 和证据范围。

## 处理单篇论文和旧 corpus

在仓库根目录运行这些示例。命令写入 `build/` 下你指定的路径。

```sh
qec-graph split examples/paper/main.tex --project-id qec-demo --out build/split
qec-graph ingest examples/paper/main.tex --project-id qec-demo --out build/graph \
  --annotations examples/annotations.example.json
qec-graph validate --store build/graph
qec-graph context thm:hgp-length --store build/graph
```

Python 安装还提供 `qec-latex-split`。`qecgraph` 和 `python -m qecgraph` 入口
使用与 `qec-graph` 相同的 CLI。[切割参考](splitter.zh-CN.md) ·
[Corpus 参考](../operations/corpus.zh-CN.md)

把已有 corpus 复制到新工作区，使用
`qec-graph workspace-migrate --corpus /path/to/corpus --workspace /path/to/new-workspace`。
迁移保留来源快照、记录修订和审核绑定。[迁移指南](workspace.zh-CN.md#导入现有-corpus)

## 复现检查

维护者可用版本 tag 构建单文件可执行程序，并在发布 GitHub Release 资产前检查
Python wheel 和源码分发包。工作流对每个目标运行安装器回归，并把安装后的
可执行文件和 wheel 检查报告保留为 workflow artifacts。单独的 PyPI 工作流
接受已发布 tag，在上传前检查分发哈希。启用时，为仓库的 `pypi` environment
配置 reviewer，并向 PyPI Trusted Publishing 注册同一 environment 和
`pypi-publish.yml`。
[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)

在已安装 Python 环境的仓库根目录运行
`python tools/reproduce.py --out build/reproduce`，执行回归套件和自带端到端示例。
发布报告覆盖已安装包、迁移、真实来源、MCP 和 macOS 隔离检查。
[发布验证](../../validation/README.zh-CN.md)
