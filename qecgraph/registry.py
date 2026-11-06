"""Versioned corpus registry: explicit identities, immutable source snapshots."""
from __future__ import annotations

import copy
import shutil
import tempfile
from pathlib import Path

from .graph import canonical, hash_text, read_json
from .store import current_snapshot, safe_relative, validate_snapshot
from .transactions import atomic_json, immutable_json, writer_lock

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
        return copy.deepcopy(state), revision

    def _state_or_empty(self):
        if (self.root / 'CURRENT.json').exists():
            return self.read()[0]
        if any(p.name not in {'.writer.lock', 'states', 'source_snapshots'} for p in self.root.iterdir()):
            raise ValueError('Registry must be initialized in an empty directory')
        return empty_state()

    def _publish(self, state):
        revision = hash_text(canonical(state))
        immutable_json(self.root / 'states' / (revision + '.json'), state)
        atomic_json(self.root / 'CURRENT.json', {'format': 'qecgraph.registry.current.v1', 'revision': revision})
        return revision

    def register_source(self, work_id, source_version_id, store, *, title=None, upstream_version=None):
        if not all(isinstance(x, str) and x.strip() for x in (work_id, source_version_id)):
            raise ValueError('work_id and source_version_id must be explicit nonempty IDs')
        source = current_snapshot(store)
        validation = validate_snapshot(source)
        graph = read_json(source / 'graph.json')
        snapshot_id = validation['snapshot_id']
        version = {'id': source_version_id, 'work_id': work_id, 'project_id': graph['project_id'],
                   'snapshot_id': snapshot_id, 'project_source_hash': graph['project_source_hash'],
                   'snapshot_path': 'source_snapshots/' + snapshot_id, 'upstream_version': upstream_version}
        with writer_lock(self.root):
            state = self._state_or_empty()
            existing = state['versions'].get(source_version_id)
            if existing and existing != version:
                raise ValueError('Source version ID already binds different inputs; create a new version ID')
            target = self.root / version['snapshot_path']
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
                validate_snapshot(target)
            state['works'].setdefault(work_id, {'id': work_id, 'title': title or work_id})
            state['versions'][source_version_id] = version
            revision = self._publish(state)
        return {'registry_revision': revision, 'source_version': version}

    def source_graph(self, source_version_id, revision=None):
        state, fixed = self.read(revision)
        if source_version_id not in state['versions']:
            raise ValueError(f'Unknown source version in registry {fixed}: {source_version_id}')
        version = state['versions'][source_version_id]
        snapshot = safe_relative(self.root, version['snapshot_path'])
        graph = read_json(snapshot / 'graph.json')
        if graph['snapshot_id'] != version['snapshot_id']:
            raise ValueError('Registered snapshot identity mismatch')
        return graph, snapshot, version
