# 为 QEC Graph 贡献

> **中文** · [English](CONTRIBUTING.md)

在带 SQLite FTS5 的 POSIX 系统上使用 Python 3.11 或以上。在 checkout 中运行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'pip>=25.1'
python -m pip install --group dev -e .
python -m ruff check qecgraph tests tools
python -m mypy
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
```

端到端检查运行 `python tools/reproduce.py --out build/reproduce`。
[文档索引](docs/README.zh-CN.md)和[系统设计](docs/design/DESIGN.zh-CN.md)指向需要
单独设置的 workspace、MCP 和 Lean 检查。提交变更时说明运行了哪些命令、哪些没有运行。

保持源码字节、稳定 ID、修订和证据绑定不变。测试使用临时 workspace。只提交你有权
重新分发的 fixtures，并记录其许可证和来源。合成记录应标记 synthetic，且绝不能
建立论文结论。

更新指南见[文档索引](docs/README.zh-CN.md)，兼容性变化见[变更日志](CHANGELOG.md)，
私下报告见[安全政策](SECURITY.zh-CN.md)。

## 文档规则

- 当前页面只放在 `docs/user/`、`docs/design/` 和 `docs/operations/`。没有重定向或
  归档树；被替代页面从 Git history 恢复。
- `docs/design/DESIGN.md` 是唯一设计文档。实现变更时在同一变更中扩展它，不要新增
  平行设计页。
- 每个当前页面都是双语的：`page.md` 为英文，`page.zh-CN.md` 为简体中文。两者都以
  一行状态标记开头，带语言切换，并保持相同标题层级、表格形状和可执行代码块。
  多于一个 `##` 小节的页面要有目录，锚点与标题一致。
- 优先使用小表格、GitHub alerts（`> [!NOTE]`、`> [!TIP]`、`> [!WARNING]`）和
  Mermaid 图来说明分支或流程。不要添加重复正文的装饰性标记。
- 移动、重命名或翻译页面后运行
  `python -m unittest tests.contracts.docs.test_docs tests.contracts.docs.test_docs_bilingual -v`；测试检查状态标记、
  链接、可达性、目录锚点和双语一致性。测试分层和按层运行命令见
  [tests/README.zh-CN.md](tests/README.zh-CN.md)。
- 运行 `npx --yes markdownlint-cli2@0.24.0` 检查标题/列表/空行和链接片段一致性。
  CI 在 `docs` job 中运行同一命令。

结构参考 [Diátaxis](https://diataxis.fr/)、[markdownlint](https://github.com/DavidAnson/markdownlint)
和 [Lychee](https://github.com/lycheeverse/lychee)，以及
[markdown-viewer/skills](https://github.com/markdown-viewer/skills) 与
[beautify-github-readme](https://github.com/oil-oil/beautify-github-readme) 的
读者路由和视觉一致性思路。没有复制第三方正文或资产。
