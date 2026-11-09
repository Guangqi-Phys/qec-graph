"""Reviewable proposals and independently bound decisions.

Actor identity is an explicit local assertion, not authentication. AI/program
acceptance never becomes a human review or a mathematical verification.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from .graph import canonical, hash_text, read_json
from .records import prepare_record
from .registry import Registry
from .transactions import immutable_json, writer_lock
from .validators import packaged_validator

SCOPES = {'statement', 'hypotheses', 'dependencies'}


def _actor(actor):
    if not isinstance(actor, dict) or set(actor) != {'id', 'kind'} or not isinstance(actor['id'], str) or not actor['id'].strip():
        raise ValueError('Actor needs an explicit ID and kind')
    if actor['kind'] not in {'human', 'ai', 'program'}:
        raise ValueError('Actor kind must be human, ai or program')
    return dict(actor)


def _diff(before, after, path=''):
    if isinstance(before, dict) and isinstance(after, dict):
        items = []
        for key in sorted(before.keys() | after.keys()):
            escaped = key.replace('~', '~0').replace('/', '~1')
            if key not in before:
                items.append({'path': path + '/' + escaped, 'operation': 'add', 'after': after[key]})
            elif key not in after:
                items.append({'path': path + '/' + escaped, 'operation': 'remove', 'before': before[key]})
            else:
                items.extend(_diff(before[key], after[key], path + '/' + escaped))
        return items
    return [] if before == after else [{'path': path, 'operation': 'replace', 'before': before, 'after': after}]


def _path(registry, category, identifier):
    if not isinstance(identifier, str) or not identifier:
        raise ValueError('Proposal/review ID must be a nonempty string')
    return registry.root / category / (hash_text(identifier) + '.json')


def _validate(value, schema_name):
    error = next(packaged_validator(schema_name, check_formats=False).iter_errors(value), None)
    if error is not None:
        raise ValueError('Review/proposal schema: ' + error.message)


def input_bindings(registry, state, after_records=()):
    records = list(registry.records_from_state(state, sorted(state['records'])).values())
    assets = {}
    for record in records + list(after_records):
        for asset in record['assets']:
            raw = registry.asset_bytes(asset['uri'])
            if len(raw) != asset['size_bytes']:
                raise ValueError('Review asset size mismatch')
            assets[asset['uri']] = {'uri': asset['uri'], 'sha256': asset['sha256'], 'size_bytes': len(raw)}
    for version in state['versions'].values():
        registry.validate_source_snapshot(version)
    return {'records': [{key: record[key] for key in ('id', 'revision', 'content_sha256')} for record in records],
            'source_versions': copy.deepcopy(state['versions']), 'assets': [assets[key] for key in sorted(assets)]}


def create_proposal(corpus, changes, *, actor, rationale, expected_registry_revision=None):
    actor = _actor(actor)
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError('Proposal requires rationale')
    if not isinstance(changes, list) or not changes:
        raise ValueError('Proposal requires a nonempty change list')
    for change in changes:
        if (not isinstance(change, dict)
                or set(change) != {'record', 'expected_revision', 'expected_content_sha256'}
                or not isinstance(change['record'], dict)):
            raise ValueError('Each change needs a record object, expected_revision and expected_content_sha256 (null for a new ID)')
    registry = Registry(corpus)
    with writer_lock(registry.root):
        state = registry._state_or_empty()
        fixed = registry._publish(state)
        if expected_registry_revision and expected_registry_revision != fixed:
            raise ValueError('Proposal base registry revision is stale')
        prepared, seen = [], set()
        for change in changes:
            after = prepare_record(change['record'])
            identifier = after['id']
            if identifier in seen:
                raise ValueError('Duplicate record ID in proposal')
            seen.add(identifier)
            if after['review']['status'] not in {'proposed', 'draft'}:
                raise ValueError('Proposed revisions must start draft/proposed; old review cannot be copied')
            before = registry.record_from_state(state, identifier) if identifier in state['records'] else None
            expected = (change['expected_revision'], change['expected_content_sha256'])
            actual = (before['revision'], before['content_sha256']) if before else (None, None)
            if expected != actual:
                raise ValueError(f'Proposal input revision/hash conflict for {identifier}')
            if before and after['revision'] == before['revision']:
                raise ValueError('A changed record requires a new explicit revision')
            prepared.append({'before': before, 'after': after, 'diff': _diff(before, after)})
        payload = {'schema_version': 'qecgraph.proposal.v1', 'corpus_id': state['corpus_id'],
                   'base_registry_revision': fixed, 'actor': actor, 'rationale': rationale,
                   'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'proposed',
                   'changes': prepared, 'input_bindings': input_bindings(registry, state, [x['after'] for x in prepared])}
        proposal_id = 'proposal:' + hash_text(canonical(payload))
        proposal = {'id': proposal_id, **payload}
        _validate(proposal, 'proposal.v1')
        immutable_json(_path(registry, 'proposals', proposal_id), proposal)
    return proposal


def read_proposal(registry, proposal_id):
    proposal = read_json(_path(registry, 'proposals', proposal_id))
    _validate(proposal, 'proposal.v1')
    payload = {key: value for key, value in proposal.items() if key != 'id'}
    if proposal.get('schema_version') != 'qecgraph.proposal.v1' or proposal.get('id') != proposal_id or proposal_id != 'proposal:' + hash_text(canonical(payload)):
        raise ValueError('Proposal identity/hash mismatch')
    return proposal


def decide(corpus, proposal_id, *, actor, decision, rationale, checked_scopes=()):
    actor = _actor(actor)
    if decision not in {'approve', 'reject'} or not isinstance(rationale, str) or not rationale.strip():
        raise ValueError('Decision requires approve/reject and a rationale')
    scopes = set(checked_scopes)
    if not scopes <= SCOPES:
        raise ValueError('Unknown review scope')
    if actor['kind'] == 'human' and decision == 'approve' and scopes != SCOPES:
        raise ValueError('Human approval must explicitly check statement, hypotheses and dependencies')
    registry = Registry(corpus)
    with writer_lock(registry.root):
        state, fixed = registry.read()
        proposal = read_proposal(registry, proposal_id)
        if state.get('corpus_id') != proposal['corpus_id'] or fixed != proposal['base_registry_revision']:
            raise ValueError('Proposal belongs to another corpus or stale registry revision')
        if input_bindings(registry, state, [x['after'] for x in proposal['changes']]) != proposal['input_bindings']:
            raise ValueError('Proposal input/asset bindings changed; create and inspect a new proposal')
        review_id = 'review:' + str(uuid.uuid4())
        status = 'rejected' if decision == 'reject' else 'human_approved' if actor['kind'] == 'human' else 'machine_accepted'
        review = {'schema_version': 'qecgraph.review.v1', 'id': review_id, 'proposal_id': proposal_id,
                  'proposal_sha256': hash_text(canonical(proposal)), 'corpus_id': proposal['corpus_id'],
                  'actor': actor, 'decision': decision, 'status': status, 'checked_scopes': sorted(scopes),
                  'rationale': rationale, 'created_at': datetime.now(timezone.utc).isoformat(),
                  'input_bindings': proposal['input_bindings'], 'scope': 'record contents; no automatic mathematical or Lean verification'}
        _validate(review, 'review.v1')
        immutable_json(_path(registry, 'reviews', review_id), review)
    return review


def final_records(proposal, review):
    if review['proposal_id'] != proposal['id'] or review['proposal_sha256'] != hash_text(canonical(proposal)):
        raise ValueError('Review is not bound to this exact proposal')
    if review['decision'] != 'approve':
        raise ValueError('A rejected proposal cannot be applied')
    records = []
    for change in proposal['changes']:
        record = copy.deepcopy(change['after'])
        if review['status'] == 'human_approved':
            if review['actor']['kind'] != 'human' or set(review['checked_scopes']) != SCOPES:
                raise ValueError('Incomplete human review binding')
            record.pop('content_sha256')
            record['review'] = {'status': 'reviewed', 'review_id': review['id'],
                                'review_sha256': hash_text(canonical(review))}
        elif review['status'] != 'machine_accepted' or review['actor']['kind'] not in {'ai', 'program'}:
            raise ValueError('Invalid review actor/status combination')
        records.append(prepare_record(record))
    return records


def verify_record_review(registry, record, *, checked_reviews=None):
    if record['review']['status'] != 'reviewed':
        return
    review_id = record['review'].get('review_id')
    review_hash = record['review'].get('review_sha256')
    checked = checked_reviews.get(review_id) if checked_reviews is not None else None
    if checked is None:
        review = read_json(_path(registry, 'reviews', review_id))
        _validate(review, 'review.v1')
        digest = hash_text(canonical(review))
        if review['id'] != review_id or review_hash != digest:
            raise ValueError('Record human review hash/identity mismatch')
        proposal = read_proposal(registry, review['proposal_id'])
        expected = {}
        for item in final_records(proposal, review):
            expected.setdefault(item['id'], item)
        if checked_reviews is not None:
            checked_reviews[review_id] = (digest, expected)
    else:
        digest, expected = checked
        if review_hash != digest:
            raise ValueError('Record human review hash/identity mismatch')
    if expected.get(record['id']) != record:
        raise ValueError('Review does not bind this statement, hypotheses, dependencies and exact revision')


def read_review(registry, review_id):
    review = read_json(_path(registry, 'reviews', review_id))
    _validate(review, 'review.v1')
    if review['id'] != review_id:
        raise ValueError('Review identity mismatch')
    return review


def apply(corpus, proposal_id, review_id):
    """CAS publish an entire validated batch; unreferenced objects are harmless.

    The immutable receipt is written before CURRENT, and the published state
    records the application. A receipt alone never counts as a completed apply.
    """
    from .validators import registry_issues
    registry = Registry(corpus)
    with writer_lock(registry.root):
        state, fixed = registry.read()
        proposal = read_proposal(registry, proposal_id)
        review = read_review(registry, review_id)
        if state.get('corpus_id') != proposal['corpus_id'] or review['corpus_id'] != proposal['corpus_id']:
            raise ValueError('Proposal/review belongs to another corpus')
        applications = state.get('applications', {})
        if proposal_id in applications:
            if applications[proposal_id]['review_id'] != review_id:
                raise ValueError('Proposal already applied with a different review')
            receipt = read_json(_path(registry, 'applications', proposal_id))
            if receipt['review_sha256'] != hash_text(canonical(review)):
                raise ValueError('Applied review content changed')
            return {'status': 'applied', 'receipt': receipt}
        if fixed != proposal['base_registry_revision']:
            raise ValueError('Stale proposal: registry changed; inspect and propose a new revision')
        records = final_records(proposal, review)
        review_sha256 = hash_text(canonical(review))
        checked_reviews = {}
        if review['status'] == 'human_approved':
            checked_reviews[review_id] = (review_sha256, {record['id']: record for record in records})
        if input_bindings(registry, state, records) != proposal['input_bindings']:
            raise ValueError('Proposal input/asset bindings changed')
        for change in proposal['changes']:
            identifier = change['after']['id']
            before = registry.record_from_state(state, identifier) if identifier in state['records'] else None
            if before != change['before']:
                raise ValueError('Apply input revision/hash no longer matches the reviewed diff')
        for record in records:
            registry._put_record(state, record, checked_reviews=checked_reviews)
        after_records = registry.records_from_state(state, _checked_reviews=checked_reviews)
        errors = [issue for issue in registry_issues(registry, after_records)
                  if issue.get('severity', 'error') == 'error']
        if errors:
            raise ValueError('Apply cross-record validation failed: ' + canonical(errors))
        binding = {'review_id': review_id, 'review_sha256': review_sha256,
                   'records': [{key: record[key] for key in ('id', 'revision', 'content_sha256')} for record in records]}
        state.setdefault('applications', {})[proposal_id] = binding
        target_revision = hash_text(canonical(state))
        receipt = {'schema_version': 'qecgraph.application.v1', 'proposal_id': proposal_id,
                   'base_registry_revision': fixed, 'registry_revision': target_revision, **binding}
        immutable_json(_path(registry, 'applications', proposal_id), receipt)
        published = registry._publish(state)
        if published != target_revision:
            raise ValueError('Application state identity mismatch')
    return {'status': 'applied', 'receipt': receipt}
