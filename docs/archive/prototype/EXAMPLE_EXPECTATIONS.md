> 历史参考：本文保留上一版原型说明。当前入口和规范见项目根目录 `START_HERE.md` 与编号文档；本次执行结果见 `validation/REPORT.md`。文中旧相对路径、版本和测试计数按历史语境理解。

> Historical. See the [current documentation index](../../README.md).

# LaTeX 演示工程的预期结果

入口是 `examples/paper/main.tex`。它依次输入 `sections/foundations.tex` 和 `sections/hgp.tex`，再给出一段 verbatim 文本。这个工程是结构解析测试资料；没有运行 TeX 或 Lean。SVG 图片作为资源引用示例，直接排版时需要选择支持该格式的工作流。

## 1. 应识别的结构

| 类型 | 有标签的对象 |
|---|---|
| Section | `sec:foundations`、`sec:hgp`、`sec:literal-examples` |
| Definition | `def:gf2`、`def:css` |
| Lemma | `lem:css-commutation` |
| Theorem | `thm:hgp-css`、`thm:hgp-length` |
| Proof | `proof:css-commutation`、`proof:hgp-css`、`proof:hgp-length` |
| Equation | `eq:css-commutation`、`eq:hgp-checks`、`eq:hgp-commutation`、`eq:repetition-seed` |
| Table | `tab:rep3` |
| Figure | `fig:repetition-seed` |
| Unnumbered remark | `rem:source-only` |
| Example | `ex:rep3-parameters` |

还包含一个无标签的 `equation*` 和若干说明段落。环境名称 `lem`、`thm` 与 `remarkstar` 来自 `newtheorem`；解析器应根据声明或环境映射识别它们。定理和 proof 的可选标题要完整保留。

## 2. 引用和依赖不能混为一类

以下关系是源文件明确给出的声明，导入后适合记录为 `depends_on_declared`：

- `def:css` 通过 `uses` 指向 `def:gf2`。
- `lem:css-commutation` 通过 `uses` 指向 `def:css` 与 `def:gf2`。
- `thm:hgp-css` 的陈述通过 `uses` 指向 `def:css`。
- `proof:hgp-css` 通过 `uses` 指向 `def:gf2` 与 `lem:css-commutation`。
- `proof:hgp-length` 通过 `uses` 指向 `thm:hgp-css`。

这些是作者声明的依赖，并非从 Lean 证明项中导出的实际依赖。

普通 `ref`、`eqref` 应先成为 `references`。例如，长度定理之后那段以 “For background and motivation” 开头的正文引用了 `thm:hgp-css`；该引用不应直接升级为证明依赖。proof 中出现普通引用也只能支持依赖候选，除非另有明确声明或审核。

数学陈述本身引用的定义和证明里使用的引理有不同角色。应分别保留原始边及其所在对象，不把 proof 的全部关系无条件搬到 theorem 上。

## 3. Proof 的关联

`proof:hgp-length` 与 `thm:hgp-length` 之间隔着正文、表格和图片，proof 内的 `proves` 明确指定目标。预期产生作者声明的 `proof_of` 关系，并保存其来源位置。

另外两个 proof 紧跟对应 lemma/theorem，但没有 `proves` 标记。仅依据相邻位置绑定时应使用 `proof_of_candidate`，不能伪装成经过人工确认的关系。可选标题中的文字或引用也不应悄悄升级为已验证的证明关联。

## 4. 标签所有权和源位置

`eq:css-commutation` 位于 `def:css` 内部，应归属最内层 equation 对象；不能同时作为 definition 的另一个主标签。类似地，`eq:hgp-checks` 和 `eq:repetition-seed` 分别属于 theorem 内嵌的公式块。

每个抽取对象应能通过原文件的 `[char_start:char_end]` 切片找回完全相同的 LaTeX。行号对应原始文件，不是把输入文件合并后重新计算的行号。中文注释位于真实对象之前，能够暴露将 UTF-8 字节位置误当成 Python 字符位置的问题。

源文件不是通过重新生成的 LaTeX 保存：大小写、空白、注释和宏调用都应在原始资产中保留。文件 SHA-256 针对实际字节，字符区间针对 UTF-8 解码后的字符串。

## 5. 不应生成的对象或引用

以下内容仅出现在注释或 verbatim 中，不能作为标签、真实环境或输入文件导入：

- `lem:comment-ghost`
- `lem:verbatim-ghost`
- `thm:verbatim-ghost`
- `this-comment-must-not-be-read`
- `this-verbatim-must-not-be-read`

这些名称可以出现在保存的原始文字中，但不能进入真实标签索引或引用解析结果。

## 6. 资源与数据的边界

`figures/tanner-placeholder.svg` 是实际存在的资源，画的是长度三重复码种子的 Tanner 图：三个变量、两个校验、四条边。它不表示完整的十三量子比特 HGP 图。

`references.bib` 包含真实的 Tillich–Zémor 文献条目，引用键为 `TillichZemor2009`，指向 [arXiv:0903.0566v2](https://arxiv.org/abs/0903.0566v2)。图中可以保留 citation 节点和 bibliography 资源节点；只识别引用键不等于核对了文献中的所有结论。

`tab:rep3` 与 `ex:rep3-parameters` 写出了有限普通 HGP 实例的 `n=13,k=1,d=3`。自动解析器应把它们作为表格、示例和来源陈述。没有明确元数据与验证证据时，不应自动生成一个标为已验证的 CodeInstance。

该小例子的数学参数正确：两组种子都是 `[[1,1,0],[0,1,1]]`，HGP 检查矩阵各有 6 行和 13 列，GF(2) 秩均为 6；X/Z 距离可穷举验证为 3。本 LaTeX 工程没有附计算报告，也没有执行这些数值检查。

## 7. Lean 标记的解释

`lem:css-commutation` 含有 `lean{QEC.Examples.binary_css_commutation}` 与 `leanok`。这个名称是演示用的作者标注；本工程没有对应 Lean 项目，不声称该声明存在。

预期保留声明名和作者完成标记，同时维持“未核查”的形式化状态。`leanok` 不应自动成为 `lean_verified`、`kernel_checked` 或 `semantic_review=equivalent`。
