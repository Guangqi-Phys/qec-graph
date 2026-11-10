"""Explicit review decisions for AI proposals.

These decisions bind a person/agent to the exact proposal bytes. They do not
turn the proposal into a research record; conversion/application to canonical
records is deliberately separate.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from ..core.graph import canonical, hash_text
from ..core.transactions import immutable_json
from .errors import LLMError

SCOPES = frozenset({'statement', 'hypotheses', 'dependencies'})


class AIReviewError(LLMError):
    """An AI proposal review request is invalid."""


def _actor(actor):
    if (not isinstance(actor, dict) or set(actor) != {'id', 'kind'}
            or not isinstance(actor['id'], str) or not actor['id'].strip()
            or actor['kind'] not in {'human', 'ai', 'program'}):
        raise AIReviewError('actor needs an explicit ID and kind')
    return dict(actor)


def read_proposal(path):
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AIReviewError(f'could not read AI proposal: {exc}') from exc
    if not isinstance(value, dict) or value.get('schema') != 'qecgraph.ai.proposal':
        raise AIReviewError('not a qecgraph.ai.proposal')
    if value.get('review_status') != 'proposed':
        raise AIReviewError('AI proposal is not in proposed state')
    return value


def decide(workspace, proposal_path, *, actor, decision, rationale, checked_scopes=()):
    workspace = Path(workspace)
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
    proposal_path = Path(proposal_path).resolve()
    try:
        relative = proposal_path.relative_to(workspace.resolve())
    except ValueError as exc:
        raise AIReviewError('proposal must be inside the workspace') from exc
    proposal = read_proposal(proposal_path)
    proposal_sha256 = hash_text(canonical(proposal))
    review_id = 'ai-review:' + uuid.uuid4().hex
    status = ('rejected' if decision == 'reject'
              else 'human_approved' if actor['kind'] == 'human' else 'machine_accepted')
    review = {
        'schema': 'qecgraph.ai.review',
        'id': review_id,
        'proposal_path': str(relative),
        'proposal_sha256': proposal_sha256,
        'source_tree_hash': proposal.get('source_tree_hash'),
        'skill': proposal.get('skill'),
        'actor': actor,
        'decision': decision,
        'status': status,
        'checked_scopes': sorted(scopes),
        'rationale': rationale,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'AI proposal review only; no automatic research-record application',
    }
    target = workspace / 'machine' / 'ai' / 'reviews' / (hash_text(canonical(review)) + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    immutable_json(target, review)
    return review


def decisions(workspace):
    root = Path(workspace) / 'machine' / 'ai' / 'reviews'
    values = []
    if not root.is_dir():
        return values
    for path in sorted(root.glob('*.json')):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get('schema') == 'qecgraph.ai.review':
            values.append(value)
    return values
