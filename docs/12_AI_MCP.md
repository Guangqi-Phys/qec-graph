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

store 和 corpus 服务按协议 2025-06-18 实现本地 stdio，并提供以上五个工具。
工作区服务增加研究查询与来源资源。见[工作区说明](user/workspace.md#研究查询和审核)。
各模式均为本地只读服务。
stdout 只发送逐行 UTF-8 JSON-RPC，兼容 text content 和 structuredContent；日志只能写 stderr。
未知工具/非法参数返回协议错误，业务查询失败返回 isError=true 的相同 envelope。
单请求最多 1 MiB，工具调用每秒最多 60 次；支持 ping、EOF 退出和客户端终止。
请求按顺序处理，未声明长任务、异步取消或进度能力；客户端超时可以终止进程，不影响权威记录。

输入 JSON 拒绝重复 key、非有限数、错误 UTF-8、批量请求及未完成行。
协议协商只提供本服务支持的 2025-06-18；其他协议客户端应接受该版本或断开，不能假设实现了未来版本。
安装后的 qecgraph-mcp 别名等价于 `python -m qecgraph.mcp_server`。
## 客户端接入和实测

```bash
qecgraph mcp-config --store build/demo > build/mcp-client.json
python tools/reproduce_mcp.py --out build/reproduce-mcp
```

mcp-config 生成使用当前虚拟环境 Python、绝对 store 路径和固定 snapshot 的可审阅配置；
corpus 同样固定 registry revision。它不修改 Codex 或其他客户端的配置文件。
`examples/mcp-client.example.json` 是常见 mcpServers 配置示例，需替换占位符并按具体客户端的格式接入。
安装包后运行不依赖客户端工作目录；不要使用缺少本项目依赖的另一个 Python。

实际 stdio 测试客户端已完成握手、发现、全部工具调用，验证 text/structuredContent、
CLI/Python/MCP 相同 envelope、固定旧 snapshot/corpus、空结果、重复 label、错误作用域、
节点/字符预算和 partial 状态，共 22 项端到端断言。报告与真实协议 transcript 保存在 validation/p4。
客户端没有运行 TeX/论文脚本/Lean，也没有修改外部应用配置；测试进程通过 EOF 退出。
新会话若需要新版，显式重建配置或选择新 revision，不在一次任务中混读 CURRENT。
