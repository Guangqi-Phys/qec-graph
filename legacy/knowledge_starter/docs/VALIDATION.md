# 本次交付的验证记录

验证日期：2026-11-06。

执行环境：CPython 3.12.14，SQLite 3.53.1，jsonschema 4.26.0。

已执行并通过：

- `python tools/qec_kb.py verify --json-schema`：10 个记录、两个 Schema、资产哈希和跨记录引用通过；具体 HGP 构造、对易、GF(2) 秩、逻辑配对及距离计算通过。
- `python tools/qec_kb.py index`：由原记录生成 SQLite 表、FTS5 和输入指纹。
- `python tools/qec_kb.py codes --n-max 20 --distance-at-least 3`：返回当前普通 HGP 示例，证据级别为 `computed_exact`。
- 同样查询提高到距离下界 4，或将构造改为 `lifted_product`：均返回空列表。
- `python tools/qec_kb.py search HGP`：返回 8 个相关记录，包含当前码实例。
- `python tools/qec_kb.py context claim:rep3-hgp:distance --depth 2`：返回 8 个关联记录，包含准确的计算证据。

数学结果也与另一份独立的纯 Python 枚举核对一致：`n=13, k=1, dX=dZ=3`，两组检查矩阵秩均为 6，X/Z 逻辑代表分别支持在 `[0,1,2]`、`[0,3,6]`。

这些检查覆盖当前小实例和演示查询。没有安装或运行 Lean，没有启动 Docker 服务，也没有对完整 QEC 文献库执行导入。原文语义审核与通用数学验证器需要在扩展时分别实现。
