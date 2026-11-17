# TeX 编译优先文献准备管线测试实现与验证记录

> 状态：测试已实现并验证通过。日期：2026-11-17。对应测试方案见 [01-test-engineering-plan.zh-CN.md](01-test-engineering-plan.zh-CN.md)。

本文记录按 [01-test-engineering-plan.zh-CN.md](01-test-engineering-plan.zh-CN.md) §3 拆分实现的三个独立测试文件、测试用例映射、执行命令及验证结果。

## 目录

- [1. 已实现的测试文件清单](#1-已实现的测试文件清单)
- [2. 用例实现明细](#2-用例实现明细)
- [3. 执行命令与验证结果](#3-执行命令与验证结果)

---

## 1. 已实现的测试文件清单

| 文件路径 | 测试类别 | 用例数 | 运行耗时 |
| --- | --- | ---: | ---: |
| [tests/unit/parsing/test_preparation_properties.py](../../../tests/unit/parsing/test_preparation_properties.py) | 属性测试（Property-Based Testing，`PBT-01`～`PBT-04`） | 4（含 95 组随机生成子用例） | ~0.18s |
| [tests/unit/parsing/test_preparation_metamorphic.py](../../../tests/unit/parsing/test_preparation_metamorphic.py) | 蜕变测试（Metamorphic Testing，`MT-01`～`MT-05`） | 5 | ~0.04s |
| [tests/unit/parsing/test_preparation_adversarial.py](../../../tests/unit/parsing/test_preparation_adversarial.py) | 对抗、安全边界与差分测试（`ADV-01`～`ADV-07`、`DIFF-01`～`DIFF-04`） | 10 | ~0.10s |
| **合计** | — | **19 个测试方法** | **0.314s** |

---

## 2. 用例实现明细

### 2.1 属性测试：[test_preparation_properties.py](../../../tests/unit/parsing/test_preparation_properties.py)

1. `test_pbt01_randomized_syntax_trees_tile_entry_and_reconstruct_bytes`
   - 使用固定随机种子（`20261117`）生成 25 组混合章节、定理、表格、TikZ、数学公式、UTF-8 多字节字符、未闭合花括号（触发 `opaque` 节点）及 `\end{document}` 后尾部的文档。
   - 验证 `validate_material` 通过，`roots` 严格无重叠铺满 `[0, len(entry.tex))`，且从 `source_spans` 字节切片拼接出的内容与原始输入 100% 字节一致。
2. `test_pbt02_multifile_include_splicing_preserves_exact_source_coordinates`
   - 使用固定随机种子（`20261118`）生成 20 组含路径宏与多层嵌套 `\input`（`main.tex` $\to$ `frag_a.tex` $\to$ `sub/frag_b.tex`）的源码树，子文件末尾随机放置无换行注释 `% trailing comment` 或控制词以触发 `EntryCoordinates` 分隔符插入。
   - 验证 `assembly.validate(files) == []`，且每个语法节点的 `source_spans` 原文件字节切片拼接严格等于 `assembly.text[start:end]`。
3. `test_pbt03_normalized_latex_bijective_tiling_and_inverse_reconstruction`
   - 使用固定随机种子（`20261119`）生成 20 组混合 `$`/`$$`、宏参数内 `$x$`、`verbatim`、引用包装宏 `\citeRef` 与 `.bbl` 内联的文档。
   - 验证 `validate_normalized` 通过，且通过 `mapping["segments"]` 的 `input_range` 逆向拼接可 100% 还原 `entry.tex`。
4. `test_pbt04_source_index_utf8_multibyte_and_line_invariants`
   - 使用固定随机种子（`20261120`）生成 30 组含 1～4 字节 UTF-8 字符（ASCII、`é`、`α`、`—`、`𝕏`、`🧮`）与 `\n`/`\r\n` 的文本，每组随机抽样 20 个区间验证 `SourceIndex.span` 的字节切片与 1-based 行号。

### 2.2 蜕变测试：[test_preparation_metamorphic.py](../../../tests/unit/parsing/test_preparation_metamorphic.py)

1. `test_mt01_comment_injection_preserves_outline_citations_and_crossrefs`：验证在文件头、章节后、`\cite{k1, k2}` 逗号后、`\ref` 后注入含伪造标签/引用的 `%` 注释时，大纲、引用绑定、标签与交叉引用结果完全不变。
2. `test_mt02_inactive_branch_and_post_document_mutations_do_not_affect_active_view`：验证在 `\if 0 ... \fi` 与 `\end{document}` 之后注入未定义引用、重复标签与未闭合环境时，激活视图与 `coverage["complete"]` 完全不受影响。
3. `test_mt03_include_factoring_equivalence_between_single_and_multifile_trees`：验证单文件与拆分为 `chapters/sec1.tex`、`chapters/sec2.tex` 后的组装字节、大纲、引用与交叉引用完全等价。
4. `test_mt04_unused_bib_entries_and_control_records_preserve_active_bindings`：验证向 `.bib` 添加未引用条目与 `@CONTROL{REVTEX41Control}` 不改变激活的 `bindings`。
5. `test_mt05_positional_macro_redefinition_locality_invariant`：验证文档中段通过 `\renewcommand` 或 `\newcommand{\alias}{\renewcommand}` 改变宏参数签名时，重定义之前的调用参数解析严格不变。

### 2.3 对抗与差分测试：[test_preparation_adversarial.py](../../../tests/unit/parsing/test_preparation_adversarial.py)

1. `test_adv01_bcf_rejects_xml_doctype_and_entity_declarations`：拦截 `.bcf` 中的 `<!DOCTYPE` 与 `<!ENTITY`。
2. `test_adv02_compiler_mutating_source_or_replacing_with_symlink_is_caught`：验证编译期间篡改 `.sty` 会触发 `source_changed_during_build` 并置 `build.success = False`。
3. `test_adv03_fls_traversal_line_limit_and_entry_flag_injection_rejected`：拦截 `-shell-escape.tex` 等非法入口、过滤 `.fls` 沙箱外路径、拦截 `.fls` 超过 32,768 行。
4. `test_adv04_support_directory_rejects_symlinks_and_conflicting_files`：拦截软链接 `--support-dir`、软链接支持文件及多目录同名文件冲突。
5. `test_adv05_deep_brace_nesting_degrades_gracefully_to_partial_material`：验证 135 层花括号嵌套触发 `depth > 128` 保护后安全降级为 `partial` 产物并保留原文件。
6. `test_adv06_tampered_manifest_status_and_corrupted_aux_locators_rejected`：验证伪造 `manifest.json` 的 `status: "ready"` 被 `validate_material` 拒绝。
7. `test_adv07_cli_prepare_compiled_check_recover_and_exit_codes`：验证 `tools/prepare_compiled.py` 的正常构建、`--check`、`--recover` 及产物被篡改后的退出码（`0` vs `1`）。
8. `test_diff01_and_diff02_roundtrip_pdf_text_mismatch_and_tool_failure_block_ready`：验证 `pdftotext` 页面文本不一致（`different`）或命令失败/超时（`failed`）均阻断 `complete`。
9. `test_diff03_etex_dvips_ps2pdf_pipeline_and_short_circuit_on_failure`：验证 Harvmac 自动选择 `etex`（含 `stdin="b\n"`），且 `dvips` 失败时短路跳过 `ps2pdf`。
10. `test_diff04_non_utf8_aux_bbl_and_bib_produce_explicit_diagnostics`：验证 `.aux`/`.bbl`/`.bib` 含非 UTF-8 字节时生成 `bibliography_encoding` 与 `bib_encoding` 诊断且不崩溃。

---

## 3. 执行命令与验证结果

```bash
.venv/bin/ruff check \
  tests/unit/parsing/test_preparation_properties.py \
  tests/unit/parsing/test_preparation_metamorphic.py \
  tests/unit/parsing/test_preparation_adversarial.py

.venv/bin/python -m unittest \
  tests/unit/parsing/test_preparation_properties.py \
  tests/unit/parsing/test_preparation_metamorphic.py \
  tests/unit/parsing/test_preparation_adversarial.py -v

.venv/bin/python -m unittest discover -s tests/contracts/docs -v
```

| 检查项 | 结果 |
| --- | --- |
| Ruff 静态检查 | `All checks passed!` |
| 新增三大测试套件（属性 / 蜕变 / 对抗与差分） | 19 项全部通过（`0.314s`） |
| `tests/unit/parsing` 全量测试 | 186 项全部通过 |
| `tests/integration/pipeline` 全量测试 | 50 项通过（5 项需 `QECGRAPH_TEST_TEX=1` 的真实编译测试按默认规则跳过） |
| `tests/contracts/docs` 文档契约测试 | 17 项全部通过 |
