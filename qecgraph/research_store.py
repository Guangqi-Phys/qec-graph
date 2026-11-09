"""Publish explicit, immutable research revisions alongside the legacy corpus."""
from __future__ import annotations

from .graph import canonical, hash_text, read_json
from .research import key, ref, validate_bundle
from .store import safe_relative, validate_snapshot
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


def validate_sources(registry, state, records, *, require_source=True):
    """Resolve verified locators through registered graph identity, never paths supplied by a record."""
    from .workspace import HEX
    graphs = {}
    for record in records:
        if record['is_synthetic']:
            continue
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
            if digest not in graphs:
                snapshot = safe_relative(registry.root, 'source_snapshots/' + digest)
                validate_snapshot(snapshot, digest)
                graph = read_json(snapshot / 'graph.json')
                graphs[digest] = (graph['project_id'], {n['id']: n for n in graph['nodes']})
            project_id, nodes = graphs[digest]
            node = nodes.get(locator.get('node_id'), {})
            span = node.get('source') or {}
            a, b = locator.get('char_start'), locator.get('char_end')
            if (project_id != version['project_id'] or node.get('origin') != 'parser'
                    or node.get('content_sha256') != locator.get('node_content_sha256')
                    or span.get('path') != locator.get('path') or type(a) is not int or type(b) is not int
                    or not span['char_start'] <= a < b <= span['char_end']):
                raise ValueError('Source evidence does not resolve to a verbatim registered span')
        if record['kind'] == 'paper_version' and require_source:
            if record['id'] not in state['versions'] or record['data'].get('source_snapshot_id') != record['revision']:
                raise ValueError('Paper version records must refer to a registered source projection')


def stage_records(registry, state, records):
    previous = load_records(registry, state)
    indexed = {key(ref(row)): row for row in previous}
    for record in records:
        identity = key(ref(record))
        if identity in indexed and indexed[identity] != record:
            raise ValueError('Research revision already binds different content')
        indexed[identity] = record
    validated = validate_bundle(indexed.values())
    validate_sources(registry, state, (validated[key(ref(record))] for record in records))
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
