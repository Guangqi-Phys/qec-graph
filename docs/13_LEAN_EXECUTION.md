# Lean 构建、实际声明与证据

本实现采用 [ADR 0003](adr/0003-lean-boundary.md) 的 core-only 边界和固定 Lean 4.19.0。
不将旧 HGP [[13,1,3]] 距离穷举或 LaTeX leanok 升级成 Lean 验证。

```bash
python tools/reproduce_lean.py --out build/reproduce-lean
# 显式选择其他已安装但版本匹配的 Lake：
python tools/reproduce_lean.py --lake /absolute/path/to/lake --out build/reproduce-lean
```

脚本不安装工具或运行 lake update；执行实际 clean/build/export，保存每条命令、退出码和 stdout/stderr。
记录完整源码/配置/manifest 字节哈希、编译 olean 哈希、实际 toolchain/binary、Git commit、
项目 dirty 状态和包含未追踪输入的补丁指纹；构建前后再次核对输入，变动时拒绝当前证据。
报告中的 mathlib_commit 为 null，原因明确是 not_a_dependency；静态核对的 mathlib 版本不是构建依赖。

## 实际环境导出

`QEC.Export` 从固定编译环境导出声明名称、种类、模块、完整类型、结构化 Expr、
universe 参数、模块真实直接 imports 和声明范围。Expr 仅省略非语义 metadata 的载荷，并明确标注协议；
不省略量词、假设或类型参数。源码行号从 1 开始，Unicode 列从 0 开始，另存实际 UTF-16 列。
类型与证明值的直接常量分开；传递 closure 包括实际 ConstantInfo 的类型/值和 inductive/recursor 引用，
不按作者 uses 或启发式名字推断，不隐藏标准库常量。依赖明确记录未过滤。

传递公理来自 Lean.collectAxioms 的实际 checked environment。
本次先用零公理政策运行，构建通过但审计因实际 propext 而拒绝，保留该失败证据。
随后显式采用 core-boolean-propext-only-v1：只允许标准命题外延公理 propext，
拒绝 sorryAx 及所有未列入政策的公理，包括原生求值引入的附加信任。
这是明确的信任配置，不是删去依赖或声称“无公理”。

`validated_build` 表示准确导出声明在该工具链和公理政策下通过，不表示论文语义对应已审核。
`build_passed`（build-only）和 trust_rejected 分别保留。所有语义审核仍为 not_reviewed。
规范 claim/来源映射与构建证据的接入、失效在下一步骤补入本页。
