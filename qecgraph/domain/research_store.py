"""Publish explicit, immutable research revisions alongside the legacy corpus."""
from __future__ import annotations

from ..core.graph import canonical, hash_text, read_json
from .research import key, ref, validate_bundle
from ..store import load_validated_snapshot, safe_relative, source_span_index
from ..core.transactions import immutable_json, writer_lock


def _record_path(record):
    identifier, revision = key(ref(record))
    return 'research/' + hash_text(identifier) + '/' + hash_text(revision) + '.json'


def load_records(registry, state):
    result = []
    for identifier, revisions in sorted(state.get('research_records', {}).items()):
        for revision, digest in sorted(revisions.items()):
            binding = {'id': identifier, 'revision': revision}
            path = safe_relative(registry.root, _record_path(binding))
            record = read_json(path)
            if ref(record) != binding or hash_text(canonical(record)) != digest:
                raise ValueError('Research revision binding or hash mismatch')
            result.append(record)
    return result


def validate_sources(registry, state, records, *, require_source=True, verified_spans=None):
    """Resolve verified locators through registered graph identity, never paths supplied by a record."""
    from ..workspace import HEX
    from ..workspace_assets import references, verify_asset
    graphs = {}
    verified_assets = set()

    def snapshot_spans(digest):
        if digest not in graphs:
            snapshot = safe_relative(registry.root, 'source_snapshots/' + digest)
            indexed = verified_spans.get((snapshot, digest)) if verified_spans is not None else None
            if indexed is None:
                graph, _ = load_validated_snapshot(snapshot, digest)
                indexed = source_span_index(graph)
            graphs[digest] = indexed
        return graphs[digest]

    for record in records:
        if record['is_synthetic']:
            continue
        if record['kind'] == 'paper_version' and require_source:
            version = state['versions'].get(record['id'])
            digest, data = record['revision'], record['data']
            if (not version or not HEX.fullmatch(digest) or data.get('source_snapshot_id') != digest
                    or any(data.get(field) != version[field] for field in ('work_id', 'upstream_version'))
                    or snapshot_spans(digest)[0] != version['project_id']):
                raise ValueError('Paper version records must refer to a registered source projection')
        for uri in references(record):
            if uri not in verified_assets:
                verify_asset(registry, uri)
                verified_assets.add(uri)
        for evidence in record['field_evidence'].values():
            locator = evidence.get('source_locator')
            if locator is None:
                continue
            source = evidence.get('source_ref') or {}
            identifier, digest = source.get('id'), source.get('revision')
            version = state['versions'].get(identifier)
            if (not version or not isinstance(digest, str) or not HEX.fullmatch(digest)
                    or locator.get('source_version_id') != identifier or locator.get('snapshot_id') != digest):
                raise ValueError('Source evidence must bind a registered version and snapshot')
            project_id, nodes = snapshot_spans(digest)
            span = nodes.get(locator.get('node_id'))
            a, b = locator.get('char_start'), locator.get('char_end')
            if span is not None:
                content_sha256, path, start, end = span
                if (project_id == version['project_id'] and content_sha256 == locator.get('node_content_sha256')
                        and path == locator.get('path') and type(a) is int and type(b) is int and start <= a < b <= end):
                    continue
            raise ValueError('Source evidence does not resolve to a verbatim registered span')


def stage_records(registry, state, records, *, verified_spans=None):
    previous = load_records(registry, state)
    indexed = {key(ref(row)): row for row in previous}
    incoming = {}
    input_count = 0
    for record in records:
        identity = key(ref(record))
        existing = incoming.get(identity, indexed.get(identity))
        if existing is not None and existing != record:
            raise ValueError('Research revision already binds different content')
        incoming[identity] = record
        input_count += 1
    indexed.update(incoming)
    validated = validate_bundle(indexed.values())
    index = state.get('research_records', {})
    for identifier, revision in incoming:
        record = validated[identifier, revision]
        if (record['kind'] == 'paper_version' and not record['is_synthetic']
                and revision not in index.get(identifier, {})
                and state['versions'].get(identifier, {}).get('snapshot_id') != revision):
            raise ValueError('New paper version records must bind the current registered source projection')
    validate_sources(registry, state, (validated[identity] for identity in incoming), verified_spans=verified_spans)
    index = state.setdefault('research_records', {})
    for identifier, revision in incoming:
        if revision in index.get(identifier, {}):
            continue
        record = validated[identifier, revision]
        digest = hash_text(canonical(record))
        immutable_json(safe_relative(registry.root, _record_path(record)), record)
        index.setdefault(identifier, {})[revision] = digest
    return input_count


def publish_records(registry, records):
    with writer_lock(registry.root):
        state, previous = registry.read()
        if not state.get('workspace_id'):
            raise ValueError('Research import requires an initialized workspace')
        input_count = stage_records(registry, state, records)
        release = registry._publish(state)
    return {'status': 'imported' if previous != release else 'unchanged', 'release_id': release,
            'input_records': input_count}
