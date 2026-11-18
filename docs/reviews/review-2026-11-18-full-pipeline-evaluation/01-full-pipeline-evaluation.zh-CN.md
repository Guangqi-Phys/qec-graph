# QEC-Graph 全流程实现评估报告

日期：2026-11-18
评估对象：`1c800aa`（2026-11-18 11:32:56 +0800），版本 `0.6.4`
评估环境：macOS 27.2.1 arm64；项目 `.venv` Python 3.15.2 / SQLite 3.54.1 /
`pylatexenc 2.10` / `jsonschema 4.26.0`；系统 Python 3.12.2；TeX Live 2026
评估方式：测试套件、静态检查、端到端复现、真实 arXiv 包、故障注入和只读代码/契约审计
报告性质：AI 编码代理独立评估，不是人工评审，不是形式化验证，也不代表维护者结论

> **作者：DeepSeek Harness 编码代理（root agent `lead`，模型 `deepseek-flash`）。**
> 本报告由我撰写；所有实测均在本次会话中重新执行，未修改项目源码、测试或既有
> review 文件。评估过程另外使用了两个只读子审计（测试质量、代码冗余）作为交叉
> 检查，关键结论均由我复核。

## 0. 结论摘要

**整体判断：核心工作区全流程可以跑通，但“完整验收”证据仍不足。**
不是“不可用”；也不是“全部通过”。最合适的表述是：**核心功能有条件通过，
测试门禁和文档一致性未通过完整验收。**

| 维度 | 结论 | 一句话依据 |
|---|---|---|
| 端到端主流程 | **通过（PASS）** | `init → sync → archive → parse → validate → publish → query → human → rebuild` 在真实 arXiv 包上跑通 |
| 测试套件 | **部分通过（PARTIAL）** | 582 项收集，568 项执行通过、14 项跳过；存在 2 项静默漏收集和 1 个死测试方法 |
| 真实 TeX 路径 | **本环境未验证（NOT RUN）** | 12 项 `QECGRAPH_TEST_TEX=1` 测试因外层沙箱禁止嵌套 `sandbox-exec` 而失败，非产品回归 |
| 核心查询/MCP | **通过（PASS）** | 8 个 research tools、真实 stdio、资源读取、路径/SQL 拒绝、私有内容隔离均通过 |
| 材料准备/离线提取 | **读取端通过；重编译未验证** | 复检 v20 bundle：source fidelity 通过，提取 2,531 / 1,034 units；未重新编译 |
| 代码冗余/复杂度 | **中等风险（PARTIAL）** | 无整函数复制粘贴，但有死代码、重复扫描器骨架、双查询栈和 78 个超复杂度函数 |
| 文档/契约一致性 | **未通过（FAIL）** | 多处“Current design”仍描述已删除的 `watch`、`corpus.py`、`review apply` 和旧 CI |
| 安全/隔离 | **受测路径通过；边界未完全验证** | 路径遍历、符号链接、锁、损坏 `CURRENT`、MCP 越权均实测拒绝；TeX 沙箱和 Linux 隔离未在本机执行 |
| 发布/容器 | **部分通过** | wheel/sdist 资源检查通过；`Dockerfile` 的入口命令与当前 console script 不一致，研究 Compose profile 会启动失败 |

**没有发现 P0 级缺陷**（没有观察到源码/数据被越权写出、发布指针被错误推进、
或已归档字节被改写）。**但存在 4 个应先处理的 P1 问题**：测试静默漏收集、真实
TeX 路径不在 CI、文档与实现漂移、Docker 入口错误。

## 1. 范围、基线与方法

### 1.1 评估范围

本报告覆盖仓库当前全部可执行表面：

- 源包输入、归档、解包、入口选择、解析、来源坐标和快照；
- 工作区（workspace）单写者事务、发布、校验、恢复、状态、查询；
- research records、证据/审核状态、查询语义；
- CLI、MCP、human/Obsidian 渲染；
- 材料准备（compile-first preparation）和冻结材料提取；
- AI 配置/提议路径（不调用真实模型）；
- 打包、容器、文档和测试契约。

不覆盖：论文数学正确性、Lean 证明、PDF/OCR、通用距离求解、真实 LLM 答案质量。
这些属于 DESIGN §16.8 的“科学可用性”，本报告不作肯定结论。

### 1.2 基线

| 项 | 值 |
|---|---|
| 提交 | `1c800aafd7a5baffcb3adfddb461a0c9dca65ef4` |
| 提交时间 | 2026-11-18 11:32:56 +0800 |
| 包版本 | `0.6.4`（`qecgraph/__init__.py`、`pyproject.toml`、CHANGELOG 一致） |
| 测试入口 | `python -m unittest discover -s tests -v` |
| 端到端入口 | `python tools/reproduce.py --out build/reproduce` |
| 本报告证据目录 | `build/eval-2026-11-18/`（本地生成，未纳入版本控制） |
| 工作树状态 | 仅有一个评估前已存在的未跟踪 review 文件；本次未改源码/测试/既有 review |

### 1.3 方法

采用五轴 code-review 思路（correctness、tests、security、maintainability、
documentation），并叠加本仓库 DESIGN §12 的不变量和失败案例作为项目专属检查。
参考的公开 skill 只提供评审框架，不覆盖本项目规范；项目规范仍以
`docs/design/DESIGN.md` 和 `AGENTS.md` 为准。

实际执行分四层：

1. **静态**：Ruff、mypy、pyright、复杂度门禁、AST 引用/重复扫描；
2. **测试**：默认套件、带 TeX 的套件、覆盖率、收集完整性检查；
3. **端到端**：仓库自带 `reproduce`、真实 arXiv 包、MCP stdio、prepared bundle；
4. **故障注入**：错误 `CURRENT`、写锁占用、恶意 tar、非法输入、无结果查询、
   quarantine/restore、重复导入。

“通过”表示我实际执行并得到预期结果；“未执行”会明确标注，不用测试套件的
存在来代替执行证据。

## 2. 全流程实测结果

### 2.1 主流程逐步结果

| 阶段 | 实测 | 结果 | 证据 |
|---|---|---|---|
| `init` | 空目录初始化；非空目录拒绝且不写入 | 通过 | 非空目录退出 1，目录只保留原 `README.txt`，未创建 `inputs/` |
| 输入/claim | 真实 gzip TeX、tar.gz、非法 zip、恶意 tar | 通过 | 合法包被消费；非法包保留；恶意 tar 返回 `unsafe_archive`，未逃逸到 `/tmp` |
| archive | 原字节 SHA-256、receipt | 通过 | `0903.0566v1` 的 `256ea08a…` 与本地 manifest 完全一致 |
| unpack/入口 | 单文件 gzip、多文件 tar | 通过 | 分别选择 `main.tex`、`arXiv_v2.tex`；生成 `sources/<tree-hash>/` |
| parser/坐标 | 真实定理块与归档源切片 | 通过 | `show` 返回的 span 截取与 `latex` 字段逐字节一致；文件 SHA-256 一致 |
| 发布/validate | 真实 workspace | 通过 | `validate.valid=true`、`issues=[]`、release 与 `CURRENT` 一致 |
| 查询 | `search`、`show`、`context`、`deps`、`impact` | 通过 | 真实论文 `search LDPC` 20 条命中；`show`/`context`/`deps`/`impact` 均返回固定 scope |
| human | 0903 与 2308 两篇真实论文 | 通过 | 生成 `human/2009/01/…`、`human/2023/08/…`；front matter 顺序正确 |
| rebuild | 真实 workspace | 通过 | 返回 `unchanged`，release 与之前完全相同 |
| MCP | 真实 stdio + 资源读取 | 通过 | `initialize`、`tools/list`、`tools/call`、`resources/list/read` 全部通过 |
| research-import | 11 条 synthetic records | 通过 | 首次 `imported`，再次 `unchanged`；随后 `validate.valid=true` |
| prepared extraction | 复检既有 v20 bundle | 通过（读取端） | `prepare_compiled.py --check` 返回 `source_fidelity=true`；提取 2,531 / 1,034 units |
| 分发资源 | wheel/sdist | 通过（静态） | `check_distribution.py` 验证 README、schema、skills、catalog seed 一致 |

### 2.2 真实论文实测

使用 `test-sources/arxiv-sources/` 中未改动的原始包：

| 论文 | 包类型 | 归档 SHA-256 | 结果 |
|---|---|---|---|
| `0903.0566v1` | `.tex.gz`，单文件 | `256ea08a5d91cc3bc50fc14a271e77e337e2345a50a7b50f6568d48450a0ca65` | 发布 1 篇，`main.tex`，1 个 code mention；human 生成于 `2009/01`；搜索 20 条 |
| `2308.07915v2` | `.tar.gz`，多文件 | `d0dc3ffbb467a71630efa6b930913d19ee3d5356c42412930bc43dbd96306b2e` | 发布 1 篇，入口 `arXiv_v2.tex`，49 个 code mention；human 生成于 `2023/08`；搜索 20 条 |

关键细节：

- 两篇均不是“合成小型 fixture”，而是真实 arXiv 源包；`validate` 均为真。
- `0903.0566v1` 的 `show` 节点 `th:main`：span 为 `main.tex` 字符 8526–9034，
  归档源切片与 `latex` 字段完全相同（508 字符），证明 G01 在真实包上成立。
- human note 的 YAML 顺序为 `tags`、`link`、`title`、`author`；作者保留全名；
  2308 的标签来自标题中的 “fault-tolerant”，不是随意生成的。
- `0903` 的 upstream version 为 `null`、`arxiv_id` 为 `null`，而 human 目录仍按
  包名 `0903` 得到 `2009/01`。这与 DESIGN §9 的“包名只用于年月，不建立论文身份”
  一致，不应误报为版本识别失败。

### 2.3 冻结材料的检查与提取

没有重新编译（本环境不能嵌套 `sandbox-exec`），而是对上一轮保留的两个 v20
bundle 做**当前读取端**的只读复检和提取：

```text
build/repository-cleanup/compile-harvmac
  check: source_fidelity true, nodes 8391, ready_for_extraction true
  extract: status ready, units 2531, checked true
build/repository-cleanup/compile-0903.0566
  check: source_fidelity true, nodes 4092, ready_for_extraction true
  extract: status ready, units 1034
```

这验证了“v20 材料 → source-bound extraction”的读取路径，但**不验证本提交重新
编译产生同样材料**。后者属于未执行项。

### 2.4 失败路径与安全边界

| 场景 | 预期 | 实测 |
|---|---|---|
| 非空目录 `init` | 拒绝，不写入 | 退出 1；只保留原有文件 |
| 坏包 + 好包同批 | partial batch；好包发布，坏包保留 | 退出 2；`processing_completed` 1 个；坏包仍是 `unsupported_format` |
| 恶意 tar（`../../../../tmp/...` + 符号链接） | 拒绝且不物化 | `unsafe_archive`；`/tmp/qecgraph-escape-eval.txt` 不存在 |
| quarantine/restore | 保留字节，可恢复，不删用户文件 | 成功；状态可查询 |
| writer lock 被占用 | 退出 5，指出精确路径 | 退出 5，`Another writer holds .../.qecgraph` |
| 损坏 `CURRENT.json` | 退出 1，指出精确路径，不写入 | 退出 1，`CURRENT contains invalid JSON`，原文件未改 |
| 无结果 `show`/`context` | 退出 4，返回 scope | 退出 4，`NOT_FOUND`，scope 完整 |
| 无结果 `search` | 0 结果，不声称不存在 | 0 结果，`total_matches=0`，scope/coverage 存在；但没有显式 `absence_note` |
| MCP 传 `path`/`sql`/`file:///human/...` | 拒绝，不解释为查询 | 全部拒绝；私有 canary 未出现在响应中 |

### 2.5 实测汇总数字

```text
测试（默认，带评估用 PTY skip）：582 collected, 568 passed, 14 skipped, 0 failed
测试（原始，不 skip）：          582 collected, 568 passed, 2 errors, 12 skipped
测试（QECGRAPH_TEST_TEX=1）：    582 collected, 12 failed, 2 skipped（嵌套沙箱限制）

reproduce.py：                   passed
  split：4 files / 29 fragments / 36 nodes / 99 edges
  workspace sync + validate：    passed
  search：11 hits；context：16 nodes
  schema checks：                passed

覆盖率：84.58%（15,134 statements；6,386 branches；1,871 missed；1,092 partial）
Ruff：All checks passed
mypy：Success: no issues found in 124 source files
pyright：0 errors, 77 warnings
复杂度：78 legacy functions > 10，0 regressions
```

## 3. 测试评估

### 3.1 结构与数量

| 层 | 测试模块 | 收集用例 | 说明 |
|---|---:|---:|---|
| unit | 37 | 280 | 解析、domain、AI、rendering、query |
| integration | 26 | 267 | workspace、pipeline、MCP、CLI、human |
| contracts | 7 | 35 | docs、packaging、architecture、tools |
| **合计** | **70** | **582** | 87 个 `.py` 文件；约 2,561 个断言调用，约 4.4 个/用例 |

测试整体质量是本次评估中较好的部分：没有真实网络调用，provider/HTTP 都被 fake；
临时目录基本使用 context manager；有真实的 SIGKILL/发布恢复、锁冲突、损坏
`CURRENT`、重复标签、上界不满足下界、stale review、MCP 私有内容隔离等用例。
这些不是“只复述实现”的测试。

### 3.2 发现 T1：2 个测试从未被收集，另有 1 个死测试方法

**严重度：P1（测试完整性）。**

证据：

- `tests/unit/query/` 目录没有 `__init__.py`。`unittest discover` 不会递归进入
  非包目录，因此 `tests/unit/query/test_lexical.py` 的两个测试不在 582 项中。
  显式运行时它们是通过的：

  ```text
  python -m unittest tests.unit.query.test_lexical -v
  Ran 2 tests ... OK
  ```

- `tests/unit/parsing/test_assembly.py:444-457` 把一个测试方法放在
  `if __name__ == "__main__": unittest.main()` 之后，使它不再是类成员：

  ```python
  if __name__ == "__main__":
      unittest.main()

      def test_missing_preamble_include_is_a_dependency_not_content_loss(self):
          ...
  ```

  `hasattr(AssembleTests, 'test_missing_preamble_include_is_a_dependency_not_content_loss')`
  为 `False`，所以该用例永远不会执行。

静态 AST 统计得到 584 个类级测试方法，而 discovery 只收集 582 个；差值正好对应
两个 lexical 测试。`test_lexical.py` 检查的是 `LexicalIndex.rank` 的全词优先
和 `[[144,12,12]]` 的归一化，属于查询核心语义，不是可有可无的小测试。

**建议**：添加 `tests/unit/query/__init__.py`；把 `test_missing_preamble...`
移回 `AssembleTests`；增加一个“收集数不得低于预期”的收集守卫。

### 3.3 发现 T2：真实 TeX 测试不在 CI，且本环境无法复核

**严重度：P1（覆盖门禁）。**

12 个 `LocalCompilerTests` 由环境变量控制：

```python
@unittest.skipUnless(
    os.environ.get("QECGRAPH_TEST_TEX") == "1",
    "Set QECGRAPH_TEST_TEX=1 for isolated local TeX checks",
)
```

CI（`.github/workflows/ci.yml:44-51`）只运行普通 `unittest discover` 和
`tools/reproduce.py`，没有设置 `QECGRAPH_TEST_TEX`，因此这 12 个用例在 CI 中
全部是 skipped。它们覆盖的正是最敏感的编译、沙箱、PDF 文本、Harvmac、
bibliography 和 normalized TeX 路径。

我尝试在本机执行：

```text
QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest discover -s tests -v
Ran 582 tests ... FAILED (failures=12, skipped=2)
```

失败原因不是断言逻辑，而是 TeX 启动即退出 71：

```text
pdflatex --version -> exit 71
```

进一步复现：

```text
/usr/bin/sandbox-exec -f <profile> /Library/TeX/texbin/pdflatex --version
sandbox-exec: sandbox_apply: Operation not permitted
```

本会话运行在 DSH 的外层 macOS sandbox 中，内层 `sandbox-exec` 被拒绝；直接运行
`pdflatex --version` 是成功的（TeX Live 2026）。因此：

- **不能把这 12 个失败当作产品回归**；
- **也不能把上一轮“TeX 全通过”当作本环境的复核结果**；
- 事实是：本环境**未验证**真实 TeX 路径，CI 默认也**不验证**。

**建议**：单独增加一个带 TeX Live、允许 `sandbox-exec`/bubblewrap 的 CI job 或
release gate；`LocalCompilerTests` 在沙箱不可用时应给出明确 skip 原因，而不是
让 12 个错误看起来像代码失败。

### 3.4 发现 T3：PTY 测试无守卫，受限环境会让整套失败

**严重度：P2（可移植性）。**

`tests/integration/cli/test_progress.py:99` 直接调用 `pty.openpty()`。在本环境：

```text
OSError: out of pty devices
```

导致默认套件 2 个 error（`success` 和 `interrupt` 两个子测试）。这不是产品逻辑
失败，而是测试把“本机有可用 PTY”当成前提，且没有捕获 `OSError`/`ENOENT`。
同一测试还有固定 `time.sleep(0.35)` 的时序断言，在负载高时可能不稳定。

**建议**：捕获 PTY 不可用并 `skipTest`，或注入伪终端；减少固定 sleep，改为事件
同步。我在评估中使用了一个只位于 `build/eval-2026-11-18/shim/sitecustomize.py`
的临时 shim，让该测试跳过；**这个 shim 不在仓库、也不是产品修复**。

### 3.5 发现 T4：覆盖率整体过门，但关键模块明显偏低

**严重度：P2（风险集中）。**

当前 84.58% 高于 `fail_under = 80`，但低覆盖集中在对安全和语义最重要的地方：

| 模块 | 覆盖率 | 风险 |
|---|---:|---|
| `qecgraph/cli/commands/records.py` | 13.64% | `research-import`/software 记录 CLI 几乎没有自动化覆盖 |
| `qecgraph/preparation/sandbox.py` | 21.88% | TeX 沙箱是安全关键路径；默认套件不执行 |
| `qecgraph/preparation/harvmac_refs.py` | 48.86% | Harvmac 引用解析 |
| `qecgraph/validators/qec.py` | 48.89% | CSS/距离/实验校验的许多分支 |
| `qecgraph/preparation/projection.py` | 59.23% | 源投影和重编译证据 |
| `qecgraph/preparation/view_contract.py` | 67.18% | 视图契约 |
| `qecgraph/preparation/inputs.py` | 67.57% | 输入/旧 tar 修复 |

`records.py` 只有 48 个 statement，却只有 13.64% 覆盖；我手工验证了
`research-import`（11 条记录、重复导入 `unchanged`），但这正说明**该路径靠手工
而非回归测试**。`sandbox.py` 的低覆盖主要因为 TeX 测试在本环境未执行；即使换到
允许沙箱的环境，默认 CI 也不会覆盖它。

**建议**：为 `records.py`、`validators/qec.py`、`harvmac_refs.py` 增加定向测试；
对安全模块设 per-module 下限；CI 保存 coverage XML/日志作为工件，而不是只依赖
本地 `.coverage` 文件。

### 3.6 测试方面做得好的地方

- 源字节保真：`test_source_package.py`、`test_pipeline.py`、`test_splitter.py`
  覆盖 gzip/zip/tar、路径穿越、大小写碰撞、伪造 ZIP 计数、Unicode/CRLF span；
- 发布：`test_publication.py` 覆盖 staging、CURRENT 替换、锁目录、失败重试；
- 恢复：workspace 测试包含真实 SIGKILL 窗口、损坏 release、claim 清理；
- 语义：重复标签歧义、上界不满足下界、stale/unbound 排除、exact ID 要求；
- MCP：真实 stdio 子进程，校验 machine 树哈希不变、human/private 不可读；
- human：front matter、所有权、符号链接、`human_stale` 恢复；
- 数据：research/registry/graph/material schema 和伪造/重哈希拒绝；
- AI：proposed 状态、引用/逐字校验、缓存/语言拒绝、离线 provider；
- 没有用 `assertRaises(Exception)` 或真实网络调用来“凑覆盖率”。

## 4. 功能与语义评估

### 4.1 来源和身份

- `G01` 在真实包上抽检通过：span 截取与节点 `latex` 完全一致，文件哈希一致。
- 包名只进入 human 年月；`arxiv_id`/`upstream_version` 仍由已登记元数据或内容
  证据决定。`0903.0566v1` 在改名的输入上得到 `upstream_version=null`，这是
  设计允许的“文件名不建立身份”，不是 bug。
- 重复标签、歧义引用、missing target 的行为由测试覆盖；我没有在真实论文上
  人为制造重复标签做端到端验证（测试用例已覆盖）。

### 4.2 证据、审核与查询

- 默认查询排除 stale/unbound/unresolved；`show` 的 `audit_view=true`，
  `absence_note` 存在；这部分与 DESIGN §6/§8 基本一致。
- **缺口**：DESIGN §6 描述“review decision 对象 + 原子、幂等 `apply`”，但当前
  代码没有 `review_decision`/`apply` 实现；实际只有 annotation sidecar 的
  `review_status` 与 `core/graph.py:341-389` 的哈希绑定。`research-import` 可以
  发布 records，但不是 review decision 的应用。
- **缺口**：query 结果中的 `absence_note` 和 `audit_view` 主要由 MCP/legacy
  graph 层添加，CLI `search` 的空结果没有显式 absence note（只有 scope、
  `total_matches=0` 和 coverage）。测试也没有断言这些字段。
- **两套查询栈并存**：CLI 的 `search`/`deps`/`impact` 使用 legacy
  `qecgraph_*`（`WorkspaceGraph`），MCP 的 research profile 使用
  `qec_search`/`qec_trace`/`qec_fetch`。我在同一真实论文上比较：

  ```text
  CLI legacy search LDPC: 20 results（document/abstract/bib_entry 在前）
  query-tool qec_search:  5 results（paragraph/abstract 在前）
  ```

  这不是说两者哪个错，而是**同一工作区存在两种排序/命中语义，文档没有明确
  说明用户何时应期待哪一种**。如果保留兼容层，应在文档和测试中写清楚；否则
  应合并或明确废弃。

### 4.3 human 视图

- 两篇真实论文的笔记路径、front matter、作者、标题、tags 都符合 §9 的格式。
- 删除生成笔记后，`status` 仍报告 `human.status=current`，因为状态只比较
  `.qecgraph/human-published.json` 中的 rendered release，而不检查笔记文件是否
  实际存在。`human build` 能重新生成，但这使“current”不等同于“文件存在”。
  这是 **P3** 级语义问题；建议要么在 status/doctor 检查注册笔记路径，要么在
  文档中明确“current 表示发布记录一致，不表示 vault 未被手工改动”。

### 4.4 AI

`ai status` 显示 `configured=false`、`allow_source_upload=false`；`sync` 的 AI
阶段是 skipped（来源上传未启用）。我没有调用真实 provider，也没有上传任何论文。
因此本报告**不评估**模型抽取质量、schema 重试的真实网络行为或成本上限。
测试中的 fake provider 覆盖了 schema/语言/重试/引用校验；这属于机制验证，不是
科学质量验证。

## 5. 代码冗余与可维护性

### 5.1 规模

| 项 | 数量 |
|---|---:|
| `qecgraph` Python 模块 | 124 |
| `qecgraph` Python LOC | 22,866 |
| 全部 `qecgraph`+`tools`+`tests` LOC | 38,263（230 模块） |
| 顶层/全部函数（qecgraph） | 约 1,089 个函数、111 个类 |
| >600 行的模块 | 7 个 |
| C901 > 10 的函数 | 78 个（25 个 >20，7 个 >30，最大 53） |

最大模块：

```text
qecgraph/source/assembly.py      1515
qecgraph/workspace.py            1246
qecgraph/source/parser.py        1171
qecgraph/workspace_query.py       764
qecgraph/knowledge.py             743
qecgraph/store.py                 683
qecgraph/preparation/convert.py   618
```

### 5.2 无引用/死代码

我用“AST 定义 → 全仓库引用 → 无引用”三重检查确认以下内部对象没有调用点
（不把公开模块入口算入）：

| 对象 | 位置 | 备注 |
|---|---|---|
| `SourceLineIndex`（及 `_line_starts`） | `qecgraph/source/assembly.py:1476` | 无实例化 |
| `distance_issues` | `qecgraph/validators/qec.py:117` | 被 schema/其他校验取代；且语义与 schema 已分叉，**不要直接复活** |
| `record_fingerprint` | `qecgraph/domain/research.py:243` | 无调用 |
| `KINDS`, `REQUIRED` | `qecgraph/domain/research.py:15,18` | 无引用；保留前需确认外部 API |
| `_SECTION`, `_SECTION_NAMES` | `qecgraph/source/assembly.py:76,78` | 被 parser/structure 取代 |
| `_without_comments` | `qecgraph/preparation/convert.py:434` | 与 `citations.py:152` 逐字相同且无调用 |
| `Registry.validate`, `Registry.validate_source_snapshot` | `qecgraph/registry.py:209/181` | 无调用点 |
| `WorkspaceSession.material_records/projected_graph/source_projection/reading_blocks/_reading_by_source` | `qecgraph/workspace_query.py:101/109/121/392/384` | 会话内部无调用 |

总计约 16 个无引用单元、约 95 行。删除前需确认没有外部消费者；但这些至少说明
当前维护面比实际功能大。

### 5.3 重复模式

**没有发现整函数级的复制粘贴**（对 ≥4 条语句的函数体做归一化 AST 比较，没有
完全相同的函数体）。真正的问题是“近似重复”：

| 模式 | 证据 | 影响 |
|---|---|---|
| LaTeX 扫描器骨架 4 份 | `source/assembly.py:643/840/948/439`；嵌套 `walk` 与 `_scan` 结构高度相似 | escape、`\verb`、literal environment、条件分支的修复要同步 3–4 处 |
| JSON 编码器 5 份 | `store.py:38`、`core/transactions.py:97`、`preparation/artifacts.py:50`、`preparation/publication.py:58`、`tools/reproduce.py:34` | 缩进/排序/NaN 标志不同；产物哈希绑定字节，合并需先固定 golden bytes |
| SHA-256 直接调用约 40 处、字节 helper 2 个 | `core/graph.py:33`、`preparation/artifacts.py:46` 等 | 容易出现“字符串/字节/换行”不一致 |
| 路径守卫 6 份 | `core/fs.py`、`store.py`、`preparation/artifacts.py`、`source/package.py` 等 | 威胁模型不同，多数应保留；`publication.py` 的副本可合并 |
| 注释掩码 3 份 | `source/entry.py:28`（保偏移）、`preparation/citations.py:152`（移除）、`preparation/convert.py:434`（死代码） | 选错会破坏 source coordinates |
| 关系词汇 4 处 | `core/graph.py:20 KNOWN_RELATIONS`、`validators/__init__.py:20 ENDPOINTS`、`query.py:268 contextual`、DESIGN §4.4 | 已出现漂移：`normalizes_to` 在 ENDPOINTS/docs 中，但不在 `KNOWN_RELATIONS`；`maps_declaration` 等只在 query 中 |
| `STATEMENTS`/`MATHEMATICS` 两份 | `core/graph.py:16-17` 与 `validators/__init__.py:18-19` | 修改一处会导致图构建与校验不一致 |

注意：`normalizes_to` 目前不一定被实际发射；我的 fixture split 只产生 10 种
relation，且都在 `KNOWN_RELATIONS` 内。因此这是**潜在漂移**，不是当前已观测到的
错误输出。但它说明“canonical relation registry”并不真正单一。

### 5.4 复杂度与类型

- 78 个函数超过 C901 阈值；`workspace.py`、`assembly.py`、`store.py` 各有一个
  170 行左右的核心函数（`_ingest_locked` 176、`_scan` 165）。
- mypy 通过，但大量模块仍是 untyped body（日志中的 `annotation-unchecked`）；
  pyright 0 error / 77 warnings。
- 这不是“代码坏味道”式的泛泛评价：`_ingest_locked` 同时处理归档、发布、清理、
  恢复，`_scan` 同时处理条件分支、字面环境、注释和 scope；这类函数是故障注入
  最应该覆盖的地方，但覆盖率并不高。

### 5.5 兼容层

`workspace_query.py` 的 `qecgraph_*` 旧工具（5 个）仍被 CLI legacy 路径和测试
使用，但 README/文档只描述 `qec_*` research tools。它不是死代码（CLI 依赖），
但属于**未文档化的兼容表面**。要么明确标注为 legacy，要么把 CLI 切到 research
工具并删除兼容层。

## 6. 文档与契约一致性

这是本次评估中问题最集中的部分。文档测试（`tests/contracts/docs/test_docs.py`）
只检查状态标记、链接、命令可解析和双语文档结构；它**不检查“文档声称的模块/行为
是否存在”**，因此以下漂移全部通过。

| # | 位置 | 文档声称 | 当前实现 | 严重度 |
|---|---|---|---|---:|
| D1 | `docs/design/DESIGN.md:124-132` | 当前模块包括 `corpus.py`、`review.py`，`qecgraph/splitter.py`/`mcp_server.py` 是兼容 shim | 四个文件都不存在（`qecgraph/source/splitter.py` 是另一条路径） | P1 |
| D2 | `docs/design/DESIGN.md:727-732` | `watch` 是当前增量能力 | 没有 `watch` parser/handler；只有 `qecgraph/cli/__init__.py:53` 的死分支；`tests/integration/workspace/test_watch.py` 不存在 | P1 |
| D3 | `docs/design/DESIGN.md:920` | CI 只跑 unit-test 层 | CI 实际跑全量 `unittest discover`、coverage 和 `tools/reproduce.py`（`.github/workflows/ci.yml:48-51`） | P1 |
| D4 | `docs/design/DESIGN.md:687` | review decision 对象 + 原子/幂等 `apply` | 没有 `review_decision`/`apply` 实现；只有 annotation sidecar | P1 |
| D5 | `README.md:184`、`docs/design/DESIGN.md:205` | 27 kinds / 47 typed relations | schema 枚举为 28 / 48 个 relation field；差值正好是派生 `ai_extraction` 及其 `source_ref`。若有意排除派生 kind，文案应说明 | P2 |
| D6 | `docs/design/DESIGN.md:265` | canonical registry 是 `qecgraph.research.RELATIONS` | 实际模块是 `qecgraph.domain.research.RELATIONS`（且它是 field→target-kinds 映射，不是完整 relation 枚举） | P2 |
| D7 | `tests/README.md:24-26` | 列出 `test_registry.py`、`test_workspace_migration.py`、`test_watch.py`、`test_ai_tools.py` | 四个文件都不存在；同时表格没有列出多组新增测试 | P2 |
| D8 | `validation/README.md:76` | 称为 85 个 legacy complex functions | `check_complexity.py` 实际输出 78 | P3 |
| D9 | `Dockerfile:12` | `ENTRYPOINT ["qecgraph"]` | console scripts 只有 `qec-graph`、`qec-latex-split`、`qecgraph-mcp`；wheel 的 `entry_points.txt` 可证明 | P1 |

D9 是运行问题，不只是文档问题，见 §7.3。

另外：

- `tests/README.md` 把 `integration/pipeline/test_registry.py` 等列为当前文件，
  但 `test-sources/` 是 `.gitignore` 的，干净 clone 也没有 47 篇准备的
  `manifest.json`；DESIGN 中的完整 replay 命令无法在干净 clone 直接执行。
- `examples/annotations.example.json` 的 `title`/`data` 含中文；如果它只是
  “源语言示例”，应说明；如果它是用户模板，则与 AGENTS 的“metadata 用英文”
  约定冲突。当前没有运行时语言检查能区分这两者。
- `validation/README.md` 把 `preparation_acceptance.json` 称为 current 证据，
  但该报告的 `code_revision` 是 `cb37129`（早于当前 `1c800aa`），且
  `code_sha256` 包含已删除模块。它作为历史证据是合理的，但应在索引中明确
  “绑定旧 revision”，避免被读成当前提交的证据。

## 7. 安全、隔离与发布

### 7.1 已实测通过

- 归档路径穿越、tar 符号链接、伪造包：在物化前拒绝；我的恶意 tar 测试没有写出
  `/tmp` 目标文件。
- 写锁：非阻塞 `flock`；冲突退出 5，错误携带精确 `.qecgraph` 路径。
- `CURRENT` 损坏：退出 1，精确路径；不写新指针。
- MCP：工具参数不能传路径/SQL/shell；`file:///human/...` 资源被拒绝；
  私有内容不进入 machine 查询；`mcp serve` 的 stdout 只输出 JSON-RPC。
- human 所有者检查：测试覆盖 unowned vault、符号链接、历史文件清理；我的真实
  运行没有覆盖这些所有边界，但测试套件覆盖了。

### 7.2 未验证

- **TeX 沙箱**：本环境禁止嵌套 `sandbox-exec`，无法验证真实隔离。`sandbox.py`
  覆盖率只有 21.88%，默认 CI 也不跑。
- **Linux bubblewrap / Docker**：Docker daemon 未运行，未构建镜像或容器；Linux
  隔离测试未执行。
- **macOS 隔离 profile**：`deploy/mcp-macos.sb` 未在本机执行。
- **AI provider**：没有真实 key，没有网络请求；不评估模型行为。
- **大模型/真实论文科学质量**：不做数学或实验复现。

### 7.3 发现 D9：研究 Compose profile 的入口命令错误

`Dockerfile:12`：

```dockerfile
ENTRYPOINT ["qecgraph"]
CMD ["--help"]
```

`pyproject.toml:31-34` 只声明：

```text
qec-graph
qec-latex-split
qecgraph-mcp
```

我从现有 0.6.4 wheel 的 `entry_points.txt` 也确认没有 `qecgraph`。因此
`compose.yaml` 的 `research` service（未覆盖 entrypoint，只传
`command: ["split", ...]`）在容器启动时会报
`exec: "qecgraph": executable file not found`。`compose.mcp-isolated.yaml` 显式
覆盖了 entrypoint，所以不受影响；不能因此认为整个容器路径正常。

这是一个静态可证的发布缺陷。未运行 Docker 是因为 daemon 不可用；修复后应增加
一次容器 smoke test（`qec-graph --version` + `qec-graph split ...`）。

## 8. 问题清单与优先级

优先级定义：

- **P1**：会改变“是否完整验收”的结论，或直接破坏一个声明支持的工作流；
- **P2**：不阻塞核心流程，但会降低回归可信度或维护质量；
- **P3**：局部语义/文案/清理问题，可在后续迭代处理。

| ID | 优先级 | 问题 | 证据 | 建议 |
|---|---|---|---|---|
| T1 | P1 | 2 个 lexical 测试未收集；1 个测试方法在 `__main__` 后成为死代码 | `tests/unit/query/` 无 `__init__.py`；`test_assembly.py:444-457` | 加 `__init__.py`；移动方法；加收集数守卫 |
| T2 | P1 | 12 个真实 TeX 测试默认 skip；本环境 nested sandbox 无法执行 | `test_compilation.py:19-23`；`ci.yml` 未设 `QECGRAPH_TEST_TEX`；`sandbox_apply` 失败 | 单独 TeX CI/release gate；沙箱不可用时明确 skip |
| D1-D4 | P1 | DESIGN 仍描述已删除的 watch/corpus/review apply，且 CI 描述错误 | DESIGN 124-132、687、727-732、920 | 更新文档或实现；加“文档引用模块存在”契约测试 |
| D9 | P1 | Docker 研究 profile 入口 `qecgraph` 不存在 | `Dockerfile:12` vs `pyproject.toml:31-34` | 改为 `qec-graph`；容器 smoke test |
| T3 | P2 | PTY 测试无守卫，受限环境整套失败 | `test_progress.py:99`；本次 2 errors | 捕获 PTY 不可用并 skip；去掉固定 sleep |
| T4 | P2 | 覆盖率集中在安全/语义关键模块偏低 | 84.58% overall；records 13.64%、sandbox 21.88%、qec 48.89% | 定向测试 + per-module threshold + CI 工件 |
| S1 | P2 | review decision/apply 规格未实现 | DESIGN §6 无对应代码；annotation sidecar 是实际机制 | 实现或收窄文档；补 CLI 测试 |
| C1 | P2 | 死代码/重复扫描器/关系词汇漂移 | §5.2/§5.3；16 个无引用单元；`normalizes_to` 漂移 | 删除死内部代码；单一 relation registry；合并扫描器 |
| C2 | P2 | 78 个 C901 超阈值函数；7 个 >600 行模块 | `check_complexity.py`；assembly/workspace/store | 以故障注入测试为前导做增量拆分 |
| R1 | P2 | 完整 47 篇准备语料未纳入 git，干净 clone 无法复现 DESIGN 命令 | `.gitignore` 含 `test-sources/`；0 个 tracked 文件 | 提供 tracked manifest/downloader 或明确外部步骤 |
| H1 | P3 | 删除生成 human note 后 status 仍报 `current` | `workspace.py:1207-1211` 只读 renderer state | 检查注册文件存在性，或在文档中定义 current 语义 |
| X1 | P3 | 文档计数 27/47 vs schema 28/48；`qecgraph.research.RELATIONS` 路径错误 | README 184、DESIGN 205/265 | 从 schema 生成计数或说明排除项 |
| X2 | P3 | `tests/README.md` 文件清单过期 | 4 个列出的文件不存在 | 更新清单或改成自动生成 |
| X3 | P3 | `validation/README` 的 85 vs 实际 78；acceptance 绑定旧 revision | `check_complexity.py`；`preparation_acceptance.json` 的 `code_revision` | 更新文案；给历史报告加 revision 标签 |
| X4 | P3 | 示例注释元数据含中文 | `examples/annotations.example.json` | 确认是源语言示例还是模板；模板改为英文 |
| X5 | P3 | `graph.schema.json` 无运行时消费者，主要靠测试/复现工具校验 | `grep packaged_validator('graph')` 无结果 | 明确它是外部契约，或在 store 发布时校验 |
| X6 | P3 | `review-list` 仍在 `help.py`/`progress.py` 表中，但命令已退役 | `help.py:27`、`progress.py:19` | 删除残留表项 |
| X7 | P3 | `preparation/inputs.py` 用异常消息文本判断旧 tar 修复 | `inputs.py:39-41` 比较 `"Tar missing a valid zero-block trailer"` | 改用 `PackageError.status`/错误码 |

## 9. 建议的验收路径

### 阶段 A：先修复测试与发布门禁（建议 0.5–1 天）

1. 修复 T1，确认 `unittest discover` 收集数从 582 变为 585（2 个 lexical + 1 个
   移回类中的方法），并显式运行这 3 个被漏掉的用例；
2. 修复 T3，让无 PTY 环境 skip 而不是 error；
3. 修复 Dockerfile 入口，增加 `docker build` + `qec-graph --version` +
   `qec-graph split` smoke test（即使本机 daemon 不可用，也应进 CI）；
4. 在 CI 中增加一个 TeX job（允许 `sandbox-exec`/bwrap），设置
   `QECGRAPH_TEST_TEX=1`，把 12 个测试纳入门禁；若环境不满足，显式 skip 并
   记录原因。

### 阶段 B：修复文档/契约漂移（建议 0.5 天）

- 删除 DESIGN 中已删除模块、`watch`、未实现 review apply 的“current”表述，
  或实现相应功能；
- 修正 CI 描述、27/47 计数、`qecgraph.research.RELATIONS` 路径；
- 更新 `tests/README.md`，增加“文档引用模块/测试文件存在”的契约测试；
- 给 `validation/preparation_acceptance.json` 标注其绑定 revision，避免被当作
  当前提交证据。

### 阶段 C：维护性与证据（建议 1–2 天）

- 删除 16 个无引用内部单元，合并 assembly 的扫描器骨架（先补 golden bytes）；
- 统一 relation vocabulary（至少把 `KNOWN_RELATIONS`、`ENDPOINTS`、query
  contextual 三者用同一数据源生成）；
- 为 `records.py`、`validators/qec.py`、`harvmac_refs.py` 增加定向测试；
- 提供 47 篇准备语料的 tracked manifest 或下载脚本，使干净 clone 可复现
  DESIGN §5.4 的复核命令。

### “完整验收”的完成标准

我建议把完成标准写成可检查的布尔条件，而不是“感觉可用”：

- [ ] `unittest discover` 收集数 ≥ 585，且 3 个漏收集用例实际执行；
- [ ] CI 有 TeX job，12 个 `LocalCompilerTests` 实际 ok（不是 skip）；
- [ ] `Dockerfile` entrypoint 与 wheel console scripts 一致，容器 smoke test 通过；
- [ ] DESIGN 中每个“current”模块路径存在；`watch`/review apply 要么实现，
      要么从 current 文案删除；
- [ ] `tests/README.md` 中列出的路径全部存在；
- [ ] `records.py`、`sandbox.py` 覆盖率有明确阈值或定向测试；
- [ ] 在允许 TeX 沙箱的干净环境重跑 `QECGRAPH_TEST_TEX=1` 并保存日志；
- [ ] 47 篇语料或等价可获取清单可从干净 clone 重建；
- [ ] 本报告第 8 节的 P1 项全部关闭。

## 10. 未执行项与局限

以下项目在本环境中**没有执行**，不能据本报告声称通过：

- Docker 镜像构建/容器运行（daemon 不可用）；
- Linux bubblewrap 隔离和 `compose` 运行；
- macOS 隔离 profile 的实际 MCP 测试；
- 真实 TeX 编译、PDF 文本比较、Harvmac/bibliography 的 12 项测试
  （nested sandbox 拒绝）；
- 真实 AI provider、模型质量、成本上限、真实上传策略；
- 47 篇完整 preparation replay 的现场重跑（仅复检既有 bundle）；
- `tests/golden` 六篇 arXiv 源的完整下载/回放（本地只有其中一篇）；
- 真实的 50–100 题人工标注科学问答评估。

限制：

- 本次评估是 **AI 独立评估**，不是人工代码审查，也不是数学/形式化验证；
- 子审计用于发现候选问题，关键结论已由我复核，但未覆盖所有外部消费者；
- 覆盖率是单次运行结果，受跳过项和测试环境 shim 影响；我已明确区分默认、
  PTY-skip 和 TeX 三种运行；
- 所有 `build/eval-2026-11-18/` 证据是本地产物，未提交；命令见附录。

## 附录 A：实际执行命令与结果

```text
# 静态
python -m ruff check qecgraph tests tools
  -> All checks passed!
.venv/bin/python -m mypy
  -> Success: no issues found in 124 source files
.venv/bin/python -m pyright
  -> 0 errors, 77 warnings
python tools/check_complexity.py
  -> {"legacy_functions_over_10": 78, "regressions": {}}

# 测试（默认，原始）
.venv/bin/python -m unittest discover -s tests -v
  -> Ran 582 tests ... FAILED (errors=2, skipped=12)

# 测试（评估用 PTY skip shim，仓库外）
COVERAGE_FILE=build/eval-2026-11-18/.coverage-default \
  .venv/bin/python -m coverage run --branch --source=qecgraph \
  build/eval-2026-11-18/run_tests.py
  -> Ran 582 tests ... OK (skipped=14)
.venv/bin/python -m coverage report
  -> TOTAL 84.58%

# 真实 TeX 尝试
QECGRAPH_TEST_TEX=1 .venv/bin/python -m unittest discover -s tests -v
  -> Ran 582 tests ... FAILED (failures=12, skipped=2)
  -> 失败入口：sandbox-exec: sandbox_apply: Operation not permitted

# 端到端
.venv/bin/python tools/reproduce.py --out build/eval-2026-11-18/reproduce
  -> status passed; 582 tests; 4 files / 29 fragments / 36 nodes / 99 edges;
     search 11; context 16; schema checks passed

# 真实论文工作区（摘要）
.venv/bin/python -m qecgraph init --workspace build/eval-2026-11-18/ws-real --json
.venv/bin/python -m qecgraph sync   --workspace build/eval-2026-11-18/ws-real --json
.venv/bin/python -m qecgraph validate --workspace ... --json
.venv/bin/python -m qecgraph search LDPC --workspace ... --json
.venv/bin/python -m qecgraph show <theorem-id> --workspace ... --json
.venv/bin/python -m qecgraph context <theorem-id> --workspace ... --json
.venv/bin/python -m qecgraph rebuild --workspace ... --json
  -> sync published; validate true; search 20; show/context/deps/impact ok;
     rebuild unchanged

# MCP
.venv/bin/python tools/reproduce_mcp.py --out build/eval-2026-11-18/mcp
  -> passed, 7 checks
.venv/bin/python build/eval-2026-11-18/mcp_real.py
  -> 8 tools; fetch 209 chars; context 4 nodes/5 edges; path/SQL rejected

# 准备材料
.venv/bin/python tools/prepare_compiled.py --out ... --check
  -> source_fidelity true, 8391 nodes
.venv/bin/python tools/extract_prepared.py ... --out ... --check
  -> status ready, units 2531, checked true

# 分发
.venv/bin/python tools/check_distribution.py build/repository-cleanup/dist
  -> Verified 0.6.4, README, license, schemas, skills and catalog seed
```

## 附录 B：本报告使用的本地证据

```text
build/eval-2026-11-18/tests-default-coverage.log   默认套件 + PTY shim
build/eval-2026-11-18/tests-tex-coverage.log       TeX 尝试的 12 个失败
build/eval-2026-11-18/coverage-report.txt          84.58% 明细
build/eval-2026-11-18/ruff.log / mypy.log / pyright.log
build/eval-2026-11-18/complexity.log
build/eval-2026-11-18/reproduce/results.json
build/eval-2026-11-18/ws-real/                     0903.0566v1 真实工作区
build/eval-2026-11-18/ws-real2/                    2308.07915v2 真实工作区
build/eval-2026-11-18/ws-import/                   research-import 验证
build/eval-2026-11-18/ws-sec/                      恶意 tar 测试
build/eval-2026-11-18/mcp-real.log                 真实 MCP stdio
build/eval-2026-11-18/workspace-release.json       standalone workspace 20 项检查
build/eval-2026-11-18/prep-check-*.log              v20 bundle 复检
build/eval-2026-11-18/extracted-*.json              离线提取结果
```

## 附录 C：评估者声明

本报告由 DeepSeek Harness 编码代理（root agent `lead`，模型 `deepseek-flash`）
于 2026-11-18 撰写。评估对象为当时工作树的 `1c800aa`；报告没有修改源码、测试或
任何既有 review 文件。报告中的“通过”只针对本报告列出的命令和环境；未执行项
不会因为测试套件中存在同名用例而被视为通过。

如果后续维护者修复了本报告的问题，请在本文件之外新增 review 或回复记录，并
附上新的可执行证据；不要直接改写本报告来“消除”历史结论。
