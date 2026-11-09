# Data and search

QEC Graph keeps the original sources, the graph extracted from them, and
versioned research records. Search results refer to the machine release that
served the query, so you can trace a result back to the same data later.

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
Mathematical checks, semantic review, and Lean builds carry separate evidence.
[Graph semantics](02_QEC_GRAPH_SPEC.md) · [Field and evidence conventions](04_DATA_FORMATS.md)

## Research record types

| Category | Record kinds | What they describe |
| --- | --- | --- |
| Paper | `paper_version` | The registered work, upstream version, and source snapshot. |
| Codes and constructions | `code_mention`, `classical_seed`, `code_family`, `construction`, `code_instance`, `code_presentation`, `distance_claim` | Reported notation, classical inputs, families and construction recipes, individual codes, check representations, and distance claims with their metrics, bounds, and assumptions. |
| Circuits, noise, and decoders | `circuit_protocol`, `noise_model`, `noise_instantiation`, `decoder_configuration`, `hardware_assumptions` | Circuit or measurement protocol, noise model and concrete parameters, decoder settings, and hardware conditions. |
| Experiments and results | `reported_experiment`, `metric_definition`, `performance_series`, `performance_point`, `execution_environment`, `execution_run` | What the source reports, what the metric measures, the observed values and coordinates, and the environment and evidence of a recorded run. |
| Software and algorithms | `software_project`, `software_distribution`, `software_release`, `software_usage`, `software_catalog_observation`, `catalog_source`, `algorithm` | Projects and algorithms, packages and versions, observed metadata, and software usage tied to a paper, experiment, or run. |

Each `qecgraph.research.v1` record has a `schema_version`, stable `id`, exact
`revision`, `kind`, `data`, `field_evidence`, and `is_synthetic` flag. References
bind both an `id` and a `revision`. Evidence for a data field can include the
source revision, source location, method, and limits. An unknown field uses
`null` with a state such as `not_extracted`, `unresolved`, `not_reported`,
`not_applicable`, or `conflicting`. Default workspace queries filter synthetic
records and stale provider approvals. Legacy `qecgraph.record.v3` records can
also carry claims, evidence, and Lean mappings in a migrated workspace.
[Research record schema](../qecgraph/validators/schemas/research.v1.schema.json) · [Legacy record schema](../qecgraph/validators/schemas/record.v3.schema.json)

## Search by keyword, source, or structured fields

The CLI and MCP use the same read-only workspace tools. Use these names in
your MCP client, or run `qec-graph query-tool` from the workspace root.

| Goal | Tools | How to start |
| --- | --- | --- |
| Find a term, label, source, or record | `qecgraph_search` | Pass `query` and optionally `kind`, `limit`, and `offset`. The workspace search matches keywords case-insensitively. Use `kind: "code_mention"` to focus on notation proposals. |
| Read a record and follow its links | `qec_get_entity`, `qec_get_context` | Pass the result's `id` as `identifier`. Supply `revision` to select an exact research record when several revisions are available. |
| Read the original passage or asset | `qec_get_source`, `qec_get_asset` | Use the registered source occurrence ID or a record's asset ID. Source ranges use half-open Unicode code point offsets. Asset ranges use byte offsets. |
| Inspect graph nodes and dependencies | `qecgraph_show`, `qecgraph_context`, `qecgraph_deps`, `qecgraph_impact` | Use the graph node ID or a unique label. `deps` follows what a result depends on. `impact` follows what depends on it. Inspect edge status before relying on a candidate or historical link. |
| Filter code instances | `qec_find_codes` | Use `n_min` or `n_max` to filter code size. For a hard distance bound, specify the metric ID and choose a sector (`joint` by default). Use `evidence_policy: "source_reported"` with an exact `metric_revision` to select qualifying reported bounds. The default `verified` policy requires current bound evidence for a hard distance filter. |
| Find performance points | `qec_find_performance` | Filter by `code_id`, `decoder_id`, `noise_model_id`, or `metric_id`. Use `complete_only: true` for points with the required context bound. Coordinate selection supports exact or nearest reported points and returns the actual reported coordinate. |
| Find software or an algorithm | `qec_find_software` | Search by `query` or `role`. A project entry describes the catalog. Follow its usage records for evidence that a paper or run used it. |
| Inspect workspace status | `qec_workspace_status` | Pass `{}` to read the latest recorded operational status alongside the connection's fixed knowledge release. |

For example, after importing the bundled paper, search for HGP.

```sh
qec-graph query-tool qecgraph_search --workspace . --arguments /dev/stdin <<'JSON'
{"query":"HGP","limit":5}
JSON
```

Copy a result's `id` into `qec_get_entity`. For a graph hit with a source span,
pass its occurrence ID to `qec_get_source` to retrieve the exact LaTeX. MCP
clients can also list and read registered passages by their `qec://source/`
resource URIs. To filter structured code instances by size, use the same
command pattern.

```sh
qec-graph query-tool qec_find_codes --workspace . --arguments /dev/stdin <<'JSON'
{"n_min":10,"n_max":100,"limit":5}
JSON
```

A workspace populated only by paper imports can contain notation proposals
and source passages while the structured instance or performance query comes
back empty. For distance filtering, check the metric, sector, direction of
the bound, and evidence policy. For performance, compare the returned metric
definition, experiment and curve revisions, noise, decoder, and unresolved
conditions before comparing values. [Import and review records](ADVANCED_USAGE.md#manage-the-obsidian-vault-and-research-records)

## Read and reproduce a query result

Use `scope` and `knowledge_snapshot` to identify the release, and `coverage`
to see what is registered or indexed. If a result is `truncated`, use its
`continuation` as the next `offset` when the tool supports paging. For a
source passage that exceeds the response budget, request a smaller character
range. An empty result describes the search and release you queried.

An MCP connection fixes the knowledge release at startup. Reconnect after
`sync` to read the newly published release. If the client configuration came
from `mcp-config`, regenerate it to update its explicit release ID. The CLI
also accepts `--release` to repeat a query against a particular release.
[MCP setup](../README.md#mcp)
