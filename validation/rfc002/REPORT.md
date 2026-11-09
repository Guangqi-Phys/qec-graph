# RFC-QEC-002 / 0.4.0rc1 验收

这是 `71c7904` 的历史验收记录，环境为 macOS arm64 / Python 3.15.2，
日期为 2026-11-09。包说明曾与后续源码 README 不一致。当前包检查记录见[审阅整改](../../docs/AUDIT_REMEDIATION.md)。
工作区、原包、渲染结果和 wheel/sdist 都在本地验证；Git 只归档测试证据和源码。

| 门禁 | 实际结果 |
|---|---|
| `.venv/bin/python tools/reproduce.py --out build/rfc002-final-reproduce` | 退出 0；116 项测试通过，无跳过。三图、来源坐标、JSON Schema、有限 HGP 与现有 Lean 回归在运行范围内 |
| `tools/reproduce_incremental.py`、`tools/reproduce_mcp.py` | 中途回归实测退出 0；旧增量/恢复回放通过，旧固定作用域 MCP client 22 项检查通过 |
| `uv build --offline --no-build-isolation` | 用本机缓存的 setuptools 84.0.0 构建 sdist 并由其生成 wheel；两份文件见[哈希清单](distributions.json) |
| 全新 venv 离线安装 wheel，运行 `tools/reproduce_workspace.py` | [20 步实测](installed.json)通过：源码目录外 init、sync、全归档 rebuild、validate、真实 stdio 工具/资源、迁移和历史回查 |
| `tools/reproduce_isolation.py` | [实测通过](isolation-macos.json)；系统级拒绝读/列测试笔记、列收件箱、写机器库、网络绑定，同时真实 MCP 可查 |
| `docker compose -f compose.mcp-isolated.yaml config` | 配置解析通过；本机 daemon 未运行，未启动容器、未实测 Linux |
| `qec-graph software refresh --project-id software:stim` | [观察成功](stim-refresh.json)：仅公开仓库元数据；未安装或基准测试目录项目 |

真实来源是 [Aly、Klappenecker、Sarvepalli 的 *Subsystem Codes* v1](https://arxiv.org/abs/quant-ph/0610153v1)。
源包通过 [arXiv](https://arxiv.org/src/quant-ph/0610153v1) 本地取得，SHA-256 和入口见安装报告。
回归分别核对一处子系统参数、一处经典 parent BCH 参数与正文 K/R 语义；
未将源包或完整论文正文提交。双输入安装回放中生成 98 条记法提议和 174 张生成页；
页数包含软件和分类索引，提议数量不代表人工正确率或数学证明。

| F5 范围 | 已实测与限制 |
|---|---|
| A01–A02、A04–A11 | 合法包/部分批次、两种去重身份、显式版本冲突、多入口、危险路径和资源限额、全归档重建、写锁、失败来源可见。未测试所有文件系统或压缩工具组合 |
| A03 | 注入候选验证失败和 pointer 后、清理前故障，原包与认领保留且可重试；不是所有进程中止窗口或掉电的验证 |
| D01–D08、D10–D14 | 分离提议、精确修订、上下界、Pauli 重量、公式缺种子、噪声未知、深度口径、选点和软件语义有定向测试；真实论文只校对上述记法案例。模型、硬件、计算与运行字段仍需显式记录或 provider 提议，未声称已自动补齐 |
| D09 | 没有图像数字化或插值；无数值证据时不制造数值。未完成通用论文表格/多曲线抽取验收 |
| M01–M04 | 实际 stdio、固定 release、来源哈希、候选/历史/合成记录隔离、URL 编码与符号链接绕行，以及 macOS 系统隔离负例 |
| H01–H03 | 生成页/稳定链接、notes 字节不变、逐页发布中断后重建；未执行 Obsidian GUI 开启回放 |
| P01–P02 | macOS 源码目录外安装；从实际 0.3.0 CLI 建库及审核，到新工作区迁移、重建和历史回查。未实测 Linux 安装 |

没有连接外部 LLM 或验证其领域抽取准确率。未执行 Docker、批量真实论文 golden 集、真实 LER 复现、
数学距离或新的独立 Lean 发行门禁；这些结果不能从已通过的结构、绑定和查询测试推断。
