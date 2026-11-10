# Corpus: registration, identity and queries

> **Status: Current for the legacy corpus surface.** The workspace surface is the primary product; see the [workspace guide](../user/workspace.md).

> **English** · [中文](corpus.zh-CN.md)

> [!NOTE]
> This is the legacy multi-document corpus surface. The workspace has its own
> machine release format; do not point both at the same directory.

## On this page

- [Canonical records and source mapping](#canonical-records-and-source-mapping)
- [Fixed-revision queries](#fixed-revision-queries)
- [Explicit migration and assets](#explicit-migration-and-assets)

The original single-project store and CLI remain compatible. Corpus maintains
multi-document identity in a separate directory:

```bash
qecgraph ingest examples/paper/main.tex --project-id demo --out build/demo
qecgraph register --corpus build/corpus --store build/demo --work-id work:demo --source-version-id version:demo:1
```

`work_id` and `source_version_id` must be supplied explicitly. A title is not a
unique key. A source version cannot be rebound to changed input; a paper update
requires a new version ID. One work may keep multiple versions; each version
fixes project ID, input hash and snapshot ID.

`CURRENT.json` points to exactly one immutable `states/<revision>.json`; the
state content is hashed as canonical JSON with
`ensure_ascii=False,sort_keys=True,separators=(',',':')`.
`Registry.read(revision)` can read historical states. A writer lock and atomic
pointer enforce the publication boundary. A crash may leave a complete but
unreferenced object; the old pointer never points at a half-written state.

Import copies and verifies the existing extraction snapshot into
`source_snapshots/<snapshot_id>/`. Moving the original store or paper later does
not change stored locators. This preserves the source that was actually
extracted; unread original project files still need separate preservation. The
migrator explicitly attaches old catalog external assets; registration does not
claim those assets were copied.

Runtime boundary: local POSIX filesystem (macOS/Linux), one writer and many
snapshot readers; distributed filesystems and Windows file locks are not
claimed.

## Canonical records and source mapping

```bash
qecgraph record-add examples/claim.example.json --corpus build/corpus
qecgraph claim-link examples/claim-link.example.json --corpus build/corpus
```

P1 introduced `qecgraph.record.v2`; new P2 writes use strict
`qecgraph.record.v3`, with migration described in the [review guide](review.md).
The author supplies `id` and `revision`; the program fills content hashes and
protocol fields. The same ID/revision cannot overwrite different content; a new
revision preserves the old file. Different IDs remain independent even when
their titles and parameters match. Automatic input defaults to
`review.status=proposed`; import or syntax parsing is not human review.

`normalizes_to` is the added registry relation that represents an explicit
mapping between a source block and an independent claim. Each mapping binds the
source version, snapshot, exact node and both hashes, claim revision, assumptions
and notation scope. Many-to-many mappings are allowed; this does not turn a
source lemma into a claim and does not claim the two statements are equivalent.
Existing graph.v1 relation meanings are unchanged. Unknown schemas are rejected
and require an explicit migration; new records do not reinterpret old formats.

## Fixed-revision queries

```bash
qecgraph search HGP --corpus build/corpus --limit 10
qecgraph show 'version:demo:1::thm:hgp-length' --corpus build/corpus
qecgraph context claim:demo:hgp-length --corpus build/corpus --include-candidates
qecgraph show thm:hgp-length --corpus build/corpus --source-version-id version:demo:1
```

Use `source_version_id::selector` for cross-document labels and raw node IDs; the
returned occurrence ID contains the source-version namespace and can be reused
directly. Different versions keep separate source occurrences even when raw node
IDs match. Entity IDs do not receive a source namespace. When candidates are not
requested, proposed source mappings are not added to context as confirmed
relations. After a claim revision, old mappings remain but are stale; the
candidate switch cannot revive them.

Every corpus query first pins one registry revision, then builds a read-only
projection and calls the shared query layer. The returned scope lists source
versions, exact snapshots and entity revisions. Replay a historical query with
`--registry-revision <returned value>`; the original store query adds
`--snapshot <snapshot_id>` and does not follow later CURRENT changes. In Python,
use `corpus.execute(...)`, `Registry.read(revision)` or `store.pin_snapshot(...)`.

Corpus search currently uses deterministic case-insensitive substring matching
and reports limit truncation; the original single store keeps SQLite/FTS5. An
empty result only means no hit within the pinned scope. Queries do not write
records, run source code or promote mathematical evidence.

## Explicit migration and assets

```bash
qecgraph migrate legacy/knowledge_starter/records --source-root legacy/knowledge_starter --out build/migration
qecgraph migration-import build/migration --corpus build/corpus
qecgraph context code:rep3-hgp:13 --corpus build/corpus
```

Migration output must be a separate new directory. `migration-report.json`
records input byte hashes, schemas, ID/revision mappings, accepted and rejected
items; original bytes are stored under `originals/`; unknown versions remain
opaque input and are refused interpretation. Any rejection makes migration exit
2, and import rejects a batch with unresolved rejections.

Old `0.1.0` records enter the current version through a separate envelope,
preserving the original ID, all record fields, original evidence categories and
not-executed status. Old refs use the `catalog:` prefix so they are never
implicitly promoted to review dependencies. When an old claim does not state a
quantifier, it becomes null with a reason. `qecgraph.graph.v1` and
`qecgraph.annotations.v1` use byte-preserving passthrough adapters, preserving
source-block and review-binding meaning; a source theorem is not converted into
a claim. Use register for cross-document access to a complete store.

Relative asset paths in old records require an explicit `--source-root`; never
guess relative to the new store. Migration verifies old byte hashes and the old
`ensure_ascii=True` canonical hash, preserves the old protocol marker, and copies
assets as `qecasset:sha256:<digest>`. Actual paths in records are replaced by
managed URIs while the original fields remain in `legacy_record`. Import copies
complete assets before atomically publishing registry state; moving the corpus
does not break URI resolution. `Registry.asset_bytes(uri)` verifies exact bytes
and errors on corruption or absence. Migration never runs an import script. Back
up old originals and the migration report together; rollback reads an old
registry revision and does not delete new objects.
