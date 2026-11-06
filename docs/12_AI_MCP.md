# 固定快照的只读 AI 接口

接口契约以 [ADR 0002](adr/0002-read-only-ai-contract.md) 为准。
Python 使用 `ReadOnlySession`，CLI 使用 `query-tool`，二者返回同一 JSON envelope。

```python
from qecgraph.ai_tools import ReadOnlySession

session = ReadOnlySession(store="build/demo")
result = session.invoke("qecgraph_context", {"identifier": "thm:hgp-css", "depth": 2})
print(result)
```

```bash
# 参数文件内容：{"identifier":"thm:hgp-css","depth":2}
qecgraph query-tool qecgraph_context --arguments query.json --store build/demo
```

Session 固定启动时的 snapshot；corpus 使用固定 registry revision，可加 source_version_id。
重开 session 才选择新的 CURRENT。每次调用仍校验固定产物和资产，不把损坏缓存或缺失文件说成有效证据。
所有工具只读；不运行来源脚本、TeX 或 Lean，不修改任何人工记录。

默认上限：深度 4、100 节点、50 搜索结果、64000 compact JSON 字符。
工具参数的 max_nodes/depth/limit/max_chars 可以在 session 上限内缩小。
budget 统计完整条目的遗漏，truncated/context_complete 表明是否缺少上下文；
不截断根陈述或假设，预算不足返回明确错误。搜索项带来源坐标、审核与验证状态，召回不等于证明。
show 作为 audit view 返回历史、候选和失效边，保留准确状态；其余遍历共用状态过滤。
无结果仅表示固定 scope 未匹配。

CLI 可用 --snapshot、--registry-revision、--source-version-id 固定读取范围；
session-max-* 参数设置操作者允许的最大预算。工具参数不能传路径或更改作用域。

## MCP stdio

```bash
python -m qecgraph serve-mcp --store build/demo
# Corpus 服务：
python -m qecgraph serve-mcp --corpus build/corpus --registry-revision <固定revision>
```

服务按官方固定协议 2025-06-18 实现本地 stdio；初始化后提供以上五个工具。
仅声明 tools capability，工具列表固定；无 HTTP、写入、资源订阅、采样或自动 watch。
stdout 只发送逐行 UTF-8 JSON-RPC，兼容 text content 和 structuredContent；日志只能写 stderr。
未知工具/非法参数返回协议错误，业务查询失败返回 isError=true 的相同 envelope。
单请求最多 1 MiB，工具调用每秒最多 60 次；支持 ping、EOF 退出和客户端终止。
请求按顺序处理，未声明长任务、异步取消或进度能力；客户端超时可以终止进程，不影响权威记录。

输入 JSON 拒绝重复 key、非有限数、错误 UTF-8、批量请求及未完成行。
协议协商只提供本服务支持的 2025-06-18；其他协议客户端应接受该版本或断开，不能假设实现了未来版本。
安装后的 qecgraph-mcp 别名等价于 `python -m qecgraph.mcp_server`。
具体客户端配置和三种入口一致性演示在下一步骤补入本页。
