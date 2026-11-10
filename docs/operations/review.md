# Type validation, evidence and review

> **Status: Current (0.5.x) for the corpus review surface.** Workspace review/apply semantics are in the [system design](../design/DESIGN.md#6-review-evidence-and-query-eligibility).

> **English** · [中文](review.zh-CN.md)

## On this page

- [Records and schema](#records-and-schema)
- [Validation scope](#validation-scope)
- [Math plugins and hard conditions](#math-plugins-and-hard-conditions)
- [Proposals and decisions](#proposals-and-decisions)
- [Apply transactions and recovery](#apply-transactions-and-recovery)
- [Derived invalidation and logical cycles](#derived-invalidation-and-logical-cycles)

> [!IMPORTANT]
> Schema/type validation is not mathematical verification. A passed check,
> a bound distance witness, and a human review are separate evidence states.

## Records and schema

Records use the single current `qecgraph.record` format. The authoritative schema
ships with the Python package under
[`qecgraph/validators/schemas/`](../../qecgraph/validators/schemas); use that
packaged path directly. Unknown schemas are rejected and are never reinterpreted
with the current fields. New writes always produce the current format.

`qecgraph.record` also contains an experimental `lean_declaration` kind and
relation fields; Lean is deferred in 0.5.x, is not part of the supported workflow
and is not a verification conclusion. See
[system design §10](../design/DESIGN.md#10-lean-deferred-not-supported).

`jsonschema==4.26.0` is a pinned runtime dependency, not an optional validation
extra, so every write entry point performs the same structural validation. JSON
input rejects duplicate keys, NaN, Infinity and decimal exponents that overflow
to non-finite values. Top-level unknown fields must go in extensions; domain
extensions under data may remain, and specified fields are type-checked. null
requires unknown_reason; n/k cannot be negative or boolean, and k cannot exceed n.

## Validation scope

```bash
qecgraph validate --store build/demo
qecgraph validate-corpus --corpus build/corpus
```

Single-store validation adds relation endpoint types, for example `proof_of` can
only point from a proof to a statement; a wrong type fails before publication and
preserves the old CURRENT. Legacy `catalog:` relations keep their old meaning and
are not presented as review dependencies. Corpus validation also checks dangling
references, revision bindings, managed asset bytes and source integrity. Drafts
may store unresolved references, but query diagnostics and strict acceptance
report them explicitly instead of silently ignoring them. Structural/type success
does not mean a matrix is valid, a distance is proved, a human reviewed the
record or experimental Lean was built.

The tool fingerprint covers all Python submodules, packaged schemas and parser
and validation dependency versions. Changing a validator or schema produces a
new build identity; old snapshots are not reused as acceptance evidence for new
rules.

## Math plugins and hard conditions

```bash
qecgraph check-css --hx build/demo/HX.json --hz build/demo/HZ.json --lx build/demo/LX.json --lz build/demo/LZ.json --enumerate-distance
qecgraph codes --corpus build/corpus --n-min 13 --n-max 13 --distance-at-least 3 --metric-id definition:css-distance
```

The default `verified` policy accepts computed/certificate evidence; add
`--evidence-policy source_reported --metric-revision REV` to select a reported
bound explicitly. The CSS plugin supports only the binary CSS convention with +1 phase; it checks
explicit shape, coordinates, GF(2) rank, commutation and logical pairing. Finite
distance enumeration must be requested explicitly, defaults to n≤20 and has an
absolute cap of 22; k=0 is outside the domain and never fabricates a distance.
A successful run remains Python computed_exact; non-commuting matrices never
receive a valid CSS result. This interface does not run
Lean and does not write review records.

Hard filtering first matches an explicit metric_id and sector
(joint/X/Z), then checks known lower bounds for exact/lower_bound/interval;
upper_bound, unknown lower bound, missing representation or absent current
evidence never match. Evidence `data.inputs` must bind the current ID, revision
and content hash of the distance estimate, instance, representation and metric.
Related assets must also be readable with matching hashes. Existing evidence
without a claim binding remains viewable; to use it in hard filtering, inspect
the exact claim and register a new evidence revision. Output preserves evidence
categories such as source report, computation and certificate; Lean does not
participate in the supported flow. Historical samples with unstated input bindings and sectors do not satisfy
this strict filter by default; register exact evidence instead of only
refreshing hashes. `evidence_ids` lives uniquely in the record envelope.

The experimental plugin `validators.qec.check_experiment(record, metric)` or
`check-experiment <JSON>` validates error events, denominator, sector, rounds,
bounds, post-selection, timeout and input-binding structure. IID computes
failures/accepted only for an explicit accepted_shots metric and returns the
acceptance rate separately; importance/MCMC must provide estimator and sampling
information and must not reuse errors/shots. Zero failures cannot carry a zero
probability upper bound. `comparable_experiments` conservatively compares exact
inputs, configuration, metric and sampling. Empty, unknown and null-containing
configurations fail comparability. The plugin's input-version check is structural;
callers must separately resolve and verify the referenced actual records, and
the return value marks this scope explicitly.

## Proposals and decisions

```bash
qecgraph review examples/proposal.example.json --corpus build/review-demo --actor-id codex --actor-kind ai
qecgraph review-decide <返回的proposal_id> --corpus build/review-demo --actor-id codex --actor-kind ai --decision approve --rationale '结构检查接受，保持未人工审核'
```

`review` stores only a proposed proposal and diff; it does not apply the record.
For a new ID, expected_revision/hash are both null; when changing an existing ID,
the exact old revision/hash and new revision are required. The diff includes the
full statement, assumptions and dependencies. A proposal binds corpus_id, the
changed records and their explicit reference closure, source snapshots and the
asset bytes actually read. Unrelated records do not stale a decision; a changed
dependency does. Different corpora with identical content do not share
proposals. Moving a corpus preserves identity in the marker; a path is not
identity.

`review-decide` stores actor ID/kind, time, scope, rationale, decision and exact
proposal hash. AI/program approve produces only machine_accepted; the final record
remains draft/proposed. Human approve must explicitly check the statement,
hypotheses and dependencies scopes (repeat `--checked-scope`), not merely refresh
the expected hash. Identity is a local operator declaration, not authentication;
automation must not impersonate a human. A human review binds its complete
proposal and exact final record; changing statement, assumptions, dependencies or
revision invalidates the old review copy. Missing/changed assets, mismatched input
revision/hash, another corpus or a stale registry all reject the decision.

A `depends_on_reviewed` edge keeps its exact relation name and hash binding;
domain refs without a human binding are marked unbound_review and never enter
confirmed context because of declared status or include-candidates. Raw records
remain showable for review.

## Apply transactions and recovery

```bash
qecgraph apply <proposal_id> --review-id <review_id> --corpus build/review-demo
```

`apply` holds one writer lock while checking the corpus, the complete registry
baseline, the review proposal hash, current record content and actual assets, then
writes a complete new revision, performs endpoint/cross-record checks and
atomically publishes one registry state. The conservative whole-registry CAS
rejects unrelated parallel changes; re-fetch the diff and create a new proposal
rather than auto-refreshing the expected hash. A missing target or wrong type
fails the whole batch; stale historical evidence remains a visible warning and is
not deleted or rebound.

A published state records the application; an immutable receipt binds the
proposal, review, all result hashes and the published revision. Repeating apply
for the same proposal/review returns the same receipt; later updates do not
overwrite the record again. A different review cannot overwrite an already
applied proposal.

A failure or crash may leave unreferenced complete records/receipts; a receipt
file alone does not prove application. Only CURRENT pointing at a complete state
containing the application counts as published. A failed pointer write preserves
the old state; retrying the same valid input can recover. Rollback inspects
historical state/record revisions and does not delete new evidence or rewrite old
hashes. A POSIX flock conflict reports an explicit error and does not damage a
running writer.

## Derived invalidation and logical cycles

All traversals, proof attachment, structural attachment, final edge sets and
annotation output share one state policy. stale/unbound_review/unresolved are
always excluded; include-candidates only adds still-valid candidates. A valid
`depends_on_reviewed` status may be declared; data is not incorrectly required
to write reviewed.

Human decisions are immutable; queries derive review_binding from the actual
record, source and assets they bind. If a bound dependency revision/hash or asset
changes, the review becomes stale and lists the exact reason; old reviews, hashes
and evidence are never edited directly. Reading a historical registry revision
uses its original record versions; missing physical assets are reported and the
evidence is not claimed replayable. The current stale binding covers the entire
corpus known at review time, which is conservative; adding an unrelated ID does
not rewrite old decisions.

```bash
qecgraph audit-dependencies --corpus build/corpus
qecgraph audit-dependencies --store build/demo
```

Only the still-valid `depends_on_reviewed` subgraph is checked for strongly
connected components, returning node/edge IDs and open questions. Literature
citation cycles may remain; candidates, unbound edges and stale dependencies do
not enter the audit subgraph. The whole graph is not forced to be a DAG, and
problem edges are not deleted automatically.
