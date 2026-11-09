"""Versioned corpus registry: explicit identities, immutable source snapshots."""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path

from .graph import canonical, hash_text, read_json
from .store import current_snapshot, safe_relative, validate_snapshot
from .transactions import atomic_bytes, atomic_json, immutable_json, writer_lock
from .records import prepare_record
from .query import resolve

FORMAT = 'qecgraph.registry.v1'


def empty_state():
    return {'schema_version': FORMAT, 'works': {}, 'versions': {}, 'records': {}, 'links': []}


class Registry:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def read(self, revision=None):
        if revision is None:
            pointer = read_json(self.root / 'CURRENT.json')
            if pointer.get('format') != 'qecgraph.registry.current.v1':
                raise ValueError('Not a corpus registry pointer')
            revision = pointer['revision']
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
            raise ValueError('Invalid registry revision')
        state = read_json(self.root / 'states' / (revision + '.json'))
        if state.get('schema_version') != FORMAT or hash_text(canonical(state)) != revision:
            raise ValueError('Registry state schema/hash mismatch')
        return state, revision

    def _state_or_empty(self):
        existing = (self.root / 'CURRENT.json').exists()
        state = self.read()[0] if existing else empty_state()
        marker = self.root / '.qecgraph-registry.json'
        if marker.exists():
            identity = read_json(marker)
            if identity.get('format') != FORMAT:
                raise ValueError('Incompatible registry marker')
        else:
            if not existing and any(p.name != '.writer.lock' for p in self.root.iterdir()):
                raise ValueError('Registry must be initialized in an empty directory')
            identity = {'format': FORMAT}
        if not identity.get('corpus_id'):
            identity['corpus_id'] = 'corpus:' + str(uuid.uuid4())
            atomic_json(marker, identity)
        if state.get('corpus_id', identity['corpus_id']) != identity['corpus_id']:
            raise ValueError('Corpus identity differs from its marker')
        state['corpus_id'] = identity['corpus_id']
        return state

    def prepare_publication(self, state):
        revision = hash_text(canonical(state))
        immutable_json(self.root / 'states' / (revision + '.json'), state)
        return revision

    def publish_prepared(self, revision):
        atomic_json(self.root / 'CURRENT.json', {'format': 'qecgraph.registry.current.v1', 'revision': revision})
        return revision

    def _publish(self, state):
        return self.publish_prepared(self.prepare_publication(state))

    def register_source(self, work_id, source_version_id, store, *, title=None, upstream_version=None):
        with writer_lock(self.root):
            state = self._state_or_empty()
            version = self.stage_source(state, work_id, source_version_id, store,
                                        title=title, upstream_version=upstream_version)
            revision = self._publish(state)
        return {'registry_revision': revision, 'source_version': version}

    def stage_source(self, state, work_id, source_version_id, store, *, title=None, upstream_version=None,
                     replace_projection=False):
        """Prepare a verified source projection under the caller's registry writer lock."""
        if not all(isinstance(x, str) and x.strip() for x in (work_id, source_version_id)):
            raise ValueError('work_id and source_version_id must be explicit nonempty IDs')
        source = current_snapshot(store)
        validation = validate_snapshot(source)
        graph = read_json(source / 'graph.json')
        snapshot_id = validation['snapshot_id']
        version = {'id': source_version_id, 'work_id': work_id, 'project_id': graph['project_id'],
                   'snapshot_id': snapshot_id, 'project_source_hash': graph['project_source_hash'],
                   'snapshot_path': 'source_snapshots/' + snapshot_id, 'upstream_version': upstream_version}
        existing = state['versions'].get(source_version_id)
        if existing and existing != version:
            if not replace_projection or any(existing[field] != version[field]
                                             for field in ('work_id', 'project_id', 'upstream_version')):
                raise ValueError('Source version ID already binds different inputs; create a new version ID')
        target = safe_relative(self.root, version['snapshot_path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = Path(tempfile.mkdtemp(prefix='.register-', dir=target.parent))
            try:
                shutil.copytree(source, temporary, dirs_exist_ok=True)
                validate_snapshot(temporary, expected_snapshot_id=snapshot_id)
                temporary.rename(target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        else:
            validate_snapshot(target, expected_snapshot_id=snapshot_id)
        state['works'].setdefault(work_id, {'id': work_id, 'title': title or work_id})
        state['versions'][source_version_id] = version
        return version

    def source_graph(self, source_version_id, revision=None):
        state, fixed = self.read(revision)
        return self.source_graph_from_state(state, source_version_id, fixed)

    def source_graph_from_state(self, state, source_version_id, registry_revision):
        if source_version_id not in state['versions']:
            raise ValueError(f'Unknown source version in registry {registry_revision}: {source_version_id}')
        version = state['versions'][source_version_id]
        snapshot = safe_relative(self.root, version['snapshot_path'])
        graph = read_json(snapshot / 'graph.json')
        if graph['snapshot_id'] != version['snapshot_id']:
            raise ValueError('Registered snapshot identity mismatch')
        return graph, snapshot, version

    def validate_source_snapshot(self, version):
        """Validate the source snapshot bound by a verified registry state."""
        snapshot = safe_relative(self.root, version['snapshot_path'])
        if snapshot.name != version['snapshot_id']:
            raise ValueError('Registered snapshot identity mismatch')
        return validate_snapshot(snapshot)

    def _put_record(self, state, record):
        record = prepare_record(record)
        from .review import verify_record_review
        verify_record_review(self, record)
        from .validators import validate_endpoint
        for ref in record['refs']:
            if ref['target'] in state['records']:
                validate_endpoint(record['kind'], state['records'][ref['target']]['kind'], ref['relation'])
        identifier, revision = record['id'], record['revision']
        identity = state['records'].setdefault(identifier, {'kind': record['kind'], 'revisions': {}})
        if identity['kind'] != record['kind']:
            raise ValueError('An entity cannot change kind without explicit migration')
        path = 'records/' + hash_text(identifier) + '/' + hash_text(revision) + '.json'
        binding = {'path': path, 'content_sha256': record['content_sha256']}
        if revision in identity['revisions'] and identity['revisions'][revision] != binding:
            raise ValueError('Entity revision already binds different content')
        immutable_json(self.root / path, record)
        identity['revisions'][revision] = binding
        identity['current_revision'] = revision
        return record

    def add_record(self, record):
        with writer_lock(self.root):
            state = self._state_or_empty()
            record = self._put_record(state, record)
            revision = self._publish(state)
        return {'registry_revision': revision, 'record': record}

    def record(self, identifier, record_revision=None, registry_revision=None):
        state, _ = self.read(registry_revision)
        return self.record_from_state(state, identifier, record_revision)

    def record_from_state(self, state, identifier, record_revision=None):
        if identifier not in state['records']:
            raise ValueError(f'Unknown entity: {identifier}')
        identity = state['records'][identifier]
        revision = record_revision or identity['current_revision']
        if revision not in identity['revisions']:
            raise ValueError(f'Unknown revision for {identifier}: {revision}')
        binding = identity['revisions'][revision]
        record = prepare_record(read_json(safe_relative(self.root, binding['path'])), allow_legacy=True)
        if record['schema_version'] == 'qecgraph.record.v3':
            from .review import verify_record_review
            verify_record_review(self, record)
        if record['id'] != identifier or record['revision'] != revision or record['content_sha256'] != binding['content_sha256']:
            raise ValueError('Registered record identity/hash mismatch')
        return record

    def link_claim(self, link_id, source_version_id, source_selector, claim_id, *, claim_revision=None,
                   assumptions=None, notation_scope=None):
        if not isinstance(link_id, str) or not link_id.strip():
            raise ValueError('Link requires explicit identity')
        with writer_lock(self.root):
            state, fixed = self.read()
            graph, _, version = self.source_graph(source_version_id, fixed)
            node_id = resolve(graph, source_selector)
            node = next(n for n in graph['nodes'] if n['id'] == node_id)
            if node['origin'] != 'parser' or not node.get('source'):
                raise ValueError('Claim provenance requires an actual source block')
            claim = self.record(claim_id, claim_revision, fixed)
            if claim['kind'] != 'claim':
                raise ValueError('Source normalization target must be a claim')
            from .validators import validate_endpoint
            validate_endpoint(node['kind'], claim['kind'], 'normalizes_to')
            link = {'id': link_id, 'relation': 'normalizes_to', 'status': 'proposed',
                    'source_version_id': source_version_id, 'source_snapshot_id': version['snapshot_id'],
                    'source_node_id': node_id, 'source_content_sha256': node['content_sha256'],
                    'claim_id': claim_id, 'claim_revision': claim['revision'],
                    'claim_content_sha256': claim['content_sha256'],
                    'assumptions': assumptions or [], 'notation_scope': notation_scope or {}}
            prior = next((x for x in state['links'] if x['id'] == link_id), None)
            if prior and prior != link:
                raise ValueError('Provenance link identity already binds different content')
            if not prior:
                state['links'].append(link)
                state['links'].sort(key=lambda x: x['id'])
            revision = self._publish(state)
        return {'registry_revision': revision, 'link': link}

    def import_migration(self, migration_root):
        migration_root = Path(migration_root).resolve()
        report = read_json(migration_root / 'migration-report.json')
        if report.get('schema_version') != 'qecgraph.migration.v1' or report.get('rejected'):
            raise ValueError('Import requires a migration report with no rejected inputs')
        records = [read_json(safe_relative(migration_root, item['output_path'])) for item in report['accepted']
                   if item['output_schema'] == 'qecgraph.record.v3']
        with writer_lock(self.root):
            state = self._state_or_empty()
            for record in records:
                for asset in record['assets']:
                    source = safe_relative(migration_root, asset['path'])
                    raw = source.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != asset['sha256']:
                        raise ValueError('Migrated asset hash mismatch')
                    target = safe_relative(self.root, asset['path'])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and target.read_bytes() != raw:
                        raise ValueError('Managed asset is corrupted')
                    target.write_bytes(raw)
                self._put_record(state, record)
            revision = self._publish(state)
        return {'registry_revision': revision, 'imported_records': len(records), 'mathematical_recheck': 'not_performed'}

    def asset_bytes(self, uri):
        prefix = 'qecasset:sha256:'
        digest = uri.removeprefix(prefix)
        if not uri.startswith(prefix) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Unknown managed asset URI')
        raw = safe_relative(self.root, 'assets/' + digest).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Managed asset content changed')
        return raw

    def _put_asset(self, raw, media_type, original_path=None):
        digest = hashlib.sha256(raw).hexdigest()
        target = safe_relative(self.root, 'assets/' + digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError('Managed asset content changed')
        else:
            atomic_bytes(target, raw)
        asset = {'asset_id': 'asset:sha256:' + digest, 'uri': 'qecasset:sha256:' + digest,
                 'path': 'assets/' + digest, 'sha256': digest, 'size_bytes': len(raw), 'media_type': media_type}
        if original_path is not None:
            asset['original_path'] = original_path
        return asset

    def validate(self, registry_revision=None, *, check_live_lean=True):
        from .validators import registry_issues
        from .corpus import project
        state, fixed = self.read(registry_revision)
        issues = registry_issues(self, state, fixed)
        for version in state['versions'].values():
            self.validate_source_snapshot(version)
        graph, _ = project(self.root, fixed, check_live_lean=check_live_lean)
        from .validators import validate_graph_types
        validate_graph_types(graph.graph)
        from .status import reviewed_cycles
        issues.extend(reviewed_cycles(graph.graph))
        issues.extend({'code': 'review_stale', 'severity': 'warning', 'record_id': node['id'],
                       'reasons': node['review_binding']['reasons']}
                      for node in graph.graph['nodes'] if node.get('review_binding', {}).get('effective_status') == 'stale')
        issues.extend({'code': 'lean_build_stale', 'severity': 'warning', 'record_id': node['id'],
                       'reasons': node['build_binding']['reasons']}
                      for node in graph.graph['nodes'] if node.get('build_binding', {}).get('effective_status') == 'stale')
        passed = not any(issue.get('severity', 'error') == 'error' for issue in issues)
        return {'registry_revision': fixed, 'passed': passed, 'issues': issues,
                'scope': 'structure, types, references, assets and source integrity; not mathematical verification',
                'suggested_exit_code': 0 if passed else 2}
