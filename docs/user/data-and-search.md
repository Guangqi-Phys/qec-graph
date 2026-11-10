# Data and search

> **Status: Current (0.4.x).** Research records, evidence policy and query contracts.

> **English** · [中文](data-and-search.zh-CN.md)

QEC Graph keeps the original sources, the graph extracted from them, and
versioned research records. Search results refer to the machine release that
served the query, so you can trace a result back to the same data later.

## On this page

- [What the workspace stores](#what-the-workspace-stores)
- [Research record types](#research-record-types)
- [Search by keyword, source, or structured fields](#search-by-keyword-source-or-structured-fields)
- [Read and reproduce a query result](#read-and-reproduce-a-query-result)

> [!IMPORTANT]
> A field marked `known` means evidence is attached; it does not mean the
> paper's theorem is mathematically verified. Distance bounds, review states
> and Lean (deferred) remain separate evidence dimensions.

## What the workspace stores

| Layer | Contents |
| --- | --- |
| Original sources | `archive/` keeps submitted package bytes by SHA-256 and receipts with the original filename and claim time. The registry tracks the source tree, selected entry point, processing outcome, and upstream work and version when known. A failed extraction can still have a registered `source_artifact`. |
| Source graph | Parsed LaTeX files and blocks such as definitions, theorems, proofs, equations, tables, and figures. Nodes carry source paths, line and character spans, and content hashes. Edges capture structure, references, and explicitly qualified proof or dependency relations. |
| Research records and assets | Typed records for QEC objects, experiments, and software, plus exact revision links and field-level evidence. Registered assets such as matrices, circuits, or data files have byte lengths and content hashes. Queries expose assets bound to eligible records. |
| Releases and status | `machine/` stores immutable releases, source snapshots, records, and query indexes. Operational status reports package counts and whether the generated views are current. |
| Human views | `human/Index.md` and `human/generated/` are derived Obsidian pages. Personal notes live in `human/notes/`. Workspace MCP reads from `machine/`. |

Importing a paper creates the source graph for supported TeX and can generate
`code_mention` proposals for recognized parameter notation. A proposal carries
its source location and any unresolved fields. Structured code parameters,
distance bounds, experimental conditions, and performance points depend on
explicit records and evidence. Source links preserve what the paper reports.
Mathematical checks and semantic review carry separate evidence. Lean is
deferred in 0.4.x; any experimental Lean fixture is not a verification claim.
[Graph semantics and data contracts](../design/DESIGN.md#4-data-contracts)

## Research record types

The code examples use the bundled 13-qubit hypergraph-product (HGP) example
to illustrate `qecgraph.research.v1` records. The experiment below uses
hypothetical settings and counts. [Bundled HGP example](../../examples/paper/sections/hgp.tex)

### Papers and codes

| Record kind | Example |
| --- | --- |
| `paper_version` | Stores `work_id`, `upstream_version`, and `source_snapshot_id`. An arXiv paper's `v2` and `v3` can have distinct source snapshots under the same work ID. |
| `code_mention` | In a supported paragraph such as “A CSS quantum code has parameters `[[13,1,3]]`”, import can propose `n_data: 13` and `k_logical: 1`, preserve the full notation and its source span, and leave `code_ref` and `distance_interpretation` unresolved. |
| `classical_seed` | Describes a classical input, such as the binary length-three repetition code with a `2 × 3` parity-check matrix. |
| `code_family` | Describes the class of ordinary hypergraph-product codes. A family can contain many instances with different seed choices. |
| `construction` | Specifies the recipe for building HGP checks from two repetition seeds. A reconstructable `matrix_recipe` includes the field, shape, indexing, bit order, formula, recipe version, and exact seed revisions. |
| `code_instance` | Identifies the particular quantum code constructed from those seeds, with `n_data: 13`, `k_logical: 1`, and links to its construction, presentations, and distance claims. |
| `code_presentation` | Records a concrete representation of the instance, such as its `H_X` and `H_Z` check-matrix assets and qubit order. Check-weight statistics specify the check set, sector, and scope, such as X stabilizers. |
| `distance_claim` | Binds a subject and a metric. For a joint CSS distance of 3, `relation: "exact"` has `lower_bound: 3` and `upper_bound: 3`. A weight-3 logical witness supports `relation: "upper_bound"` with `lower_bound: null`. |

These records let you follow a paper's notation to a specific instance once
`code_ref` is resolved, then inspect the matrices and the evidence for its
distance. The historical HGP example includes a finite enumeration check.
[Finite distance example](../../legacy/knowledge_starter/records/claim_rep3_hgp_distance.json)

### Circuits, experiments, and results

Suppose a paper describes a simulation of that code with three syndrome
rounds and reports a logical failure rate at `p = 0.005`.

| Record kind | Example |
| --- | --- |
| `circuit_protocol` | Links the code presentation to the three-round syndrome circuit, with its circuit asset and boundary conditions when supplied. A depth measurement gives its counting rule and unit, such as `two_qubit_layers` in `layers`. |
| `noise_model` | Describes where errors occur, such as two-qubit depolarizing noise after each CNOT. It records whether idle errors, loss, erasure, and leakage are included or excluded when the source establishes this. An unresolved channel field stays `null`. |
| `noise_instantiation` | Binds the model to the circuit and stores `reported_coordinates`, such as `{"p": 0.005}`. Fill `resolved_channel_parameters` when the source establishes what that axis value means for the gates or other channels. |
| `decoder_configuration` | Binds the decoding algorithm and the settings used for this experiment, such as minimum-weight perfect matching with a specified weighting rule. |
| `hardware_assumptions` | Records assumptions such as which qubits can interact and whether all CNOTs have the same duration, when the paper specifies them. |
| `reported_experiment` | Links the paper revision, code, presentation, circuit, noise model, and decoder. An exact link identifies which circuit and decoder the reported result belongs to. |
| `metric_definition` | Defines the event, denominator, and unit, such as a wrong final logical parity per accepted shot, expressed as a fraction. A per-round rate has its own metric definition. |
| `performance_series` | Groups points on the same curve, such as logical failure rate versus `p` for the three-round experiment. It links the exact experiment and metric revisions. |
| `performance_point` | Links the experiment, noise instantiation, metric, and optionally the series. For 20 failures in 10,000 shots with zero discards, the value is `0.002`. In real records, the reported value, counts, and confidence interval each need an exact source locator when supplied. |
| `execution_environment` | Describes the environment of an actual run, such as the operating system, CPU architecture, interpreter, and dependency versions. |
| `execution_run` | Ties a specific execution to its environment and execution evidence, such as a saved log and output hash. A local reproduction can link back to the reported experiment through `reported_experiment_ref`. |

The synthetic fixture shows how partial data is stored. `demo:noise-point`
has the axis coordinate but leaves the channel mapping unresolved. The
linked `demo:point` has `value: null` because the fixture supplies no logical
failure rate. [Linked synthetic fixture](../../tests/fixtures/performance_context.synthetic.json)

### Software and algorithms

| Record kind | Example |
| --- | --- |
| `algorithm` | Minimum-weight perfect matching (`MWPM`) identifies the method that a `decoder_configuration` can reference. |
| `software_project` | `software:stim` identifies the Stim project and its repository. |
| `software_distribution` | The `stim` package in the `pypi` ecosystem links back to the project through `project_ref`. |
| `software_release` | Stores an exact package version, for example `version: "1.2.3"` when a manifest pins that version. Its `distribution_ref` identifies which package it belongs to. |
| `software_usage` | A citation can use `usage_kind: "citation"`. If the methods section explicitly says Stim simulated a particular experiment, `source_reported_use` binds that paper and experiment. `locally_observed_use` binds a real run. Keep `release_ref: null` when the version is unknown. |
| `software_catalog_observation` | Captures a dated observation such as the repository's `archived` and `disabled` flags from a metadata refresh. The field evidence links the catalog source that recorded the API URL and response hash. |
| `catalog_source` | Identifies the catalog or upstream metadata source and its checked scope. For example, the bundled seed records that its coverage is non-exhaustive. |

Importing the bundled catalog creates catalog, project, distribution, and
algorithm records. A usage record needs evidence of what the paper or run
actually used, including the version when available. [Bundled software catalog](../../qecgraph/catalog/software_catalog.seed.json)

### Fields, revisions, and evidence

Each `qecgraph.research.v1` record has a `schema_version`, stable `id`, exact
`revision`, `kind`, `data`, `field_evidence`, and `is_synthetic` flag. A
reference such as `{"id": "demo:source", "revision": "r1"}` names the exact
source revision. Evidence can also specify the source location and the limits
of the extraction or check. In this excerpt from the synthetic code example,
the fixture supplies the qubit count, and the construction is still unknown.

```json
{
  "data": {"n_data": 13, "construction_ref": null},
  "field_evidence": {
    "/data/n_data": {
      "status": "known",
      "source_ref": {"id": "demo:source", "revision": "r1"},
      "method": "synthetic_fixture"
    },
    "/data/construction_ref": {"status": "not_extracted"}
  }
}
```

Use `null` for unknown fields. `not_extracted` indicates unfinished
extraction. `unresolved` can indicate an ambiguous link. `not_reported`
requires a dated check of a specified part of the source. `not_applicable`
and `conflicting` record why the field has no single value. Default workspace
queries filter synthetic records and stale provider approvals. Legacy
`qecgraph.record.v3` records can also carry claims and evidence, plus
experimental Lean mapping fields. Lean is deferred and is not part of the
supported 0.4.x workflow; see [the design note](../design/DESIGN.md#10-lean-deferred-not-supported).
The research schema lists the supported kinds, the fields that must be present
for each kind, and the shape of nullable `{id, revision}` links. Its
`x-qec-target-kinds` annotations describe the allowed target kinds. A JSON
Schema validator also checks evidence metadata, managed asset IDs, and
portable value constraints such as matrix recipes, code parameters, bound
direction, measurement units, and rates.
QEC Graph checks consistency between related values, that the exact target
revision is present, that the pointer resolves to the value, and that the
records agree.

[Research record schema](../../qecgraph/validators/schemas/research.v1.schema.json) · [Legacy record schema](../../qecgraph/validators/schemas/record.v3.schema.json)

## Search by keyword, source, or structured fields

The CLI and MCP use the same read-only workspace tools. Use these names in
your MCP client or pass them to `qec-graph query-tool` with JSON arguments.

| Goal | Tools | How to start |
| --- | --- | --- |
| Find a term, label, source, or record | `qecgraph_search` | Pass `query` and optionally `kind`, `limit`, and `offset`. The workspace search matches keywords case-insensitively. Use `kind: "code_mention"` to focus on notation proposals. |
| Read a record and follow its links | `qec_get_entity`, `qec_get_context` | Pass the result's `id` as `identifier`. Supply `revision` to select an exact research record when several revisions are available. |
| Read the original passage or asset | `qec_get_source`, `qec_get_asset` | Use the registered source occurrence ID or a record's asset ID. Source ranges use half-open Unicode code point offsets. Asset ranges use byte offsets. |
| Inspect graph nodes and dependencies | `qecgraph_show`, `qecgraph_context`, `qecgraph_deps`, `qecgraph_impact` | Use the graph node ID or a unique label. `deps` follows what a result depends on. `impact` follows what depends on it. Inspect edge status before relying on a candidate or historical link. |
| Filter code instances | `qec_find_codes` | Use `n_min` or `n_max` to filter code size. For a hard distance bound, specify the metric ID and choose a sector (`joint` by default). The default `verified` policy requires current bound evidence and accepts an exact `metric_revision`. The `source_reported` policy requires `metric_revision` for hard distance filters. |
| Find performance points | `qec_find_performance` | Filter by `code_id`, `decoder_id`, `noise_model_id`, or `metric_id`. Use `complete_only: true` for points with the required context bound. Coordinate selection supports exact or nearest reported points and returns the actual reported coordinate. |
| Find software or an algorithm | `qec_find_software` | Search by `query` or `role`. A project entry describes the catalog. Follow its usage records for evidence that a paper or run used it. |
| Inspect workspace status | `qec_workspace_status` | Pass `{}` to read the latest recorded operational status alongside the connection's fixed knowledge release. If the operational report is missing or malformed, `operational_status` is `null`; the fixed release and its coverage are still returned. |

For example, after importing the bundled paper, search for HGP.

```sh
qec-graph query-tool qecgraph_search --workspace . --arguments /dev/stdin <<'JSON'
{"query":"HGP","limit":5}
JSON
```

Copy a result's `id` into `qec_get_entity`. For a graph hit with a source span,
pass its occurrence ID to `qec_get_source` to retrieve the exact LaTeX. MCP
clients can also list and read registered passages by their `qec://source/`
resource URIs. In the CLI, use `--revision` with workspace `query show` or
`query context` to select an exact research record revision. The CLI also
offers direct commands for structured queries.

```sh
qec-graph query codes --workspace . --n-min 10 --n-max 100 --limit 5
qec-graph query performance --workspace . --coordinate-name p --coordinate 0.01 --selection exact
qec-graph query software --workspace . --query Stim --limit 5
```

Pass `--release RELEASE_ID` to repeat a query against the same workspace release.
Use `--machine` to query a mounted machine directory directly.

A workspace populated only by paper imports can contain notation proposals
and source passages while the structured instance or performance query comes
back empty. For distance filtering, check the metric, sector, direction of
the bound, and evidence policy. For performance, compare the returned metric
definition, experiment and curve revisions, noise, decoder, and unresolved
conditions before comparing values. [Import and review records](advanced-usage.md#manage-the-obsidian-vault-and-research-records)

## Read and reproduce a query result

Use `scope` and `knowledge_snapshot` to identify the release, and `coverage`
to see what is registered or indexed. If a result is `truncated`, use its
`continuation` as the next `offset` when the tool supports paging. A response
budget can shorten a page, and the continuation starts at the next complete
result. For a source passage that exceeds the response budget, request a smaller character
range. An empty result describes the search and release you queried.

An MCP connection fixes the knowledge release at startup. Reconnect after
`sync` to read the newly published release. If the client configuration came
from `mcp-config`, regenerate it to update its explicit release ID. The CLI
also accepts `--release` to repeat a query against a particular release.
[MCP setup](../../README.md#mcp)
