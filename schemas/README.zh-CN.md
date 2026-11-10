# Schema 路径

> **中文** · [English](README.md)

当前 JSON Schema 文件在[打包 schema 目录](../qecgraph/validators/schemas/)。
Checkout 使用者可把旧的 `schemas/<name>.schema.json` 路径替换为
`qecgraph/validators/schemas/<name>.schema.json`。已安装的 Python 使用者可用
`importlib.resources` 读取同一文件。

Schema 名称和记录版本保持不变。来源坐标、内容哈希和跨记录绑定等语义检查
仍需要包内 validator。
