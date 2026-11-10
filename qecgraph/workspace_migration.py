"""Copy a pinned legacy corpus into a new workspace without rewriting its evidence."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

from .registry import Registry
from .core.transactions import atomic_json, writer_lock
from .workspace import Workspace
from .workspace_query import check_machine_tree

# All of these are part of the legacy Registry's managed authority.
DIRECTORIES = {'states', 'source_snapshots', 'assets', 'records', 'reviews', 'proposals', 'applications'}
FILES = {'.qecgraph-registry.json'}


def _unresolved(registry, state):
    rows = []
    for identifier, record in registry.records_from_state(state, sorted(state['records'])).items():
        data = record['data']
        candidates = {
            'untyped_distance': ('d' in data and not data.get('relation')) or (
                'd' in (data.get('parameters') or {}) and not data.get('distance_claim_ids')),
            'unbound_negative_idle': data.get('idle') is False,
            'unresolved_software_name': isinstance(data.get('software'), str),
            'unspecified_depth_definition': 'depth' in data and not data.get('depth_definition'),
            'legacy_experiment_requires_exact_rfc_bindings': record['kind'] == 'experiment',
        }
        for reason, applies in candidates.items():
            if applies:
                rows.append({'id': identifier, 'revision': record['revision'], 'reason': reason})
    return rows


def migrate_corpus(corpus, destination, revision=None):
    source = Registry(corpus)
    raw_target = Path(destination).expanduser()
    if raw_target.is_symlink():
        raise ValueError('Migration destination must not be a symlink')
    target = raw_target.resolve()
    if target.exists() or target.is_relative_to(source.root) or source.root.is_relative_to(target):
        raise ValueError('Migration destination must be a new, independent directory')
    if not source.root.is_dir():
        raise ValueError('A legacy corpus directory is required')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + target.name + '-migration-', dir=target.parent))
    try:
        ws = Workspace(staging)
        ws.init(no_ingest=True)
        workspace_id = ws.config()['workspace_id']
        # Copy immutable inputs from a single fixed state. The source lock also blocks
        # changes to non-published proposal/review files during the copy.
        with writer_lock(source.root):
            check_machine_tree(source.root)
            state, fixed = source.read(revision)
            if state.get('workspace_id'):
                raise ValueError('Use backup/restore for a workspace; migration expects a legacy corpus')
            validation = source._validate_state(state, fixed)
            if not validation['passed']:
                raise ValueError('Legacy corpus has validation errors; inspect validate-corpus before migrating')
            unknown = _unresolved(source, state)
            new_machine = staging / 'copied-machine'
            new_machine.mkdir()
            for name in sorted(DIRECTORIES | FILES):
                path = source.root / name
                if path.is_dir() and name in DIRECTORIES:
                    shutil.copytree(path, new_machine / name)
                elif path.is_file() and name in FILES:
                    shutil.copyfile(path, new_machine / name)
            # Preserve all copied registry revisions; only add workspace metadata to a new state.
            registry = Registry(new_machine)
            copied, _ = registry.read(fixed)
            if copied != state:
                raise ValueError('Legacy state changed during copy')
            state.update(workspace_id=workspace_id, materials={}, generated_research={}, legacy_import={
                'registry_revision': fixed, 'source_versions': sorted(state['versions']),
                'archive_status': 'original_download_blobs_not_available_in_legacy_corpus'})
            release = registry._publish(state)
            checked = registry.validate(release)
            if not checked['passed']:
                raise ValueError('Copied legacy corpus did not validate')
        shutil.rmtree(ws.registry.root)  # private staging; contains only the just-created empty corpus
        os.rename(new_machine, ws.registry.root)
        report = {'status': 'migrated', 'legacy_registry_revision': fixed, 'release_id': release,
                  'source_versions': sorted(state['versions']), 'record_ids': sorted(state['records']),
                  'identity_mapping': 'unchanged', 'uncertain_fields': unknown, 'validation_issues': checked['issues'],
                  'rejected_records': [], 'review_policy': 'Preserve existing bindings; never infer new reviewed facts',
                  'source_policy': 'Legacy source snapshots preserved; original download bytes are not fabricated'}
        atomic_json(ws.path('.qecgraph/migration.json'), report)
        if target.exists():
            raise ValueError('Migration destination appeared during copy')
        os.rename(staging, target)
        return report
    finally:
        if staging.exists():
            shutil.rmtree(staging)
