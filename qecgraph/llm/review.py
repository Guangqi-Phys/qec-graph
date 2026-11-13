"""Read registered AI extraction artifacts and their source bindings."""
from __future__ import annotations

from pathlib import Path
import stat

from ..core.graph import canonical, hash_text, read_json
from ..registry import Registry


_PROPOSALS = Path('ai/proposals')


class AIReviewError(ValueError):
    """An extraction artifact could not be read."""


def _registry(workspace):
    machine = Path(workspace).resolve() / 'machine'
    if machine.is_symlink():
        raise AIReviewError('A real machine directory is required')
    return Registry(machine)


def proposal_bindings(state):
    """Index hash-bound proposals belonging to current source projections."""
    bindings = {}
    for material in state.get('materials', {}).values():
        version = state['versions'].get(material.get('source_version_id'))
        if not version or version['snapshot_id'] != material.get('source_snapshot_id'):
            continue
        for binding in material.get('ai_extraction', {}).get('written', []):
            if binding.get('proposal_sha256'):
                bindings[binding['path']] = (binding, material)
    return bindings


def read_bound_proposal(registry, binding, material):
    relative = Path(binding['path'])
    if not relative.is_relative_to(_PROPOSALS) or '..' in relative.parts:
        raise AIReviewError('Invalid registered AI proposal path')
    path = registry.root / relative
    try:
        metadata = path.lstat()
        if path.resolve() != path or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise AIReviewError('AI proposal must be an unlinked managed file')
        value = read_json(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise AIReviewError('Could not read the registered AI proposal') from exc
    if (not isinstance(value, dict) or value.get('schema') != 'qecgraph.ai.proposal'
            or value.get('review_status') != 'proposed'
            or hash_text(canonical(value)) != binding['proposal_sha256']
            or value.get('skill') != binding['skill']
            or value.get('source_version_id') != material['source_version_id']
            or value.get('snapshot_id') != material['source_snapshot_id']
            or value.get('source_tree_hash') != material['source_tree_hash']
            or value.get('projection_path') != material['entrypoint']
            or (material.get('normalization_sha256') is not None
                and value.get('normalization_id') != material['normalization_sha256'])):
        raise AIReviewError('AI proposal differs from its published content or source binding')
    return value


def proposal_issues(registry, state):
    for path, (binding, material) in proposal_bindings(state).items():
        try:
            read_bound_proposal(registry, binding, material)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            yield {'code': 'ai_proposal_invalid', 'severity': 'error', 'path': path, 'message': str(exc)}


def proposals(workspace):
    registry = _registry(workspace)
    if not (registry.root / 'CURRENT.json').exists():
        return []
    state, release = registry.read()
    items = []
    for path, (binding, material) in sorted(proposal_bindings(state).items()):
        item = {'path': str(registry.root / path), 'release_id': release, 'skill': binding['skill']}
        try:
            value = read_bound_proposal(registry, binding, material)
        except (OSError, ValueError, KeyError, TypeError):
            item['status'] = 'invalid'
        else:
            item.update(review_status=value['review_status'], items=len(value['items']))
        items.append(item)
    return items
