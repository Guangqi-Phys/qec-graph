# Lean 构建、实际声明与证据

本实现采用 [ADR 0003](adr/0003-lean-boundary.md) 的 core-only 边界和固定 Lean 4.19.0。
不将旧 HGP [[13,1,3]] 距离穷举或 LaTeX leanok 升级成 Lean 验证。

```bash
python tools/reproduce_lean.py --out build/reproduce-lean
# 显式选择其他已安装但版本匹配的 Lake：
python tools/reproduce_lean.py --lake /absolute/path/to/lake --out build/reproduce-lean
```

脚本不安装工具或运行 lake update；执行实际 clean/build/export，保存每条命令、退出码和 stdout/stderr 的字节哈希。
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

## 导入与查询

```bash
# 将 <report.json> 换成上面命令打印的实际路径；使用一个新的输出目录。
python tools/reproduce_lean_mapping.py --report <report.json> --out build/lean-mapping
qecgraph lean-status --corpus build/lean-mapping/corpus
qecgraph context formalization:lean-demo:boolean-row-pair --corpus build/lean-mapping/corpus --include-candidates
qecgraph deps lean:qec-core:QEC.Binary.css_example_commutes --corpus build/lean-mapping/corpus --depth 1
```

示例把独立的 TeX 来源、规范 claim 和实际声明连起来，保留原文快照、claim 修订及两者哈希。
`lean-import <report.json> --corpus <目录> --project-id qec-core --project lean` 导入实际构建；
可另用 `--mapping` 指定 JSON。映射需要明确的 theorem 全名和完整类型 Expr 哈希，且原文/claim
绑定必须吻合。论断、计划依赖与已编译的类型/证明常量各自保存。只被引用的常量是有明确未知原因的
名称节点；完整导出才有类型、模块和可定位源码。导入不会改变 claim 审核状态。

查询当前状态会重读受管理产物、项目源码/配置/manifest、导出器和实际工具二进制；不会执行 Lean。
其中任何一项失效，旧记录保留，边退出默认依赖/上下文；`show` 仍保留审计数据和状态。
不同机器或缺少当前输入时可显式 `--historical` 导入，始终只作历史。构建导入当前只支持空外部包
manifest；第三方包内容的绑定未实现。命令日志从第 22 步报告起全部带哈希；较早报告保留原格式，
只能作为历史读取。上下文保留完整陈述/领域数据，关系从经状态筛选的 edges 读取；原始 refs 和 review
保留于审计 show。受预算限制时查询报告截断或不能容纳完整根节点。

`lean-status` 和查询结果的 `build_binding.semantic_review` 报告当前构建及有效人工审核所支持的结论。
`declared_semantic_review` 保留记录里的提议或历史值。演示的 `formalizes` 和来源对应仍为候选。
距离硬筛选要求有效的语义审核、构建绑定和明确的距离论断证据。实测映射回放见 `validation/p5/step22/`。

## 信任与失效反例

```bash
python tools/reproduce_lean_checks.py --out build/lean-checks
```

使用新的输出目录。脚本重建当前提交中干净的 `lean/`，并在独立副本里执行反例。
`validation/p5/step23/results.json` 记录了 10 个实测场景，含每次构建的输入、日志与导出：

- 传递依赖的 `sorryAx`、自定义公理和固定 Lean 4.19.0 中 `native_decide` 实际引入的
  `Lean.ofReduceBool` 均被拒绝。该名称来自实际导出；策略拒绝所有未列入的公理。
- 定理把结论加入假设后仍能编译，完整类型哈希变化使原映射被拒绝，corpus 保持原状态。
  只导出另一个目标的构建也无法满足目标审计。
- 改变类型、import、toolchain 或作为附加输入记录的矩阵 JSON，都会使旧导出变 stale，
  查询仍能查看历史构建。矩阵文件指纹只绑定字节，不是已证明的矩阵编码桥接。

项目可以显式记录独立语义核对；当前演示未做人类语义审核，也未建立完整 CSS 矩阵、
秩、距离或 Python HGP 证书到 Lean 的桥接。
