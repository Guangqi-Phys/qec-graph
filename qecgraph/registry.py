"""Workspace release registry: explicit identities, immutable source snapshots."""
from __future__ import annotations

from .core.progress import phase, task

import hashlib
import shutil
import stat
import tempfile
from pathlib import Path

from .core.graph import canonical, hash_text, read_json
from .store import current_snapshot, load_validated_snapshot, safe_relative
from .core.transactions import ManagedDataError, atomic_bytes, immutable_json, publish_pointer, read_pointer

FORMAT = 'qecgraph.registry'
CURRENT_FORMAT = 'qecgraph.registry.current'


def empty_state(workspace_id):
    return {'schema': FORMAT, 'format_version': 2, 'workspace_id': workspace_id, 'works': {}, 'versions': {}}


def validate_state_format(state, path):
    from .validators import packaged_validator
    error = next(packaged_validator('registry', check_formats=False).iter_errors(state), None)
    if error is not None:
        location = '/'.join(str(part) for part in error.absolute_path) or '<root>'
        raise ManagedDataError(path, 'Registry state schema violation at ' + location)


def _check_source_binding(graph, version):
    if graph['snapshot_id'] != version['snapshot_id']:
        raise ValueError('Registered snapshot identity mismatch')
    if any(graph[field] != version[field] for field in ('project_id', 'project_source_hash')):
        raise ValueError('Registered snapshot project fingerprint mismatch')
    recovery = graph.get('structure_recovery')
    binding = {'status': 'proposed', 'plan_sha256': hash_text(canonical(recovery))} if recovery else None
    if binding != version.get('structure_recovery'):
        raise ValueError('Registered source structure binding mismatch')


def _verify_state_binding(state, revision, path):
    if hash_text(canonical(state)) != revision:
        raise ManagedDataError(path, 'Registry state hash mismatch')
    validate_state_format(state, path)


def _is_workspace_state(state):
    return (isinstance(state, dict) and state.get('schema') == FORMAT and state.get('format_version') == 2
            and isinstance(state.get('workspace_id'), str)
            and not {'corpus_id', 'records', 'links', 'ai_reviews', 'semantic_decisions'} & state.keys())


class Registry:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def read(self, revision=None, *, verify=True):
        pointer_path = self.root / 'CURRENT.json' if revision is None else None
        if pointer_path is not None:
            pointer = read_pointer(pointer_path, CURRENT_FORMAT)
            revision = pointer.get('revision')
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
            if pointer_path is not None:
                raise ManagedDataError(pointer_path, 'CURRENT does not identify a valid registry revision')
            raise ValueError('Invalid registry revision')
        state_path = self.root / 'states' / (revision + '.json')
        try:
            metadata = state_path.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ManagedDataError(state_path, 'Registry state must be a regular unlinked local file')
        try:
            state = read_json(state_path)
        except ValueError as exc:
            raise ManagedDataError(state_path, 'Registry state contains invalid JSON') from exc
        if not _is_workspace_state(state):
            raise ManagedDataError(state_path, 'Registry state schema mismatch')
        if verify:
            _verify_state_binding(state, revision, state_path)
        return state, revision

    def _state_and_revision(self, workspace_id):
        pointer = self.root / 'CURRENT.json'
        if pointer.is_symlink():
            raise ValueError('The registry pointer cannot be a symlink')
        if not pointer.exists():
            if any(p.name != '.writer.lock' for p in self.root.iterdir()):
                raise ValueError('Initialize the workspace with an empty machine directory')
            return empty_state(workspace_id), None
        state, fixed = self.read()
        if state['workspace_id'] != workspace_id:
            raise ValueError('Machine release belongs to another workspace')
        return state, fixed

    def prepare_publication(self, state):
        validate_state_format(state, 'registry')
        revision = hash_text(canonical(state))
        immutable_json(self.root / 'states' / (revision + '.json'), state, compact=True)
        return revision

    def publish_prepared(self, revision):
        publish_pointer(self.root / 'CURRENT.json', CURRENT_FORMAT, revision=revision)
        return revision

    def _publish(self, state):
        return self.publish_prepared(self.prepare_publication(state))

    def stage_source(self, state, work_id, source_version_id, store, *, title=None, upstream_version=None,
                     replace_projection=False, captured=None, manifest_hashes=None, canonical_url=None):
        """Prepare a verified source projection under the caller's registry writer lock."""
        if not all(isinstance(x, str) and x.strip() for x in (work_id, source_version_id)):
            raise ValueError('work_id and source_version_id must be explicit nonempty IDs')
        source = current_snapshot(store)
        snapshot_id = source.name
        snapshot_path = 'source_snapshots/' + snapshot_id
        target = safe_relative(self.root, snapshot_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None if target.exists() else Path(tempfile.mkdtemp(prefix='.register-', dir=target.parent))
        try:
            graph, _ = load_validated_snapshot(source, copy_to=temporary,
                                               manifest_hashes=manifest_hashes if temporary is not None else None)
            version = {'id': source_version_id, 'work_id': work_id, 'project_id': graph['project_id'],
                       'snapshot_id': snapshot_id, 'project_source_hash': graph['project_source_hash'],
                       'snapshot_path': snapshot_path, 'upstream_version': upstream_version}
            if canonical_url is not None:
                from urllib.parse import urlsplit
                url = urlsplit(canonical_url)
                if url.scheme not in {'http', 'https'} or not url.hostname or url.username or any(c.isspace() for c in canonical_url):
                    raise ValueError('canonical_url must be a public HTTP(S) citation URL')
                version['canonical_url'] = canonical_url
            if 'structure_recovery' in graph:
                version['structure_recovery'] = {'status': 'proposed',
                                                 'plan_sha256': hash_text(canonical(graph['structure_recovery']))}
            existing = state['versions'].get(source_version_id)
            if existing and existing != version:
                if not replace_projection or any(existing[field] != version[field]
                                                 for field in ('work_id', 'project_id', 'upstream_version')):
                    raise ValueError('Source version ID already binds different inputs; create a new version ID')
            if temporary is None:
                graph, _ = load_validated_snapshot(target, snapshot_id, manifest_hashes=manifest_hashes)
                _check_source_binding(graph, version)
            else:
                temporary.rename(target)
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)
        state['works'].setdefault(work_id, {'id': work_id, 'title': title or work_id})
        state['versions'][source_version_id] = version
        if captured is not None:
            captured.append((graph, target, version))
        return version

    def source_graph(self, source_version_id, revision=None):
        state, fixed = self.read(revision)
        return self.source_graph_from_state(state, source_version_id, fixed)

    def source_graph_from_state(self, state, source_version_id, registry_revision, *, verify=False, manifest_hashes=None):
        if source_version_id not in state['versions']:
            raise ValueError(f'Unknown source version in registry {registry_revision}: {source_version_id}')
        version = state['versions'][source_version_id]
        if verify:
            graph, snapshot, _ = self._load_verified_source(version, manifest_hashes=manifest_hashes)
            return graph, snapshot, version
        snapshot = safe_relative(self.root, version['snapshot_path'])
        graph = read_json(snapshot / 'graph.json')
        _check_source_binding(graph, version)
        return graph, snapshot, version

    def validate_source_snapshot(self, version):
        """Validate the source snapshot bound by a verified registry state."""
        _, _, report = self._load_verified_source(version)
        return report

    def _load_verified_source(self, version, *, manifest_hashes=None):
        snapshot = safe_relative(self.root, version['snapshot_path'])
        if snapshot.name != version['snapshot_id']:
            raise ValueError('Registered snapshot identity mismatch')
        graph, report = load_validated_snapshot(snapshot, manifest_hashes=manifest_hashes)
        _check_source_binding(graph, version)
        return graph, snapshot, report

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

    def validate(self, registry_revision=None, *, manifest_hashes=None):
        state, fixed = self.read(registry_revision)
        return self._validate_state(state, fixed, manifest_hashes=manifest_hashes)

    @task('Validating record references and evidence')
    def _validate_state(self, state, fixed, *, verified_spans=None, manifest_hashes=None):
        from .validators import validate_graph_types
        from .workspace_projection import project_sources

        verified_spans = {} if verified_spans is None else verified_spans
        issues = []
        graph = project_sources(self, state, fixed, verify_sources=True, verified_spans=verified_spans,
                                manifest_hashes=manifest_hashes)
        validate_graph_types(graph.graph)
        phase('Validating research records and source bindings')
        if state.get('research_records'):
            try:
                from .domain.research import validate_bundle
                from .domain.research_store import load_records, validate_sources
                research = load_records(self, state)
                validate_bundle(research)
                validate_sources(self, state, research, verified_spans=verified_spans)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                issues.append({'code': 'research_invalid', 'severity': 'error', 'message': str(exc)})
        phase('Verifying retrieval index integrity')
        if state.get('retrieval_index', {}).get('sha256'):
            try:
                from .retrieval import read_index
                read_index(self.root, state['retrieval_index'], verify_vectors=True)
            except (OSError, ValueError, KeyError, TypeError):
                issues.append({'code': 'retrieval_index_invalid', 'severity': 'error',
                               'message': 'Retrieval projection failed integrity validation; rebuild it'})
        passed = not any(issue.get('severity', 'error') == 'error' for issue in issues)
        return {'registry_revision': fixed, 'passed': passed, 'issues': issues,
                'scope': 'structure, types, references, assets and source integrity; not mathematical verification',
                'suggested_exit_code': 0 if passed else 2}
