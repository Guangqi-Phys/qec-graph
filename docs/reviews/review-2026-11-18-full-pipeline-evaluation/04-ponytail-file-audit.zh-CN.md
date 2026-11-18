# Ponytail 逐文件审查与回归记录

2026-11-18。审查基线为 `ac3db1d`。按项目约定固定使用 Ponytail 的 MIT 版本 `96608e078b2d5ea607c5c3b8b5a54d1c1fba6846`，逐个核对调用方、已有测试和可删除的重复逻辑。历史整改见 [03 整改计划](03-remediation-plan.zh-CN.md)，采用的原则见 [Ponytail 源码](https://github.com/dietrichgebert/ponytail/tree/96608e078b2d5ea607c5c3b8b5a54d1c1fba6846)。

共审查 254 个文件，包含 125 个生产 Python 文件、89 个测试文件、20 个工具及打包脚本、3 个历史测试脚本、17 个安装、构建、CI 和部署配置。修改 29 个文件，新增 199 行、删除 240 行，净减 41 行。保留独立校验、失败恢复和兼容入口所需的分支。JSON Schema、示例 TeX、数据资产和文档属于声明或输入，本次逐代码文件清单以可执行源码和构建部署配置为范围。

## 主要改动

- 统一 Anthropic 和 OpenAI 的 HTTP 请求、响应解码和重试分类，保留各 provider 的协议参数和诊断。
- 共用归档摘要检查、TeX 条件所属环境检查和文献辅助材料读取，简化同源入口选择和声明复制。
- 精简 MCP 帧限制和输出预算计算，减少检索中的重复坐标、文本和向量计算。
- 共用 Markdown 测试的本地链接解析器。保留各套测试的目标、错误定位和断言。

## 回归验证

| 检查 | 基线和本轮结果 |
| --- | --- |
| `QECGRAPH_TEST_TEX=1 python -m unittest discover -s tests -v` | 同一组 590 个测试全部通过。默认测试模式通过 579 项、跳过 11 项，分支覆盖率报告为 85.32% |
| `python tools/reproduce.py --out build/ponytail-file-audit/reproduce` | 4 个来源文件、29 个片段、36 个节点、99 条边、11 个搜索命中及 16 个上下文节点，校验通过 |
| `python tools/reproduce_mcp.py --out ...` | 7 项交互检查通过。另对比 8 个 stdio 边界案例，退出码、读取位置及响应字节一致 |
| 五篇真实归档离线重建 | 两次各发布 5 篇，0 个版本冲突，11 条码参数候选。release 均为 `97da819108d7adca61c92c8b0f64154ad2b9b5398c5c518a39a696a0ff135bbc`，图谱字节、快照产物哈希及 `validate` 结果一致 |
| `python tools/eval_retrieval.py`，五篇八题 | BM25 Recall@5/10 均为 1.000，MRR@10 为 0.775。字面检索三项均为 0.125，7 题无候选。逐题排序、证据排名及输出的非耗时字段一致，工具失败 0 |
| `python tools/reproduce_knowledge.py`，34 篇 | 67 个探针、335 次调用。响应哈希及非耗时字段一致，非预期失败为 0，两次全文预算拒绝符合预期 |
| `python tools/reproduce_preparation.py` | 48 项的稳定准备材料一致。两次均为 44 ready、3 partial、1 failed，46 项通过来源保真、规范化重编译及 PDF 文本比对，20 项语法探针通过。`report_preparation.py --check` 通过 |
| Provider 和本地向量 | 30 个离线 HTTP 对照案例的请求字节、结果和错误元数据一致。816 组本地嵌入输入和维度产生完全相同的向量 |
| 静态和分发 | Ruff、mypy、复杂度门禁、Markdown 和 `sh -n install.sh` 通过。Pyright 使用项目虚拟环境，0 错误、74 条告警。wheel 和 sdist 通过 Twine 及包内容校验。Docker 在 Linux arm64 Python 3.13 镜像内通过版本和切割冒烟检查 |

检索固定在机器副本的 release `203427876de57e2cc9af9dbf3268caf1e4a33e1388c713cc41ca07ddd39b9b61`。34 篇读取固定在 release `b694c0858805f07d238806260576463c6d98e4cce46d7927f227bb9bad68e1fc`。归档重建从同一份已登记归档开始，两组机器目录独立创建。评测均在本地副本进行，模型调用为 0。

准备回放使用相同来源、入口配置、TeX 支持文件和语法探针。三个 partial 对应 `1804.03719v1` 的原生编译失败及 `2303.15933v1`、`2605.30298v1` 的 BBL 不兼容。failed 对应预期拒绝的 PDF 反例 `1208.0928v1`。回放及对照工件在 `build/ponytail-file-audit/`。准备回放现场的 Git HEAD 仍为基线，实际执行源码由 `execution_sources` 的逐文件 SHA-256 绑定。真实模型质量、数学正确性和 Lean 构建本轮未验收。

## 逐文件记录

| 文件 | 处理 | 核对依据 |
| --- | --- | --- |
| `.dockerignore` | 保留 | Exclude local build products and workspace directories from the Docker build context. |
| `.github/workflows/ci.yml` | 保留 | Keep the four Python/platform jobs, native TeX isolation, coverage and container smoke as independent gates. |
| `.github/workflows/docs-links.yml` | 保留 | Keep scheduled external link verification distinct from local documentation lint. |
| `.github/workflows/golden.yml` | 保留 | Bound archive downloads and verify each pinned digest before replay. |
| `.github/workflows/pypi-publish.yml` | 保留 | Verify immutable release assets and checksums before the PyPI upload job. |
| `.github/workflows/standalone-release.yml` | 保留 | Preserve per-architecture smoke tests, Python artifact verification and publication prerequisites. |
| `.gitignore` | 保留 | Keep generated builds, local indexes, virtual environments and fixtures outside Git. |
| `.lychee.toml` | 保留 | Retain link-check limits, retries and the historical release exception. |
| `.markdownlint-cli2.yaml` | 保留 | Retain current documentation globs and exemptions for preserved review documents. |
| `.pre-commit-config.yaml` | 保留 | Run Ruff and mypy with scoped hook triggers and stable project commands. |
| `Dockerfile` | 保留 | Preserve installation of the wheel-backed CLI and container working directory. |
| `MANIFEST.in` | 保留 | Include docs and fixtures required by source distributions and exclude generated outputs. |
| `compose.mcp-isolated.yaml` | 保留 | Keep the read-only machine mount and the restricted networking, identity and privilege settings. |
| `compose.yaml` | 保留 | Keep the read-only source mount and separate writable research output. |
| `deploy/mcp-macos.sb` | 保留 | Preserve the stdio sandbox's executable, read, write and network permission boundaries. |
| `docs/reviews/review-2026-11-17-compile-prepare-testing/test_preparation_adversarial.py` | 保留历史 | Retain the historical adversarial and differential review evidence for exact failure cases. |
| `docs/reviews/review-2026-11-17-compile-prepare-testing/test_preparation_metamorphic.py` | 保留历史 | Retain the historical metamorphic evidence for inactive branches, include factoring and citation bindings. |
| `docs/reviews/review-2026-11-17-compile-prepare-testing/test_preparation_properties.py` | 保留历史 | Retain the historical randomized source reconstruction and multibyte coordinate evidence. |
| `install.sh` | 保留 | Keep HTTPS restrictions, manifest checks, version matching and atomic replacement across supported platforms. |
| `pyproject.toml` | 保留 | Keep Python compatibility, pinned runtime dependencies, entry points, package data and quality gates. |
| `qecgraph/__init__.py` | 保留 | Expose the version and public splitter while keeping LaTeX initialization lazy. |
| `qecgraph/__main__.py` | 保留 | Hand the process exit status back from the module entry point. |
| `qecgraph/cli/__init__.py` | 保留 | Keep help, JSON stream selection, terminal cleanup and execution errors on their respective paths. |
| `qecgraph/cli/__main__.py` | 保留 | Keep module execution aligned with the public CLI exit status. |
| `qecgraph/cli/commands/__init__.py` | 保留 | Command dispatch remains explicit and separately verified against parser and help. |
| `qecgraph/cli/commands/ai.py` | 保留 | Provider status and configuration reports expose different fields and redact credentials. |
| `qecgraph/cli/commands/query.py` | 保留 | Preserve typed workspace query and compatibility graph flags, defaults and exit semantics. |
| `qecgraph/cli/commands/records.py` | 保留 | Keep record import, CSS matrix and experiment checks on their typed validation paths. |
| `qecgraph/cli/commands/source.py` | 保留 | The thin splitter wrapper preserves exact source and publication options. |
| `qecgraph/cli/commands/workspace.py` | 保留 | Keep renderer subprocess outcomes and the pinned release check distinct from machine publication. |
| `qecgraph/cli/errors.py` | 保留 | Stable error envelopes preserve subtype precedence, scope, hints and process exit statuses. |
| `qecgraph/cli/help.py` | 保留 | Retain the runnable examples and stream, exit-code and progress help topics. |
| `qecgraph/cli/parser.py` | 保留 | Grouped commands and shortcuts already share argparse option definitions. |
| `qecgraph/cli/process.py` | 保留 | Dispatch frozen subprocesses through the executable and ordinary subprocesses through the active interpreter. |
| `qecgraph/cli/progress.py` | 简化 | Remove unused state and meter input and reuse the measured counter width. |
| `qecgraph/cli/render.py` | 保留 | Retain output-stream contracts and distinct summaries for partial, stale and superseded work. |
| `qecgraph/core/__init__.py` | 保留 | Empty package marker. |
| `qecgraph/core/coordinates.py` | 保留 | Sparse LF checkpoints bound lookup work while preserving Unicode codepoint coordinates. |
| `qecgraph/core/errors.py` | 保留 | Stable error codes and sanitized traceback metadata serve distinct caller boundaries. |
| `qecgraph/core/fs.py` | 保留 | Path and descriptor checks enforce link, type, size and mid-read change limits; comparison and hashing have different early exits. |
| `qecgraph/core/graph.py` | 保留 | Graph identities, edge order, proof lifting and strict JSON validation participate in persisted byte and review contracts. |
| `qecgraph/core/language.py` | 保留 | Recursive CJK checks cover object keys, values and indexed containers with exact diagnostic paths. |
| `qecgraph/core/progress.py` | 保留 | Context scoping and lock ordering keep counters, nested phases and failure outcomes consistent. |
| `qecgraph/core/relations.py` | 保留 | Explicit relation and endpoint declarations preserve the difference between dependencies and ordinary references. |
| `qecgraph/core/search.py` | 保留 | BM25 postings, lexical normalization and deterministic tie breaks determine retrieval ranking. |
| `qecgraph/core/tool_help.py` | 保留 | Tool and parameter text communicates bounds, units, provenance and unknown-value semantics. |
| `qecgraph/core/transactions.py` | 保留 | Writer locking, atomic replacement, temporary-file cleanup and compact JSON variants implement distinct recovery and serialization contracts. |
| `qecgraph/domain/__init__.py` | 保留 | Empty package marker. |
| `qecgraph/domain/ai_records.py` | 保留 | Skill-to-record mapping fixes canonical extraction identities; empty-removal state is retained when already published. |
| `qecgraph/domain/research.py` | 保留 | Record structure comes from packaged schemas while the checks enforce exact evidence and cross-revision joins. |
| `qecgraph/domain/research_store.py` | 保留 | Separates old revisions and pending writes, validating registered source spans and exact quotes before publishing. |
| `qecgraph/domain/software.py` | 保留 | Seed import and read-only metadata refresh retain different provenance; refresh is allowlisted, bounded and disables redirects. |
| `qecgraph/domain/status.py` | 保留 | Independent edge and annotation eligibility rules plus deterministic, iterative reviewed-cycle detection. |
| `qecgraph/knowledge.py` | 简化 | Share document file order, compute source section paths once per unit and normalize literal search terms once per query. |
| `qecgraph/knowledge_context.py` | 简化 | Reuse the visible record mapping and compute omitted-frontier and check-matrix membership once. |
| `qecgraph/llm/__init__.py` | 保留 | Small public configuration exports keep package import separate from live provider operations. |
| `qecgraph/llm/artifacts.py` | 保留 | Normalization manifests bind exact UTF-8 bytes and coordinate ranges to the source archive; serialized plan hashes are compatibility-sensitive. |
| `qecgraph/llm/cache.py` | 简化 | Uses contextlib.suppress for best-effort chmod and reuses the output path while keeping locked atomic writes. |
| `qecgraph/llm/client.py` | 简化 | Calculates each provider-reported cost once for both request and batch accounting. |
| `qecgraph/llm/config.py` | 保留 | Provider configuration, injectable environment and TOML defaults have explicit public validation and opt-in upload behavior. |
| `qecgraph/llm/errors.py` | 保留 | Provider failures retain machine-readable retry and status fields; rejected output stays outside printable diagnostics. |
| `qecgraph/llm/extract.py` | 保留 | Schema, line citation, quote validation and bounded correction preserve distinct checks on model output. |
| `qecgraph/llm/normalize.py` | 简化 | Builds existing transport messages directly and uses the already-imported skill loader. |
| `qecgraph/llm/prepared.py` | 保留 | Prepared evidence masks excluded source while retaining coordinates and supports offline proposal revalidation. |
| `qecgraph/llm/providers/__init__.py` | 保留 | Names the supported provider and transport interfaces. |
| `qecgraph/llm/providers/anthropic.py` | 简化 | Delegates transport/status/JSON handling while retaining Anthropic request fields and text blocks. |
| `qecgraph/llm/providers/base.py` | 保留 | Frozen messages/results and provider/transport protocols support optional adapters and offline fixtures. |
| `qecgraph/llm/providers/cli.py` | 保留 | CLI isolation uses an environment allowlist, temporary directory and fixed tool-free Claude options. |
| `qecgraph/llm/providers/factory.py` | 保留 | Explicit provider dispatch preserves selected endpoint, credential and CLI policy. |
| `qecgraph/llm/providers/http.py` | 简化 | Shares the same JSON POST, transient-status policy and sanitized transport or JSON errors across both HTTP adapters. |
| `qecgraph/llm/providers/openai.py` | 简化 | Uses shared HTTP handling and preserves structured-output setup, tracing IDs and response interpretation. |
| `qecgraph/llm/redact.py` | 保留 | Literal configured values and token pattern redaction cover different diagnostics and response text. |
| `qecgraph/llm/review.py` | 保留 | Validates proposal path, full release binding and current output contract before yielding research records. |
| `qecgraph/llm/skills.py` | 简化 | Uses one directory traversal for bundled and workspace skill packs while retaining order and overrides. |
| `qecgraph/llm/structure.py` | 保留 | Version and input-budget checks, local plan verification and recovery provenance each serve a separate boundary. |
| `qecgraph/maintenance.py` | 保留 | Keep doctor metadata probes independent so individual checks can report their failures. |
| `qecgraph/mcp/__init__.py` | 保留 | Retain the package marker for the stdio server and AI tool interfaces. |
| `qecgraph/mcp/ai_tools.py` | 简化 | Share the error envelope for selection and tool errors and measure the same mutable result when fitting output. |
| `qecgraph/mcp/server.py` | 简化 | Capture descriptors once for name/schema checks and remove the unreachable second byte-limit guard. |
| `qecgraph/preparation/__init__.py` | 保留 | Defines the active preparation rule version consumed by manifests and reporting. |
| `qecgraph/preparation/acceptance.py` | 保留 | Independently verifies frozen input and published attempt identities before trusting recorded counts and syntax probes. |
| `qecgraph/preparation/artifacts.py` | 保留 | SourceIndex and ArtifactJSON cache distinct byte offsets and parsed metadata; safe_path and stable JSON support material validation. |
| `qecgraph/preparation/bibliography_runtime.py` | 保留 | Warning parser keeps the bounded 79-byte continuation rule and distinguishes unavailable, incompatible BBL and undefined-key evidence. |
| `qecgraph/preparation/branches.py` | 保留 | Only masks proven literal or static guards and post-document tails while retaining original character offsets and line endings. |
| `qecgraph/preparation/build.py` | 保留 | Engine choice, native bibliography, recorder dependencies and original/support bytes are checked at distinct build boundaries. |
| `qecgraph/preparation/build_view.py` | 简化 | Calls the existing compiled_bibliography helper directly while retaining probe instrumentation and report logic. |
| `qecgraph/preparation/capabilities.py` | 保留 | Separates body syntax, observed bibliography, unique bindings and admissible reference ambiguity in the persisted capability contract. |
| `qecgraph/preparation/citations.py` | 简化 | Reuses the multibib scope map across literal and wildcard scans and builds the literal-command set once per scan. |
| `qecgraph/preparation/compatibility.py` | 保留 | Native retry requires the specific class digest, engine and failure signature; keeps original bytes and records the shim. |
| `qecgraph/preparation/conditions.py` | 简化 | Shares environment containment checks and indexes literal guard starts while preserving guarded-region precedence. |
| `qecgraph/preparation/contract.py` | 保留 | Independent read-side checks rederive source slices, dialect and guard evidence, bibliography state, and normalized mapping. |
| `qecgraph/preparation/convert.py` | 保留 | Strict parser reports incomplete syntax separately from tolerant recovery; source node IDs, spans and coverage remain evidence-bound. |
| `qecgraph/preparation/crossrefs.py` | 保留 | Preserves all local and imported targets plus the unique runtime observation required for derived labels. |
| `qecgraph/preparation/entries.py` | 保留 | Entry-sniff projection stays separate from original bytes passed to native compile, with explicit ambiguity rejection. |
| `qecgraph/preparation/environments.py` | 保留 | Accepts unique consumed tcolorbox declarations only after conditional, shadowing and option-forwarding checks. |
| `qecgraph/preparation/execution.py` | 保留 | Native command logs and per-page PDF comparison have distinct failure states and shared build execution already. |
| `qecgraph/preparation/guard_syntax.py` | 保留 | Exact supported guard grammar, line boundaries and source-map projection are needed for reversible native branch evidence. |
| `qecgraph/preparation/harvmac.py` | 保留 | Native dialect identification, literal bounds and offset-preserving analysis retain Harvmac-specific behavior. |
| `qecgraph/preparation/harvmac_refs.py` | 保留 | Matches unique literal Harvmac definitions to consumed bibliography payloads and preserves ambiguous or unmatched entries. |
| `qecgraph/preparation/inputs.py` | 保留 | Archive repair is restricted to the verified tar trailer case; secondary headers and original trailer evidence remain checked. |
| `qecgraph/preparation/material.py` | 保留 | Shares one evidence writer while keeping distinct compile, conversion, reference and normalization outcomes. |
| `qecgraph/preparation/normalized.py` | 保留 | Mechanical edits use a bounded allowlist and exact nonoverlapping source ranges that the validator rederives. |
| `qecgraph/preparation/options.py` | 保留 | Option field splitting and comment masking preserve nested braces, escaped delimiters and coordinate boundaries. |
| `qecgraph/preparation/pipeline.py` | 保留 | Writer lock, stage-specific failure evidence and previous ready output retention define orchestration behavior. |
| `qecgraph/preparation/projection.py` | 保留 | Reversible byte escapes are independently rederived and verified against native inputs, PDF text and original-byte locators. |
| `qecgraph/preparation/publication.py` | 保留 | Journal handles distinct abort, restore, commit and conflict outcomes while protecting managed paths and prior artifacts. |
| `qecgraph/preparation/reference_syntax.py` | 保留 | BIB/AUX readers preserve balanced optional arguments, comment handling and exact spans; source parser has different argument contracts. |
| `qecgraph/preparation/references.py` | 简化 | Removes the joined AUX text and unused resolver parameter; keeps requested keys, namespace, candidates and diagnostics. |
| `qecgraph/preparation/roundtrip.py` | 保留 | A derived compile must preserve its own bibliography runtime report; status and per-page comparison differ from guard and byte probes. |
| `qecgraph/preparation/sandbox.py` | 保留 | macOS sandbox-exec and Linux bubblewrap keep separate isolation profiles with bounded native processes and curated environment. |
| `qecgraph/preparation/scopes.py` | 保留 | Active, imported and unassigned recorder namespaces intentionally expose different labels and provenance. |
| `qecgraph/preparation/tex_passes.py` | 保留 | Convergence depends on bounded auxiliary digests and explicit rerun-signals; unavailable state still runs the full pass schedule. |
| `qecgraph/preparation/view_contract.py` | 简化 | Imports the shared bibliography artifact helper from its defining module when independently verifying probe inputs. |
| `qecgraph/prepared_extraction.py` | 保留 | Validates the preparation receipt, source continuity and projected locators before emitting source-bound extraction units. |
| `qecgraph/query.py` | 保留 | Keep SQLite phrase/substring and graph in-memory searches distinct, including existing rank, evidence and duplicate-edge handling. |
| `qecgraph/registry.py` | 简化 | Reuse the SHA-256 pattern and the existing lstat regular-file check to reject symbolic links. |
| `qecgraph/render/__init__.py` | 保留 | Retain the renderer package marker. |
| `qecgraph/render/human.py` | 保留 | Keep the history ownership check and staged note/pending-state recovery around atomic publication. |
| `qecgraph/render/thoughts.py` | 简化 | Drop an unused parameter from note metadata selection. |
| `qecgraph/retrieval.py` | 简化 | Compute embedding feature weight per token and unit identity per passage, preserving arithmetic and chunk order. |
| `qecgraph/retrieval_vectors.py` | 保留 | Keep sparse/dense encodings and content verification for existing immutable float32 vectors. |
| `qecgraph/source/__init__.py` | 保留 | Empty package marker for the installed source module layout. |
| `qecgraph/source/assembly.py` | 简化 | Uses dataclasses.replace for frozen directive events while keeping each event update and all source slices intact. |
| `qecgraph/source/bibliography.py` | 保留 | Literal BibTeX scanning keeps escaped and opaque values distinct from explicit DOI and arXiv identifiers. |
| `qecgraph/source/contracts.py` | 保留 | Typed ranges and literal macro metadata expose the source handoff without runtime helpers. |
| `qecgraph/source/encoding.py` | 保留 | Explicit single-byte decoding preserves original bytes and refuses byte layouts with ambiguous projections. |
| `qecgraph/source/entry.py` | 简化 | Uses combinations for identical pairwise title checks and min for the same deterministic nonempty-group representative. |
| `qecgraph/source/extraction.py` | 保留 | Notation normalization records a mapping to exact original offsets and emits candidates with existing conservative identities. |
| `qecgraph/source/incremental.py` | 保留 | Keeps separate input and structural fingerprints, an allowlisted AST cache, and diagnostics-preserving fallback on malformed cache. |
| `qecgraph/source/metadata.py` | 保留 | Recovers only literal title blocks and trusted arXiv identity anchors without guessing missing metadata. |
| `qecgraph/source/package.py` | 保留 | Retains archive metadata quotas, platform path collisions, member-size verification and strict bounded unpacking. |
| `qecgraph/source/parser.py` | 保留 | Discovery and strict final parse have separate diagnostics and cache semantics; source map, alias, include and tolerant recovery paths remain explicit. |
| `qecgraph/source/reading.py` | 保留 | Bounded lexical reader preserves the distinction between display projection and original citation spans. |
| `qecgraph/source/splitter.py` | 保留 | Split rendering uses a pinned immutable snapshot and guarded managed paths, including when an enriched snapshot already exists. |
| `qecgraph/source/structure.py` | 保留 | Proposed body partitions must satisfy exact line coverage, literal heading and bibliography anchors, and bound proposal identity. |
| `qecgraph/source/syntax.py` | 保留 | Opaque declaration arguments, source-derived signatures and fallback pylatexenc signatures have different lexical contracts. |
| `qecgraph/store.py` | 简化 | Reuse the SHA-256 pattern and Path.is_relative_to after resolution, keeping containment and validation. |
| `qecgraph/validators/__init__.py` | 保留 | Cached schema and validator construction preserve optional format checks and explicitly unresolved endpoint behavior. |
| `qecgraph/validators/qec.py` | 保留 | GF(2) validation and sampling checks preserve distinct mathematical conditions and finite enumeration limits. |
| `qecgraph/validators/research.py` | 保留 | Strict integer, interval and source-evidence checks supplement schema validation. |
| `qecgraph/workspace.py` | 简化 | Reuse bounded archive verification, simplify idempotent claim cleanup and remove a redundant entry-point check. |
| `qecgraph/workspace_assets.py` | 保留 | Keep streaming hash verification and bounded byte reads for the distinct asset paths. |
| `qecgraph/workspace_projection.py` | 保留 | Retain version-qualified occurrences, candidate labels and ambiguity-aware bibliography edges. |
| `qecgraph/workspace_publication.py` | 保留 | Preserve the separate semantic and external-index stages, workspace locks and race checks. |
| `qecgraph/workspace_query.py` | 简化 | Reuse scope and pagination values and define the record-binding lookup once per performance query. |
| `tests/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/contracts/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/contracts/docs/__init__.py` | 简化 | Introduce one local Markdown target parser shared by the documentation contract suites. |
| `tests/contracts/docs/test_docs.py` | 简化 | Reuse the Markdown target parser across three checks and stop reading the operations index twice in the same redirect check. |
| `tests/contracts/docs/test_docs_bilingual.py` | 简化 | Reuse local Markdown target resolution while keeping heading anchors and stale label assertions distinct. |
| `tests/contracts/packaging/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/contracts/packaging/test_distribution.py` | 保留 | Keep Docker build inputs, installed entry points, sdist contents and UTF-8 package metadata independently asserted. |
| `tests/contracts/packaging/test_installer.py` | 保留 | Keep invalid digest, wrong binary version and prerelease selection as independent installer cases. |
| `tests/contracts/test_preparation_architecture.py` | 保留 | Keep import graph cycle checks including deferred imports and semantic extraction boundary assertions. |
| `tests/contracts/tooling/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/contracts/tooling/test_architecture.py` | 保留 | Keep static layer checks beside subprocess checks for lazy CLI and Lean imports and suite discovery. |
| `tests/contracts/tooling/test_tools.py` | 保留 | Keep invoking each real script with --help to test their package imports and entry points together. |
| `tests/integration/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/integration/cli/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/integration/cli/test_ai_cli.py` | 保留 | Keep isolated fake-provider paths and assertions against credential, proposal body and unnecessary provider access. |
| `tests/integration/cli/test_cli.py` | 保留 | Keep CLI exit, stream, scope and renderer-publication paths independently observable through real dispatch. |
| `tests/integration/cli/test_progress.py` | 保留 | Keep PTY interrupts separate from redirected-stream assertions to cover actual terminal cleanup. |
| `tests/integration/mcp/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/integration/mcp/test_mcp.py` | 保留 | Keep lifecycle, rate limit, invalid UTF-8/JSON and real stdio checks on observable MCP protocol boundaries. |
| `tests/integration/pipeline/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/integration/pipeline/test_compilation.py` | 保留 | Keep native TeX replay cases separate for bibliography execution, invalid bytes and explicit support lookup. |
| `tests/integration/pipeline/test_compilation_sandbox.py` | 保留 | Keep one direct runtime check for file, network and credential isolation under the compile sandbox. |
| `tests/integration/pipeline/test_material.py` | 保留 | Keep handoff fingerprints, reference diagnostic checks and mutations logically separate so hashes cannot mask bad material. |
| `tests/integration/pipeline/test_pipeline.py` | 保留 | Keep published bytes, tampering, filtering and graph/retrieval behavior tested at their actual snapshot APIs. |
| `tests/integration/pipeline/test_preparation_acceptance.py` | 保留 | Keep frozen replay reopening, inflated report rejection and retained comparison checks distinct. |
| `tests/integration/pipeline/test_preparation_equivalence.py` | 保留 | Keep frozen comparison of serialized material bytes as well as failure outcomes across versions. |
| `tests/integration/pipeline/test_prepared_extraction.py` | 保留 | Keep verified bundle CLI coverage, original multi-file locator checks and read-only destination checks. |
| `tests/integration/pipeline/test_publication.py` | 保留 | Keep partial publication and retry fault injections separated by existing store and initial publication state. |
| `tests/integration/pipeline/test_splitter.py` | 保留 | Keep shared parser results and explicit module entrypoint parity observable from consumer outputs. |
| `tests/integration/rendering/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/integration/rendering/test_human.py` | 保留 | Keep managed-history and symlink safety checks independent of note layout, date and author metadata. |
| `tests/integration/workspace/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/integration/workspace/test_ai_workspace.py` | 保留 | Keep failed publication and semantic work lock cases alongside bytes and AI configuration evidence. |
| `tests/integration/workspace/test_bibliography.py` | 保留 | Keep citation identity recognition and publication requirements in distinct tests. |
| `tests/integration/workspace/test_incremental.py` | 保留 | Keep same-size/same-mtime cache invalidation checks beside edit-during-build publication recovery. |
| `tests/integration/workspace/test_knowledge.py` | 保留 | Keep graph and machine query source binding checks alongside deliberate text-cache validation damage cases. |
| `tests/integration/workspace/test_knowledge_context.py` | 保留 | Keep theorem and typed revision context, condition filtering and immutable query results as separate assertions. |
| `tests/integration/workspace/test_registry_schema.py` | 保留 | Keep valid nested generated artifacts and rejected registry mutations across publish and reread. |
| `tests/integration/workspace/test_research.py` | 保留 | Keep source-bound research record evidence, exact conditions and numeric semantic checks explicit. |
| `tests/integration/workspace/test_retrieval.py` | 保留 | Keep optional embedding failure and projection/vector corruption paths with separate offline fallback expectations. |
| `tests/integration/workspace/test_status.py` | 保留 | Keep strongly connected component issues limited to active reviewed lines and test filters across stages. |
| `tests/integration/workspace/test_structure_recovery.py` | 保留 | Keep provider budget/opt-out gates separate from proposed structure fallback replay and source citation parity. |
| `tests/integration/workspace/test_thoughts.py` | 保留 | Keep legacy Chinese proposal replacement and tampered-note preservation alongside normal rendering cases. |
| `tests/integration/workspace/test_workspace.py` | 保留 | Keep archive claim retries, initial workspace state, and user-visible process behavior directly tested. |
| `tests/integration/workspace/test_workspace_query.py` | 保留 | Keep fixed release resource URI checks, unreadable operational status and note-ingestion separation. |
| `tests/support.py` | 保留 | Keep one shared test path definition and fixture-only AI configuration helper. |
| `tests/unit/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/unit/domain/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/unit/domain/test_ai_client.py` | 保留 | Keep retry attempts, shared budgets, invalid cache entries and endpoint separation directly exercised. |
| `tests/unit/domain/test_ai_config.py` | 保留 | Keep default and explicit legacy provider configurations as separate cases with strict upload and concurrency options. |
| `tests/unit/domain/test_ai_extract.py` | 保留 | Keep fake provider acceptance fixtures separate from forged evidence and unsupported skill failures. |
| `tests/unit/domain/test_ai_normalize.py` | 保留 | Keep single-root and anthology-style multi-root maps separate from missing-source and duplicate-label rejections. |
| `tests/unit/domain/test_ai_normalize_runner.py` | 保留 | Keep provider-call/no-call normalization paths and complete-root accounting visible through runner results. |
| `tests/unit/domain/test_ai_prefetch.py` | 保留 | Keep measured parallel package progress and state reuse after one failed AI step. |
| `tests/unit/domain/test_ai_provider.py` | 保留 | Keep transport interruption and error body redaction cases distinct, with isolated CLI provider invocation checks. |
| `tests/unit/domain/test_ai_skills.py` | 保留 | Keep bundled schemas, valid overrides and rejected mismatched packs separate. |
| `tests/unit/domain/test_ai_thoughts.py` | 保留 | Keep corrected requests subject to the original evidence constraints and full request budget. |
| `tests/unit/domain/test_output_language.py` | 保留 | Keep Unicode English names and math alongside escaped-CJK rejection, correction and cache replacement. |
| `tests/unit/domain/test_qec_validation.py` | 保留 | Keep malformed coordinates, parity noncommutation and differing sampling metrics as independent outcomes. |
| `tests/unit/domain/test_schemas.py` | 保留 | Keep packaged schema validation over public examples and dispatcher coverage across record types. |
| `tests/unit/domain/test_semantic.py` | 保留 | Keep exact snapshot provenance, immutable validation reads and sharing of repeated assets independently checked. |
| `tests/unit/domain/test_validators.py` | 保留 | Keep invalid strict-JSON cases separate from graph proof endpoint rejection at publication. |
| `tests/unit/parsing/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/unit/parsing/material_fixture.py` | 保留 | Keep the reusable partial-material envelope around deterministic syntax tests to preserve handoff shape. |
| `tests/unit/parsing/test_assembly.py` | 保留 | Keep exact include splicing, unsupported expansion and literal environment boundaries as explicit fixtures. |
| `tests/unit/parsing/test_compilation.py` | 保留 | Keep independent compile control tests for support mutation, hash-bound retries and forged recorder paths. |
| `tests/unit/parsing/test_compiled_references.py` | 保留 | Keep bibliography namespace distinctions, compiled wildcard semantics and exact TeX source spans. |
| `tests/unit/parsing/test_material_contract.py` | 保留 | Keep independent coordinate, hash-preserving forgery, parent cycle and path escape checks. |
| `tests/unit/parsing/test_material_conversion.py` | 保留 | Keep guard, inactive source and cross-reference uncertainty cases observable through material output. |
| `tests/unit/parsing/test_material_publication.py` | 保留 | Keep process interruption, journal conflict and missing tar footer as distinct recovery conditions. |
| `tests/unit/parsing/test_normalized_latex.py` | 保留 | Keep authored formatting, uninterpreted macro bodies and derived bibliography origins independently checked. |
| `tests/unit/parsing/test_notation.py` | 保留 | Keep compact Unicode range test covering inverse notation mapping. |
| `tests/unit/parsing/test_parser.py` | 保留 | Keep a variety of source-preserving parser boundaries including non-UTF-8, duplicate keys and unclosed math. |
| `tests/unit/parsing/test_preparation_adversarial.py` | 保留 | Keep hand-crafted malformed compile inputs and differential engine chains separately reproducible. |
| `tests/unit/parsing/test_preparation_build_view.py` | 保留 | Keep recorder membership and branch proof constraints distinct from text and inserted markers. |
| `tests/unit/parsing/test_preparation_entries.py` | 保留 | Keep title and supplement heuristics with ambiguous or extensionless cases exercised independently. |
| `tests/unit/parsing/test_preparation_environments.py` | 保留 | Keep exact declaration provenance and fail-closed cases for unused, forged or redefined environments. |
| `tests/unit/parsing/test_preparation_harvmac.py` | 保留 | Keep plain TeX discovery, shadowing, and ambiguous number sequence behavior separately pinned. |
| `tests/unit/parsing/test_preparation_metamorphic.py` | 保留 | Keep direct baseline/transformation pairs for comment injection, include factoring and macro locality. |
| `tests/unit/parsing/test_preparation_projection.py` | 保留 | Keep reversible byte encoding separate from exact locator and early catcode refusal tests. |
| `tests/unit/parsing/test_preparation_properties.py` | 保留 | Keep independent invariant generators for assembled text, normalized TeX and Unicode source indexes. |
| `tests/unit/parsing/test_reading.py` | 保留 | Keep old snapshot prose compatibility and current source citation offsets tested through different input forms. |
| `tests/unit/parsing/test_source_package.py` | 保留 | Keep multiple compression/member limits and byte identity tested against actual archive data. |
| `tests/unit/parsing/test_structure.py` | 保留 | Keep exact CRLF/UTF-8 range acceptance and rejected gaps, overlaps and invented bibliography records. |
| `tests/unit/query/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/unit/query/test_lexical.py` | 保留 | Keep separate compact query cases for all-term precedence and QEC notation normalization. |
| `tests/unit/rendering/__init__.py` | 保留 | Retain the empty package marker for unittest discovery and scoped imports. |
| `tests/unit/rendering/test_metadata.py` | 保留 | Keep versioned arXiv name boundaries and family name extraction as separate metadata concerns. |
| `tests/unit/rendering/test_progress.py` | 保留 | Keep terminal size, exact counters, cleanup and visual-state assertions at distinct steps. |
| `tools/bench.py` | 保留 | Keep real and synthetic workloads and latency sampling distinct so measured paths and input sizes remain visible. |
| `tools/check_complexity.py` | 保留 | Keep inventory and comparison logic with legacy complexity allowances and explicit failure handling. |
| `tools/check_distribution.py` | 保留 | Keep sdist/wheel manifest validation and archive metadata checks on actual built artifacts. |
| `tools/compare_preparation.py` | 保留 | Keep material and runtime signatures separate with package-specific mismatches reported directly. |
| `tools/eval_retrieval.py` | 保留 | Keep release and source span validation, full-vs-compact result measurements and threshold output. |
| `tools/extract_prepared.py` | 保留 | Keep local and model-backed extraction paths behind bundle verification and output location safeguards. |
| `tools/mcp_isolated_macos.py` | 保留 | Keep explicit deny-by-default profile assembly and interpreter process arguments at their launch boundary. |
| `tools/prepare_compiled.py` | 保留 | Keep the separate existing-material check, recovery and compilation paths at the direct CLI. |
| `tools/qec-graph.spec` | 保留 | Keep explicit entry point, packaged resources and copied dependency metadata for the standalone executable. |
| `tools/report_preparation.py` | 保留 | Keep report generation and report checking with optional frozen machine evidence separate. |
| `tools/reproduce.py` | 简化 | Validate the single generated graph directly while preserving the annotations and packaged schema checks. |
| `tools/reproduce_golden.py` | 保留 | Keep pinned archives, configured source entrypoints and separate materialized graph checks. |
| `tools/reproduce_incremental.py` | 保留 | Keep alternating full/incremental run order, equivalence comparisons and independent restore/tamper checks. |
| `tools/reproduce_installed.py` | 保留 | Keep temporary venv/wheel testing and out-of-tree CLI invocation with separate smoke endpoints. |
| `tools/reproduce_isolation.py` | 保留 | Keep denial probes and successful authorized MCP reads as separate macOS checks. |
| `tools/reproduce_knowledge.py` | 保留 | Keep read/search/context evidence packs with distinct identifiers and fixed generated source locators. |
| `tools/reproduce_linux_isolation.py` | 保留 | Keep Compose lifecycle, request framing and Linux isolation evidence tied to disposable private fixtures. |
| `tools/reproduce_mcp.py` | 保留 | Keep real stdio framing and process cleanup while probing scope parity with CLI and Python results. |
| `tools/reproduce_preparation.py` | 保留 | Keep one attempt receipt per pinned input and retain compile artifacts for frozen replay evaluation. |
| `tools/reproduce_workspace.py` | 保留 | Keep installed workspace checks for registration, rendering, rebuild, read-only MCP and optional byte-pinned real sources. |
