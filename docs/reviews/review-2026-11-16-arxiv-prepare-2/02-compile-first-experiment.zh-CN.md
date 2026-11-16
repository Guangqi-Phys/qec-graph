# 原始 arXiv 工程先编译实验

日期：2026-11-16。范围：验证「原始工程 → 隔离编译 → 结构转换」能否作为准备层的前置步骤。本次没有修改生产 preparation/parser，也没有调用模型或执行科研语义抽取。

## 实测结论

同一批 47 个源代码包，清单 SHA-256 为
`153f4e78fc1546f8d6f5bd883e4c45f0a6967e6ca17ca712ffaa16b05d92a35b`。

| 检查 | 首轮 | 修正环境与调度后 | 含义 |
| --- | ---: | ---: | --- |
| 完整命令链退出成功且生成 PDF | 27/47 | 45/47 | 可以在当前本机环境编译；不代表内容、引用或数学正确性已验收 |
| 编译成功，且实际 AUX/BCF/BBL 的引用键通过机械检查 | 未使用首轮粗略值 | 40/47 | 已使用的引用键有相应绑定，无已检测到的未解析引用警告；不评参考文献字段准确性 |
| TeX4ht 生成 HTML，退出成功且转换日志无 ERROR/FATAL | 首轮仅检查文件和退出码 | 8/47 | 只证明转换工具基本运行成功；尚未验收全文、公式和来源映射 |

两个原始工程仍未在 TeX Live 2026 上成功编译：

- `1804.03719v1`：旧 `revtex4` 与当前 `array`/相关表格宏冲突；原始运行报 `Extra \or`。定向加载历史 array 后仍有宏兼容错误。
- `2103.02202v1`：包内旧 `quantumarticle.cls` 使用旧 LaTeX 内部钩子，结尾 `\@afterenddocumenthook` 不可用；日期回退试验仍存在内部宏兼容问题。

这两篇需要匹配历史 TeX 环境，不能据此判定原始论文无法编译。完整 TeX Live 2023/历史发行版尚未运行。arXiv 官方也记录了 TeX Live 更新导致的包兼容性问题及回退方案：
[TeX Live at arXiv](https://info.arxiv.org/help/faq/texlive.html)。

## 已验证的改进

- 按 `00README.json` 的编译器字段选择 pdfLaTeX/XeLaTeX 等；旧 DVI 工程走 LaTeX/eTeX → dvips → ps2pdf。
- 直接使用上传包内的 `.bbl`；需要重建时按实际 jobname 生成，不能把其他主文件的 `.bbl` 当成本工程产物。
- 内联文献表且没有 `\bibdata` 时，不因 REVTeX 的控制文件而盲目调用 BibTeX。
- 补充实验目录内的历史宏包，没有修改系统 TeX 安装或原始论文：BoxedEPS、doublespace、REVTeX 3.1。
- Harvmac 选择其交互布局选项后可以编译，无需 AI 重写论文。
- 修正沙箱中字体缓存目录的元数据权限；本机 Biber 的通用二进制通过已安装 lipo 提取 arm64 副本后，继续在受限目录中执行，避免其包装器尝试写入用户 xcrun 缓存。
- `quant-ph/0001106v1` 的 `\citeRef0` 等自定义宏由 TeX 自身展开，得到 5 个引用键和 5 个文献绑定。`2605.29137v1` 的 Biber 产物有 279 个请求键与 279 个绑定；`2607.00262v1` 有按 refsection 区分的 61 个键与 61 个绑定。

## 边界和未验收项

| 部分 | 本次执行内容 | 完成判据/限制 |
| --- | --- | --- |
| 解包 | 有界安全解包；两类历史 tar 尾记录单独记账；保留成员原始字节 | 每个原始包 SHA-256 与固定清单一致；没有应用前一轮 AI 规范化方案 |
| 入口 | 复用上一轮已经确认的路径 | 未评测自动入口发现；这些路径的历史确认可能使用过 AI，不能称整条链路已独立摆脱 AI |
| 编译 | 限时、受限写入、禁 TCP/IP 网络、禁用户目录数据访问；固定输入与工具调用 | 完整命令链成功并有 PDF；保留日志、AUX、BBL、BCF、FLS、SyncTeX 等 |
| 引用检查 | 只读取 FLS 记录的实际 AUX/BBL 输入；经典 AUX 键及 Biblatex 分节键分别检查 | 排除已声明的 BST 控制键；不同排序 datalist 的同一条目不误报重复；同列表内重复仍失败 |
| 结构转换 | TeX4ht 的 HTML/MathML 转换 | 8 篇只有基本工具成功，未做原文全文覆盖、公式保真、图表保真或精确来源坐标验收 |
| preparation | 本次未接入新的生产准备流程 | 编译产物仍是实验数据；现有 TeX parser 尚无这里的 HTML 适配器 |
| AI | 0 次调用 | 没有分类论文、提取科学内容、补写缺失文献或上传源代码 |

旧静态文献验收为 11/47；本次编译引用机械检查为 40/47，两者检查对象和判据不同，不能将其直接宣传为参考文献准确率从 11 提升到 40。

当前不能删除静态准备作为兼容路径，也不能仅凭有 PDF 宣告准备成功。要将先编译作为默认路线，还必须实现并验收「编译/转换产物 → 后续 parser 支持格式」的适配器，保留原始来源和映射，明确报出遗漏。无法编译时先解决入口、引擎、宏包、版本和缓存问题；无法转换时先判定转换工具的支持范围，不能直接把失败归因于需要 AI。

machine 固定 release
`aabc5ef397e0300bc085ea687c8beb2a12ea82080f7d0536cd609f661ff5fa22`
仍因注册表 schema 不兼容而未验收；此次实验没有修改原库，没有访问 human/私人笔记，也没有发布新 release。

## 复现与证据

实验脚本和全部运行日志位于本机 `build/compile-first/`（不作为生产工具发布）：

```sh
.venv/bin/python build/compile-first/probe.py --workers 3
.venv/bin/python build/compile-first/refined.py
.venv/bin/python build/compile-first/environment.py
.venv/bin/python build/compile-first/jobnames.py
.venv/bin/python build/compile-first/audit.py
```

这些编译命令在外层执行环境批准后启动 macOS sandbox-exec；每轮先验证范围内写入成功、范围外读取/写入失败、TCP/IP 连接被拒绝。脚本已存在结果时复用对应结果，不覆盖历史实验；改动试验条件需要使用新目录。

汇总：[audit.json](../../../build/compile-first/audit.json)。每篇记录含原始包哈希、入口、引擎、所选运行证据及编译产物哈希。原始首轮、改进调度、定向环境检查和 jobname 修正的结果分别保留，未执行完整历史 TeX 镜像、HTML 下游解析验收或科学内容金标验收。
