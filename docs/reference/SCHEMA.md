> 历史参考：本文保留上一版原型说明。当前入口和规范见项目根目录 `START_HERE.md` 与编号文档；本次执行结果见 `validation/REPORT.md`。文中旧相对路径、版本和测试计数按历史语境理解。

# 图和元数据约定

## 三种文件

- `graph.json`：`schema_version=qecgraph.graph.v1`，一份导入快照的完整图。
- `annotations.json`：`schema_version=qecgraph.annotations.v1`，人工/AI 提议的独立补充输入。
- [当前 graph schema](../../qecgraph/validators/schemas/graph.schema.json) 提供结构约束。程序另行检查跨文件位置、哈希与关系端点。

图保存的是“对象的记录”，不是数学真理的自动认证。

## 节点字段

| 字段 | 含义 |
|---|---|
| `id` | 精确节点身份；有标签时使用项目命名空间与 label |
| `kind` | definition、lemma、proof、code_instance 等类型 |
| `origin` | parser / sidecar / catalog |
| `title` | 来源标题或显示名 |
| `labels` | 属于该节点的 LaTeX 标签；不包含嵌套公式的标签 |
| `latex` | 该结构块的原始文本 |
| `source` | 相对路径、Unicode 半开字符区间、1-based 行号、文件哈希 |
| `content_sha256` | 原文片段或结构数据的内容哈希 |
| `revision` | 绑定内容、来源和工程语义上下文的修订指纹 |
| `review_status` | extracted、declared、imported、needs_review 等来源审核状态 |
| `verification_status` | 本版使用 not_verified / not_rechecked / imported_claim_not_rechecked |
| `data` | 按节点类型保存的字段；QEC 数值语义需要显式定义 |
| `annotations` | 附加说明及其绑定哈希、有效状态 |
| `record_path` | 本快照中的 JSON 路径 |
| `fragment_path` | 有原文片段时的 `.tex` 路径 |

外部 Lean 名称节点只保存声明字符串、作者映射及未检查状态。`author_claims_formalized=true` 与真实 Lean 构建证据有不同含义。

## 边字段

每条边包含 `id, source, target, relation, status, evidence`。边方向定义如下：

| 关系 | 方向 |
|---|---|
| `contains` | 容器 → 子内容 |
| `defined_in` | 原文片段 → 源文件 |
| `includes` | 包含文件 → 被包含文件 |
| `references`、`cites` | 引用者 → 被引用对象 |
| `depends_on_declared`、`depends_on_candidate`、`depends_on_reviewed` | 使用结果 → 所需结果 |
| `proof_of`、`proof_of_candidate` | 证明文本 → 目标陈述 |
| `formalizes` | Lean 声明标注 → 文献陈述 |
| `describes` | 原文片段 → 领域对象 |
| `has_matrix`、`has_presentation` | 码实例 → 矩阵/表示 |
| `uses_circuit`、`uses_noise`、`uses_decoder` | 运行或配置对象 → 所用对象 |
| `reports` | 来源数据 → 被描述对象 |
| `supports` | 证据记录 → 被支持的论断 |
| `catalog:*` | 保留原 catalog 关系的方向，未重新解释其数学意义 |

`observed` 表示抽取到语法事实，`declared` 表示作者/sidecar 声明，`candidate` 表示推测；`stale`、`unbound_review`、`unresolved` 需要处理。它们不是可以替代数学语义审核的单一可信度分数。

## Sidecar 输入

`nodes` 中的每条记录需要 `id, kind, title`，可以带 `data` 和 `source_labels`。领域实体不会因为参数相同而自动合并。

`edges` 中的端点可以使用实际 node ID，或者 `label:真实标签`；后者只能解析到唯一标签。允许的关系由 `qecgraph.graph.KNOWN_RELATIONS` 明确列出。不会自动把普通引用提升为证明依赖。

`annotations` 中的 `target` 使用同样的选择方式，`data` 是补充字段，`review_status` 默认 draft。审核为 reviewed 时须保存以下两种绑定：

```json
{
  "target": "label:thm:hgp-css",
  "review_status": "reviewed",
  "expected_content_sha256": "从 show 结果复制的真实哈希",
  "expected_project_source_hash": "从 context 结果复制的真实哈希",
  "data": {"review_note": "实际核对内容"}
}
```

这只是模板，不能把示意文字当作哈希。绑定状态由工具计算；新快照不改写你的 sidecar。

## 与前一套知识库的连接

论文中的一个 lemma 节点表示“一段准确的来源陈述”；前一知识库的 claim 表示“整理后的数学结论”。可以让多个来源节点连接同一个规范化 claim；合并与等价判断由显式记录完成。

catalog 导入保留原记录及关系，原资产地址仍属于原知识库。不要把 graph 的源文件行号解释为 PDF 页码，也不要把提取片段的哈希解释成证明正确性。
