# ADR 0002 · 固定作用域的只读 AI 工具

采用 Python `ReadOnlySession` 作为 CLI/MCP 共用边界。工具名称固定为：
`qecgraph_search`、`qecgraph_show`、`qecgraph_context`、`qecgraph_deps`、`qecgraph_impact`。
不提供写入、构建、TeX 执行、Lean 执行或任意文件读取工具。

启动时固定单个 store snapshot 或 corpus registry revision；工具参数不允许切换路径/版本/作用域。
corpus 跨文档 selector 仍使用 source_version_id::selector；重复 label 明确返回 AMBIGUOUS_SELECTOR。
每次调用都核对固定资产/快照的可读性与完整性，不重新读取 CURRENT 来选择另一个版本。

输入以 JSON Schema 固定，拒绝额外属性，限制查询长度、深度、节点、搜索数和字符预算。
默认最大深度 4、100 节点、50 搜索结果、64000 字符；操作者可以缩小或在程序支持上限内明确扩大。
字符预算单位是 compact JSON data 的 Unicode codepoint 数，非 token 数。
只删除完整节点/关系或完整搜索项；不能截断根陈述/假设。根块不适配预算时返回 BUDGET_ROOT_TOO_LARGE。
缺失部分与核心遍历截断均保留机器可读标识，context_complete=false；不把部分上下文说成完整证明。

统一返回 `{ok:true,data:{...}}` 或 `{ok:false,error:{code,message,scope,details?}}`。
错误码包括 UNKNOWN_TOOL、INVALID_ARGUMENT、SCOPE_REQUIRED、AMBIGUOUS_SELECTOR、NOT_FOUND、
BUDGET_ROOT_TOO_LARGE、BUDGET_TOO_SMALL 和 QUERY_ERROR。show 是含全部状态的 audit view；其他回答工具沿用 query 状态策略。
来源定位、版本、证据类别、未知和 partial 状态均不提升。论文/代码文字只作为数据，不作为运行指令。

MCP stdio 绑定官方固定版本 [2025-06-18 transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)、
[lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle) 与
[tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)；本次实际阅读日期 2026-11-06。
采用逐行 UTF-8 JSON-RPC、初始化握手、tools/list 和 tools/call。
工具声明只读 hints 并返回相同的结构化 envelope，同时保留兼容的 text content；
客户端仍沿用自己的工具授权设置。服务只实现本地 stdio，不对外监听 HTTP 端口。
