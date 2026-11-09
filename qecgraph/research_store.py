"""Publish explicit, immutable research revisions alongside the legacy corpus."""
from __future__ import annotations

from .graph import canonical, hash_text, read_json
from .research import key, ref, validate_bundle
from .store import safe_relative
from .transactions import immutable_json, writer_lock


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


def stage_records(registry, state, records):
    previous = load_records(registry, state)
    indexed = {key(ref(row)): row for row in previous}
    for record in records:
        identity = key(ref(record))
        if identity in indexed and indexed[identity] != record:
            raise ValueError('Research revision already binds different content')
        indexed[identity] = record
    validated = validate_bundle(indexed.values())
    index = state.setdefault('research_records', {})
    for identity, record in validated.items():
        identifier, revision = identity
        digest = hash_text(canonical(record))
        if revision in index.get(identifier, {}):
            continue
        immutable_json(safe_relative(registry.root, _record_path(record)), record)
        index.setdefault(identifier, {})[revision] = digest


def publish_records(registry, records):
    with writer_lock(registry.root):
        state, previous = registry.read()
        if not state.get('workspace_id'):
            raise ValueError('Research import requires an initialized workspace')
        stage_records(registry, state, records)
        release = registry._publish(state)
    return {'status': 'imported' if previous != release else 'unchanged', 'release_id': release,
            'input_records': len(records)}
