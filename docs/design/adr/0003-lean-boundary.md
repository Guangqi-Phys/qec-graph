# ADR 0003 · 小型 Lean 构建边界与第三方核对

核对日期 2026-11-06。选用官方 Lean 4.19.0，实际运行得到 commit 前缀 6caaee842e94，
固定完整提交 `6caaee842e9495688c1567e78c0e68dbb96942aa`。
本机使用官方 macOS ARM64 发布包，实际字节 SHA-256 为
`94d4246fd90a152a4819419498d3e45c941a31638a57a0a8e32561494ab6cea7`。
官方 release API 的 digest 为 null，因此这里是实测下载字节哈希，不冒充上游签名。

实际阅读的第三方提交和许可证：

| 项目 | 固定提交 | 实际检查路径 | LICENSE SHA-256 |
|---|---|---|---|
| [Lean 4](https://github.com/leanprover/lean4/tree/6caaee842e9495688c1567e78c0e68dbb96942aa) | 6caaee842e9495688c1567e78c0e68dbb96942aa | 发布包 LICENSE；核心环境与 CollectAxioms/FoldConsts API 源码 | 8b28515ffffc5c0fe2807d8ae3735b00b324d9b7ce807dd63ff6ac8922fbce7e |
| [mathlib4](https://github.com/leanprover-community/mathlib4/tree/c44e0c8ee63ca166450922a373c7409c5d26b00b) | c44e0c8ee63ca166450922a373c7409c5d26b00b | Mathlib/Data/Matrix/Defs.lean，LICENSE | b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1 |
| [Lean-QECert](https://github.com/QudeLeap/Lean-QECert/tree/c0ff74952c65b48e2ba5430fc4dfa4459d120440) | c0ff74952c65b48e2ba5430fc4dfa4459d120440 | QEC/Coding/CSS/ParityChecks.lean，LICENSE | e9349497d7989d39cb0ce364c6abe20c45e6331d5585f6db31537c08fd0977eb |
| [QECLean](https://github.com/Stavan-Jain/QECLean/tree/8d93e65228c4faf81e602a2d2097fc2340a1720a) | 8d93e65228c4faf81e602a2d2097fc2340a1720a | QEC/Stabilizer/Codes/Repetition/Three.lean，LICENSE | 3d7fa7264ca06e4c1fa9dd2de568b3e2cfd8941bb913dfcea54f38b8fdc88c7a |

这些 LICENSE 实际内容均为 Apache 2.0。未复制第三方实现代码；Lean core 是运行依赖，
其他三个项目只是静态定义参考，没有安装、构建或声明复现其全部结果。

mathlib Matrix 使用函数型行/列索引；QECert 的 parityCheckRow/KernelCode 基于有限域线性映射，
P 行表示 Z、Q 行表示 X，需明确与本项目 H_X/H_Z 约定的符号对应。
QECLean 的三比特重复码通过 Pauli 群、phase/check 独立性和 stabilizer framework 表达，
并明确其 quantum distance 为 1；不能将经典重复码距离直接当成量子距离。

本轮先建立 `Fin n → Bool`、xor/and 的小型可重放结果，不引入完整域/Pauli 框架。
Bool 到 ZMod 2、矩阵秩/核/商空间和外部库之间的编码桥接尚未形式化，因此语义映射保持未审核。
这项选择不声称候选库不兼容，只限定当前边界，避免在缺少桥接证明时冒用其结论。
实际构建不依赖 mathlib，运行证据中的 mathlib_commit 必须为 null 并说明 not_a_dependency。
