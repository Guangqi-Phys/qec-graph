"""Explicit decisions bound to published AI proposals and source projections."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import stat
import uuid

from ..core.graph import canonical, hash_text, read_json
from ..core.transactions import immutable_json, writer_lock
from ..registry import Registry


SCOPES = frozenset({'statement', 'hypotheses', 'dependencies'})
_PROPOSALS = Path('ai/proposals')


class AIReviewError(ValueError):
    """An AI proposal review request is invalid."""


def _actor(actor):
    if (not isinstance(actor, dict) or set(actor) != {'id', 'kind'}
            or not isinstance(actor['id'], str) or not actor['id'].strip()
            or actor['kind'] not in {'human', 'ai', 'program'}):
        raise AIReviewError('actor needs an explicit ID and kind')
    return dict(actor)


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


def decide(workspace, proposal_path, *, actor, decision, rationale, checked_scopes=()):
    actor = _actor(actor)
    if decision not in {'approve', 'reject'}:
        raise AIReviewError('decision must be approve or reject')
    if not isinstance(rationale, str) or not rationale.strip():
        raise AIReviewError('review requires a rationale')
    scopes = set(checked_scopes)
    if not scopes <= SCOPES:
        raise AIReviewError('unknown review scope')
    if actor['kind'] == 'human' and decision == 'approve' and scopes != SCOPES:
        raise AIReviewError('human approval must check statement, hypotheses and dependencies')

    registry = _registry(workspace)
    proposal_path = Path(proposal_path).absolute()
    try:
        relative = proposal_path.relative_to(registry.root).as_posix()
    except ValueError as exc:
        raise AIReviewError('Proposal must be registered in the workspace machine release') from exc
    if not (registry.root / 'CURRENT.json').is_file():
        raise AIReviewError('No machine release has published this proposal')
    with writer_lock(registry.root):
        state, release = registry.read()
        entry = proposal_bindings(state).get(relative)
        if entry is None:
            raise AIReviewError('Proposal is not registered in the current source projection')
        binding, material = entry
        proposal = read_bound_proposal(registry, binding, material)
        version = state['versions'][proposal['source_version_id']]
        registry.validate_source_snapshot(version)
        if material.get('normalization_manifest_sha256'):
            from .artifacts import load_normalization
            load_normalization(registry.root, material)
        review = {
            'schema': 'qecgraph.ai.review',
            'id': 'ai-review:' + uuid.uuid4().hex,
            'proposal_path': 'machine/' + relative,
            'proposal_sha256': binding['proposal_sha256'],
            'release_id': release,
            'source_version_id': proposal['source_version_id'],
            'snapshot_id': proposal['snapshot_id'],
            'source_tree_hash': proposal['source_tree_hash'],
            'skill': proposal['skill'],
            'actor': actor,
            'actor_authentication': 'self_asserted_local_identity',
            'decision': decision,
            'status': ('rejected' if decision == 'reject'
                       else 'human_approved' if actor['kind'] == 'human' else 'machine_accepted'),
            'checked_scopes': sorted(scopes),
            'rationale': rationale,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'scope': 'AI proposal review only; no automatic research-record application',
        }
        directory = registry.root / 'ai' / 'reviews'
        if directory.resolve() != directory:
            raise AIReviewError('AI review directory must be an unlinked managed path')
        digest = hash_text(canonical(review))
        immutable_json(directory / (digest + '.json'), review)
        state.setdefault('ai_reviews', {})[review['id']] = digest
        registry._publish(state)
    return review


def read_decisions(registry, state):
    """Read only release-registered decisions, verifying their exact content."""
    directory = registry.root / 'ai' / 'reviews'
    current = proposal_bindings(state)
    values = []
    for identifier, digest in sorted(state.get('ai_reviews', {}).items()):
        path = directory / (digest + '.json')
        try:
            metadata = path.lstat()
            if path.resolve() != path or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise AIReviewError('Registered AI review is not a regular managed file')
            value = read_json(path)
        except (OSError, ValueError) as exc:
            raise AIReviewError('Registered AI review is unavailable') from exc
        if not (isinstance(value, dict) and value.get('id') == identifier and value.get('schema') == 'qecgraph.ai.review'
                and isinstance(value.get('proposal_path'), str) and path.stem == hash_text(canonical(value))):
            raise AIReviewError('Registered AI review content binding is invalid')
        entry = current.get(value['proposal_path'].removeprefix('machine/'))
        effective_status = 'stale'
        if entry and entry[0]['proposal_sha256'] == value.get('proposal_sha256'):
            try:
                read_bound_proposal(registry, *entry)
            except (OSError, ValueError, KeyError, TypeError):
                pass
            else:
                material = entry[1]
                if (value.get('source_version_id') == material['source_version_id']
                        and value.get('snapshot_id') == material['source_snapshot_id']):
                    effective_status = value['status']
        values.append({**value, 'effective_status': effective_status})
    return values


def decisions(workspace, release_id=None):
    registry = _registry(workspace)
    if not (registry.root / 'CURRENT.json').exists():
        return []
    return read_decisions(registry, registry.read(release_id)[0])
