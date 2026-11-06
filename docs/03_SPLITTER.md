# LaTeX 文件切割工具：已经实现的 API 与命令

本包的切割功能调用同一套 `parser → graph → store` 流程。它读取一个 LaTeX 工程，将章节、定义、引理、定理、证明、公式、表格、图片和正文段落保存为带来源的文件，并返回每类文件的数量和准确路径。

实际切割结果就是快照中的 `nodes/<kind>/*.tex` 及对应 `.json`。工具没有第二套独立解析器，也不再额外复制一份失去来源的片段目录。原文文件始终保存在同一快照的 `sources/` 中。

## 1. 安装和命令入口

要求 Python 3.11+，依赖固定为 `pylatexenc==2.10`。在项目根目录安装：

```bash
python3 -m pip install -e .
```

包名为 `qec-graph`，版本为 `0.2.0`。安装后提供三个命令：

| 命令 | 用途 |
|---|---|
| `qecgraph` | 完整命令入口，包含 split、ingest、search、show、deps、impact、context、validate |
| `qec-graph` | `qecgraph` 的同义入口 |
| `qec-latex-split` | 专用于切割；参数等同于 `qecgraph split` |

用附带的多文件 QEC 示例运行：

```bash
qecgraph split examples/paper/main.tex \
  --project-id qec-demo \
  --out work/qec-demo
```

完全等价的切割入口是：

```bash
qec-latex-split examples/paper/main.tex \
  --project-id qec-demo \
  --out work/qec-demo
```

在已经安装依赖的源代码目录中，也可以使用模块入口：

```bash
python3 -m qecgraph split examples/paper/main.tex \
  --project-id qec-demo \
  --out work/qec-demo

python3 -m qecgraph.splitter examples/paper/main.tex \
  --project-id qec-demo \
  --out work/qec-demo
```

`--project-id` 是你为这份文献工程选择的稳定命名空间。`--out` 应指向一个新目录、空目录或已有的本工具存储目录。切割入口会拒绝向未识别的非空目录写入，避免接管其他工具或人工文件所在的目录。

可选参数：

| 参数 | 含义 |
|---|---|
| `--project-root DIR` | 限定工程文件的根目录；默认使用入口文件所在目录 |
| `--config FILE` | JSON 格式的解析器配置，例如自定义环境映射 |
| `--strict` | 部分抽取放入 staging，不更新 CURRENT；退出码仍为 2 |

`split` 是 source-only 操作，不接收 `--annotations` 或 `--catalog`。需要合并人工注释和既有数据记录时，使用完整的 `ingest` 命令。

## 2. 输出文件在哪里？

命令向 stdout 返回 JSON。以运行结果里的 `snapshot` 为基准，可以直接找到：

| 相对快照的路径 | 内容 |
|---|---|
| `sources/` | 保留原始字节的 UTF-8 LaTeX 源文件，维持原有相对路径 |
| `assets/` | 来源中明确引用、且成功解析到的图片和书目等资源 |
| `nodes/definition/` | 定义的 `.tex` 片段与 `.json` 记录 |
| `nodes/lemma/` | 引理片段与记录 |
| `nodes/theorem/` | 定理片段与记录 |
| `nodes/proof/` | 证明片段与记录 |
| `nodes/equation/` | 公式片段与记录 |
| `nodes/table/`、`nodes/figure/` | 表格和图片环境片段与记录 |
| `nodes/section/`、`nodes/paragraph/` 等 | 其他已识别的语义块 |
| `graph.json`、`graph.sqlite` | 同一套完整图和可查询投影 |
| `sourcegraph.json`、`datagraph.json`、`lemmagraph.json` | 从完整图生成的三种视图 |
| `report.json` | 诊断、计数和待审核关系 |
| `manifest.json` | 输入指纹、输出清单和文件哈希 |

结果 JSON 的关键字段是：

```text
snapshot                         准确的不可变快照目录
snapshot_id                      来源、配置和工具版本所确定的指纹
extraction_status                完整处理受支持语法，或 partial
fragment_count                   所有实际 .tex 片段的总数
fragments_by_kind.<kind>.count    某类片段的数量
fragments_by_kind.<kind>.directory
                                 该类片段目录的绝对路径
fragments_by_kind.<kind>.fragments[]
                                 每个片段的 ID、标签、标题和文件路径
sources[]                        原文件相对路径、SHA-256 和归档路径
paths                            各种图、数据库、报告和清单的准确路径
diagnostics                      未展开结构、缺失文件等处理信息
suggested_exit_code              API 使用者可采用的退出码
```

每个 `fragments[]` 项包含：

- `tex_file`、`record_file`：当前机器上可以直接打开的绝对路径。
- `fragment_path`、`record_path`：相对 `snapshot` 的可移植路径。
- `source`：原文件路径、原文件哈希、字符区间和行号。
- `content_sha256`：该片段内容的哈希。

不要猜测文件名。片段文件名由节点 ID 确定；根据结果 JSON、标签查询或节点记录定位即可。

## 3. Python API

```python
from qecgraph import split_project

result = split_project(
    entry="examples/paper/main.tex",
    project_id="qec-demo",
    out="work/qec-demo",
)

print(result["snapshot"])
for kind, category in result["fragments_by_kind"].items():
    print(kind, category["count"], category["directory"])
    for fragment in category["fragments"]:
        print(fragment["labels"], fragment["tex_file"])

if result["extraction_status"] == "partial":
    # 已保存能可靠抽取的部分；检查诊断后再决定如何处理。
    print(result["diagnostics"])
```

函数签名为：

```python
split_project(
    entry,
    project_id,
    out,
    project_root=None,
    config_path=None,
) -> dict
```

返回对象可以直接 `json.dumps(...)`。出现致命路径、配置或写入问题时，API 抛出异常；出现可记录的源解析问题时，API 可以返回一个 `partial` 快照。

## 4. 自定义 LaTeX 环境

工具会识别常见 `\newtheorem` 声明。也可以明确提供映射，例如 `parser.json`：

```json
{
  "environment_map": {
    "result": "theorem",
    "claim": "lemma",
    "dfn": "definition"
  }
}
```

然后运行：

```bash
qecgraph split path/to/main.tex \
  --project-id my-paper \
  --project-root path/to \
  --config parser.json \
  --out work/my-paper
```

这种映射说明“该源环境应进入哪类目录”，不会证明其数学内容。仅从表格中读到 `n=13,k=1,d=3`，也不会自动生成已验证的码实例。

## 5. 切完后直接查询图

切割已经生成标准图存储，无须再导入一次：

```bash
qecgraph show lem:css-commutation --store work/qec-demo
qecgraph deps thm:hgp-css --store work/qec-demo
qecgraph context thm:hgp-length --store work/qec-demo
qecgraph validate --store work/qec-demo
```

普通 `ref` 保持为引用关系；`uses` 是作者声明的依赖；仅由邻近位置推断的 proof 关联保持为候选；`leanok` 保持为作者标注。文件切割不会提升这些关系的证据等级。

## 6. 片段的准确含义

这是按语义结构抽取源码块：

- 一个 theorem 片段可以包含 equation 环境，同时该 equation 也拥有自己的片段。
- 片段因而可以嵌套、重叠；将所有 `.tex` 文件依次拼接会重复内容。
- 章节节点保存章节标题及其相邻标签，并通过结构边关联章节内容；跨文件章节不伪造连续源码区间。
- 片段可能依赖原文导言区的宏、包和上下文，不能保证单独编译。
- 还原已读取的 `.tex` 文件时使用 `sources/`；片段用于定位、检索、审核和构建 AI 上下文。

当前快照不自动收集未读取的 `.tex`、本地 `.sty/.cls`、动态宏生成的输入或未解析的资源。它不是任意 LaTeX 工程的完整编译归档。请另外保留完整原始工程；已归档的 `sources/` 和 `assets/` 足以核查本次实际抽取的内容，但不保证重建原 PDF。

源码字符位置按 UTF-8 解码后的 Unicode codepoint 计数，区间是 `[char_start, char_end)`；行号从 1 开始。文件 SHA-256 对原始 bytes 计算，保留 CRLF 等原始细节。

解析器不运行 TeX 或 Lean，不展开任意用户宏，不计算条件分支。重复 include、循环 include、缺失资源和不支持的配置会进入诊断。完整状态 `complete_for_supported_syntax` 只说明受支持的语法处理完成。

## 7. 快照、重复运行和退出码

相同项目 ID、源文件、配置、依赖版本及工具源码，在同一存储中重复运行，会复用同一个快照。原文件和已有快照片段保持不变；输入或工具版本变化会形成新快照。

`CURRENT.json` 指向当前快照。`split` 会把它指向 source-only 结果。如果已经开始维护 annotations/catalog，后续日常更新应使用 `ingest` 并继续传入这些输入；历史快照仍然保留。

| 退出码 | 含义 |
|---|---|
| `0` | 成功生成或复用受支持语法的完整快照；仍可能有 warning |
| `1` | 路径、配置、输出目录或其他无法完成的运行错误；stderr 给出错误 JSON |
| `2` | 已保存 partial 快照，stdout 中有结果和诊断，应检查 `extraction_status` |

参数用法错误也遵循 argparse 的惯例退出 `2`，此时 stderr 显示 usage，不产生 split-result JSON。自动化调用可据 stdout 是否有结果及 `extraction_status` 区分这两种情况。

partial 的含义是已经保存可用部分，并不表示回滚。例如，一个引理被正确抽取，但后面的 `input` 文件缺失时，输出仍包含该引理和准确的原文，同时明确记录缺失文件。

本地编辑应修改原文或人工标注，再生成新快照。直接修改快照中的片段会使后续哈希校验失败。

## 8. 本次实现的验证

新增的 `tests/test_splitter.py` 含 8 项集成测试，已实际通过。覆盖真实分类片段、原文字节与片段哈希、现有图查询复用、重复导入幂等、外部目录保护、partial 退出码、两个入口结果一致及环境配置转交。

只运行这一组检查：

```bash
python3 -m unittest discover -s tests -p test_splitter.py -v
```

这些检查验证文件、来源和接口行为，没有执行数学证明、数值码距验证、LaTeX 编译或 Lean 构建。
