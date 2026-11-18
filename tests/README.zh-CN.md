# 测试布局

> **中文** · [English](README.md)

测试使用标准库 `unittest`，不需要额外测试依赖。目录分为三层，每层内部再按功能
分组。

```text
tests/
├── unit/          # 纯解析、图/领域规则、Schema 检查
├── integration/   # store、workspace、corpus、MCP、CLI、渲染
├── contracts/     # 文档、分发包、架构和工具契约
├── fixtures/      # 共享输入 fixtures
├── golden/        # 固定 arXiv manifest 和说明
└── support.py     # 共享 root/fixture 路径
```

| 层级 | 功能组 | 文件 | 重点 |
|---|---|---|---|
| Unit | 解析 | `unit/parsing/` | TeX、归档安全、来源坐标与准备语法 |
| Unit | 领域和 AI | `unit/domain/` | 研究证据、schema、provider 与提取行为 |
| Unit | 搜索与输出 | `unit/query/`、`unit/rendering/` | 词项排序、进度和输出 |
| Integration | 流水线 | `integration/pipeline/` | 快照发布、真实编译、沙箱、材料与冻结材料提取 |
| Integration | 工作区 | `integration/workspace/` | 注册表、归档导入、恢复、知识、检索、查询和状态 |
| Integration | MCP、CLI 与渲染 | `integration/mcp/`、`integration/cli/`、`integration/rendering/` | 只读 stdio、已安装命令与 Obsidian 笔记 |
| Contract | 文档 | `contracts/docs/test_docs.py`、`contracts/docs/test_docs_bilingual.py` | 状态/目录/链接契约和中英一致性 |
| Contract | 分发包 | `contracts/packaging/test_distribution.py`、`contracts/packaging/test_installer.py` | 元数据、安装器、分发包 |
| Contract | 架构/工具 | `contracts/tooling/test_architecture.py`、`contracts/tooling/test_tools.py` | 导入边界/公共 API 和所有 `tools/*.py --help` 路径 |

按层运行：

```sh
python -m unittest discover -s tests/unit
python -m unittest discover -s tests/integration
python -m unittest discover -s tests/contracts
```

运行全部：

```sh
python -m unittest discover -s tests
```

fixtures 在 `tests/fixtures/`；固定来源说明在 `tests/golden/README.zh-CN.md`。

真实 TeX 集成测试需要在本地显式开启。安装 TeX Live、Ghostscript、Poppler 和平台沙箱后运行：

```sh
QECGRAPH_TEST_TEX=1 python -m unittest tests.integration.pipeline.test_compilation_sandbox tests.integration.pipeline.test_compilation -v
```

默认发现也会在支持的平台执行独立沙箱探针。开启真实编译的 CI 作业要求沙箱可用。

## 参考

布局参考高星测试项目的分层思路：
[Superpowers test-driven-development](https://github.com/obra/superpowers/tree/main/skills/test-driven-development)
（约 315k stars；RED-GREEN-REFACTOR 和先证据后完成）、
[JavaScript testing best practices](https://github.com/goldbergyoni/javascript-testing-best-practices)
（约 24.6k；unit/component/integration/e2e 分离）和
[pytest 仓库](https://github.com/pytest-dev/pytest)（约 14.7k；聚焦测试包和独立测试树）。
项目继续使用标准库 `unittest`，这些只是结构参考，不增加依赖。
