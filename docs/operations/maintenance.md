# Legacy store and corpus maintenance

> **Status: Current for the legacy store/corpus surface; not the workspace daily guide.**
> Workspace daily operations are in [the workspace guide](../user/workspace.md). This page
> retains source changes, failure propagation, backups and recovery for the single-paper
> store and corpus commands that remain supported for compatibility.

> **English** · [中文](maintenance.zh-CN.md)

Daily workspace operations use `init`, `sync`, `status` and `validate`; see the
[workspace guide](../user/workspace.md). Before operating, read this package's
`AGENTS.md`, the [architecture](../design/DESIGN.md#2-system-overview) and the
[data contracts](../design/DESIGN.md#4-data-contracts). Run the commands below
from the package root and complete each step before the next.

## On this page

- [1. First install and baseline](#1-first-install-and-baseline)
- [2. Daily ingest and queries](#2-daily-ingest-and-queries)
- [3. Order of operations for every change](#3-order-of-operations-for-every-change)
- [4. Failure propagation and review](#4-failure-propagation-and-review)
- [5. Index rebuild and atomic publication](#5-index-rebuild-and-atomic-publication)
- [6. Schema migration and rollback](#6-schema-migration-and-rollback)
- [7. Backup and recovery drill](#7-backup-and-recovery-drill)
- [8. Optional container deployment](#8-optional-container-deployment)
- [Primary sources](#primary-sources)

> [!WARNING]
> This page covers the **legacy store/corpus** surface. The primary workspace
> workflow is in [the workspace guide](../user/workspace.md); do not mix the
> two pointer formats or lock domains.

## 1. First install and baseline

A local POSIX filesystem, Python 3.11 or newer and working SQLite FTS5 are required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

Installation needs the relevant package sources. Record the actual Python,
SQLite, OS and installed dependencies; do not assume the example environment is
already installed. Runtime dependencies are pinned to `pylatexenc==2.10` and
`jsonschema==4.26.0`; upgrade the parser in a separate commit and inspect the
semantic output diff. The legacy knowledge sample can be verified independently;
the call below also recomputes a finite HGP instance and does not invoke Lean:

```bash
python legacy/knowledge_starter/tools/qec_kb.py verify
```

Use `verify --json-schema` to opt into schema checks for the old sample. The
references, assets and computation checks in a normal verify run must not be
reported as "full JSON Schema validation was performed".

## 2. Daily ingest and queries

First save the complete original project in a managed location; this example
uses the demo input shipped with the repository.

```bash
qecgraph ingest examples/paper/main.tex --project-id qec-demo --out build/demo --annotations examples/annotations.example.json
qecgraph validate --store build/demo
qecgraph show thm:hgp-css --store build/demo
qecgraph deps thm:hgp-css --store build/demo
qecgraph context thm:hgp-length --store build/demo
```

Use the `qecgraph split` workflow described in the [splitter reference](../user/splitter.md)
when you only need source blocks. To load the legacy knowledge sample, add
`--catalog legacy/knowledge_starter/records` to ingest; it imports JSON records
only. The matrices, validation scripts and reports referenced by those records
remain in the complete `legacy/knowledge_starter/` tree and must be preserved.

For every run, record the input path, command, exit code, snapshot ID and
diagnostics. Exit code 2 means extraction is partial; even if a snapshot was
produced, do not claim complete extraction. `validate` checks hashes, locators,
edge endpoints and SQLite consistency; it does not verify theorems, matrix
semantics or Lean proofs. Queries exclude candidates, stale and unbound
dependencies by default; inspect candidates explicitly with
`--include-candidates`. Pin one snapshot ID for an AI work task; if CURRENT
changes, decide whether to continue the old task or rebuild the context. Use
`--snapshot <id>` or the corpus `--registry-revision <revision>` for consistent
reads and check the returned scope.

## 3. Order of operations for every change

1. Identify the authoritative file for each field; edit JSON, sidecars or source,
   never generated nodes or SQLite.
2. Record the current Git commit and input asset inventory, and save the original
   files; a new paper version creates a new SourceVersion.
3. Change the record, preserving the distinction between source and normalised
   text, and list new or changed assumptions.
4. Run the relevant structural and reference checks plus a meaningful regression;
   numeric results use their dedicated verifier.
5. Generate a snapshot in a staging output directory, read diagnostics and
   validate it; do not replace the production query surface with a trial run.
6. Review semantics, update necessary bindings, then generate the same input in
   the production store and publish.
7. Commit human records and code, archive important reports, and link the
   release commit, input inventory and snapshot ID.

Default ingest publishes a partial snapshot after integrity validation; use
`--strict` for production, where partial results stay in staging and CURRENT is
unchanged. See [incremental and watch](../design/DESIGN.md#73-incremental-and-watch).
The same input, configuration, tool source and dependency fingerprint should
reuse the same snapshot ID. Published snapshots are read-only; if corruption is
found, preserve the scene and rebuild from the input into a new store. Never edit
the manifest to hide corruption.

## 4. Failure propagation and review

| What changed | Minimum review scope |
|---|---|
| Source theorem or definition | Normalised claims, semantic review and dependencies (and experimental Lean mapping; deferred) |
| Matrix or column order | Rank, commutation, logical representatives, distance evidence and SECs depending on that representation |
| Circuit / noise / decoder | Input identity, result comparability, relevant statistics and plots |
| Checker code or configuration | Applicability of its evidence and results that must be rerun |
| Lean type or imports (experimental) | Deferred; not part of the supported recovery/verification flow |
| Splitter or embedding model | The corresponding query projection; permanent source identity is unchanged |

Legacy sidecars bind reviews by project source hash; the corpus binds records by
revision, source version and assets. Even an unrelated paragraph change may
conservatively mark an old sidecar review stale. Per-file AST reuse and watch
are implemented, but semantic projections are rebuilt each time; there is no
general incremental dependency closure for domain outputs yet. Target task
manifests should record input ID + revision + hash, processor version,
configuration, outputs and dependency edges. Build the complete dependency
closure before propagating changes; unresolved dependencies must explicitly
block a "everything is still valid" conclusion. Use
[data contracts](../design/DESIGN.md#4-data-contracts) for dependency direction
and reverse-impact queries; do not treat every ordinary reference as a proof
dependency. Old evidence stays attached to its old input and is not deleted when
it becomes stale; new and old results are connected by successor relations. A
review update must re-compare statement, assumptions and dependencies, not merely
replace the expected hash with a new value.

## 5. Index rebuild and atomic publication

SQLite, FTS and vector indexes are generated from authoritative records. Build
and validate a new index completely in a temporary directory, then switch the
entry point. The current implementation creates a complete snapshot first and
then atomically replaces `CURRENT.json`; a local POSIX writer lock rejects
cross-process concurrent writes. Use `recover-store` to inspect publication
state; see [incremental and watch](../design/DESIGN.md#73-incremental-and-watch).
Never mix the relational tables of one snapshot with the full-text or vector
data of another.

A new index records the source snapshot, schema, model version, dimension,
normalisation, configuration and input text hashes. Chinese recall, theorem
integrity, parameter hard filters and source locators all enter query
regression; vector similarity does not determine evidence level. Re-ingest the
saved complete input into another store to rebuild the projection. If SQLite
later stores unique data that cannot be rebuilt, use a consistent snapshot or
the official Backup API to back up a running database.[1]

## 6. Schema migration and rollback

First decide whether a change affects record structure, field meaning, hash
protocol, graph view or execution environment. Implement a one-way migration on
a dedicated branch and copy, preserving the old schema, old data and conversion
mapping. The migration report records at least input/output versions, processed
count, rejected records, ID mapping and field-meaning changes. Check required
fields, enums, unique IDs, referential integrity, asset hashes, review bindings
and representative queries. Add a definition revision when a mathematical metric
or unit changes; never reuse old evidence by only renaming a field. Migrate old
`0.1.0` records and `qecgraph.graph` separately; they are not one version axis.
Preserve the protocol identifier while old and new canonicalisation coexist; do
not batch-recompute hashes and claim old reviews remain valid. Validate at the
new output location before switching readers; update writers at the same time so
old writers cannot keep producing the old format.

There is no in-tree legacy record migration; register current-format records or
restore a backup. old formats into a new directory. For rollback, prefer a verified historical
snapshot or registry revision; if necessary restore the whole store and the
matching input/tool versions. If a maintainer manually rolls back CURRENT, stop
writers, validate the target snapshot, then atomically replace it using the
existing pointer format. The pointer contains `format: qecgraph.current`, the
target `snapshot_id` and `path: snapshots/<snapshot_id>`. Do not delete new
snapshots to perform a rollback; preserve failure evidence and the rollback
reason. If a database migration is irreversible, restore a backup copy. Record
the exact snapshot used for a rollback; "latest" is not a reproducible reference.

## 7. Backup and recovery drill

| Must back up | Why |
|---|---|
| Git history, human JSON, sidecars, notes, schema and source | Human decisions and traceable changes |
| Complete original paper projects, PDFs, upstream code and asset inventories | Extraction snapshots do not retain every source-project resource |
| Matrices, certificates, manual corrections and expensive results | Cannot be recreated automatically from a Git remote or summary |
| Run configuration, raw statistics, execution environment and evidence | Re-check estimators and applicable inputs |
| Published snapshots and reports, or enough complete rebuild inputs | Restore a referenced query state |
| Complete `legacy/knowledge_starter/` | Catalog import does not copy its referenced assets |

Backup is not Git push; untracked large files and container volumes need a
separate inventory. Save human changes daily, save results immediately after an
important run, and keep at least one backup in an independent failure domain.
This is an operations policy; retention depends on data size, recomputation cost
and acceptable data loss. Encryption and access control follow the actual
material; credentials never enter records, images or public archives.

Run a recovery drill in this order:

1. Restore the specified Git commit, all assets, inventories and published store
   into an empty directory; do not overwrite a directory still in use.
2. Verify original asset byte hashes and confirm that source versions, sidecars
   and catalog-relative paths resolve.
3. Run `qecgraph validate --store <restored-store>` and inspect diagnostics and
   integrity.
4. Re-ingest archived inputs with the corresponding tool versions in another
   directory and compare nodes, source locators and the expected snapshot.
5. Re-run key structured queries and bounded context; for the legacy sample run
   `python legacy/knowledge_starter/tools/qec_kb.py verify`.
6. Lean is deferred; do not include it in current recovery acceptance. Read
   experimental records only as history and do not claim verification.
7. Record recovery duration, missing assets, differences and fixes; switch the
   production read entry only after they pass.

If a recovery test fails, first fix the backup or the procedure; never mark
"recoverable" merely because the backup job exited successfully.

## 8. Optional container deployment

`Dockerfile` and `compose.yaml` are provided for the research CLI only; this
delivery did not build or run Docker. The template base image is
`python:3.12-slim`; `QEC_PYTHON_IMAGE` can select an actually verified digest.
The floating tag is not a complete environment lock. The template mounts
`./examples/paper` read-only at `/input`, `./build/container` at `/output`, and
runs split by default. The runtime UID/GID come from `QEC_UID/QEC_GID`, default
1000; the output directory must already exist and be writable by that user. The
runtime uses a read-only root filesystem, disables networking and mounts `/tmp`
as tmpfs; image build still needs dependency access or an existing cache. A
future research image should add system dependency locks. Lean is deferred;
there is no supported Lean image or acceptance. Add a parser service only when
PDF parsing is needed, retaining input limits and a separate output directory.

| Path role | Mount and lifetime |
|---|---|
| Original assets, published matrices/evidence | Read-only mount |
| Human records | Read-only for query/check; use a separate Git worktree for edits |
| New results and run reports | Explicit persistent output mount |
| SQLite/index and Lean build cache | Separate rebuildable directory or volume |
| Temporary unpacked/parsed files | Separate temporary directory, cleaned after use |

The Docker writable layer disappears with the container; volumes have an
independent lifetime. Permanent results must go to a managed persistent mount.[2]
Use a bind mount for source that must be edited on the host; use a named volume
for service databases and include it in backups. Never make the Docker socket,
host credentials or the whole data directory a default writable mount for a
parser task. Fill in a digest only after an image has been selected and actually
run; offline reproduction also needs obtainable images or build inputs. Run the
same baseline and recovery checks inside the container; a successful container
start does not prove data or mathematical conclusions. Adopt PostgreSQL only
when sustained multi-writer or remote transactions become a requirement; see
the official SQLite guidance for local and concurrency boundaries.[3]

## Primary sources

1. [SQLite Backup API](https://www.sqlite.org/backup.html)
2. [Docker storage](https://docs.docker.com/engine/storage/)
3. [When to use SQLite](https://www.sqlite.org/whentouse.html)
4. Actual implementation in this package: `qecgraph/store.py`, `qecgraph/cli/`, `tests/`.
5. Legacy sample and evidence: `legacy/knowledge_starter/tools/qec_kb.py`, `legacy/knowledge_starter/docs/VALIDATION.md`.
