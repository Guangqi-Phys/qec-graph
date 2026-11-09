> 历史参考：本文保留上一版原型说明。当前入口和规范见项目根目录 `START_HERE.md` 与编号文档；本次执行结果见 `validation/REPORT.md`。文中旧相对路径、版本和测试计数按历史语境理解。

> Historical. See the [current documentation index](../../README.md).

# 本次运行与验证

日期：2026-11-06。环境：CPython 3.12.14、pylatexenc 2.10、SQLite 3.53.1。

## 运行示例

示例读取三个 `.tex` 文件，提取 26 个结构片段和 19 个真实标签。加入示例 sidecar 后，得到 **36 个节点、97 条边**，其中包含一条显式 CodeInstance 和一个 dataset 节点。这些领域实体来自明确的 sidecar，不是从表格中自动推断。

图、原文切片、引用资产、关系视图、SQLite 与输出清单均已生成。`validate` 核验了文件哈希、全部 26 个来源切片、行号、边端点与数据库一致性。两份 JSON Schema 已检查，当前图与示例 annotations 均通过对应 Schema。

示例有一条预期诊断：用户宏的参数形状已学习，替换体未展开。文件中的 metadata 宏本体为空，但仍使用相同的保守处理规则。

## 语义与维护回归

```bash
python -m unittest discover -s tests -v
```

**16 个测试全部通过**。测试覆盖：

- 真实标签与嵌套公式的正确归属。
- 注释、verbatim 中的假标签和假 input 被忽略。
- `uses`、普通 `ref`、显式 `proves`、相邻证明推测之间的区别。
- `leanok` 不变成数学验证。
- Unicode codepoint、CRLF 和原字节归档。
- 缺失、循环、越界 include 的诊断。
- 重复标签保留歧义，不静默选择目标。
- 重复导入快照幂等，输入文件不改变。
- 有标签陈述修改后 ID 保留、内容哈希改变、绑定审核失效。
- 显式 sidecar 数据实体及矩阵/配置上下文。
- 旧 proof 依赖不会被重新提升为有效 theorem 依赖。
- 资源内容哈希在审核匹配前已完整，资源变化会使对应审核失效。
- 默认 context 的最终边列表排除候选和失效关系。

## 与前一模板的集成

使用 `--catalog` 导入此前知识库模板的十个 JSON 记录，并用 `catalog-links.example.json` 将参数表与原码实例连接，得到 44 个节点、110 条边。

`context code:rep3-hgp:13` 返回关联的 presentation、distance claim 和 evidence；导入记录标注 `imported_claim_not_rechecked`，原记录的计算证据内容仍保留。

此外实际完成了本包 wheel 的构建和本地安装，并使用安装产生的 `qecgraph` 命令验证示例快照。

## 验证范围

这里验证的是工具的结构提取、来源对应、关系语义、维护行为和查询。没有编译 TeX 或 Lean，没有对源表格参数重新执行 QEC 数学验证，也没有证明所有 LaTeX 工程都能被完整解析。复杂宏与条件结构的边界在 README 中说明。
