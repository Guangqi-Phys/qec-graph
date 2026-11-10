"""Exact QEC filtering with explicit bounds, metric and current evidence bindings."""
from __future__ import annotations

from ..registry import Registry
from ..validators.qec import distance_issues
from .status import review_states


def evidence_current(registry, evidence, records, required_ids, reviews=None, builds=None):
    data = evidence['data']
    if data.get('evidence_kind') == 'lean_build':
        binding = (builds or {}).get(evidence['id'], {})
        if binding.get('semantic_review') != 'matched' or data.get('axiom_policy_status') != 'allowed':
            return False
    if reviews and reviews[evidence['id']]['effective_status'] in {'stale', 'disputed'}:
        return False
    if evidence['review']['status'] in {'stale', 'disputed'} or not all(data.get(k) is not None for k in ('method', 'checker', 'outputs', 'scope', 'limitations')):
        return False
    if not data['outputs']:
        return False
    if data.get('evidence_kind') not in {'source_reported', 'computed_exact', 'certificate_checked', 'lean_build'}:
        return False
    if data.get('status') not in {'source_reported', 'passed', 'computed_exact', 'certificate_checked', 'build_passed'}:
        return False
    bindings = data.get('inputs')
    if not isinstance(bindings, list) or not bindings:
        return False
    bound = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            return False
        target = records.get(binding.get('id'))
        if target is None or target['revision'] != binding.get('revision') or target['content_sha256'] != binding.get('content_sha256'):
            return False
        bound.add(target['id'])
        try:
            for asset in target['assets']:
                registry.asset_bytes(asset['uri'])
        except (OSError, ValueError):
            return False
    try:
        for asset in evidence['assets']:
            registry.asset_bytes(asset['uri'])
    except (OSError, ValueError):
        return False
    return set(required_ids) <= bound


def codes(corpus, *, registry_revision=None, n_min=None, n_max=None, distance_at_least=None,
          metric_definition_id=None, metric_revision=None, sector='joint', construction=None, limit=100, check_live_lean=True):
    """Read qualifying legacy codes. Workspace paging merges results with no internal limit."""
    if limit is not None and not 1 <= limit <= 200:
        raise ValueError('limit must be 1..200')
    for value in (n_min, n_max, distance_at_least):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('Code filter bounds must be nonnegative integers')
    if n_min is not None and n_max is not None and n_min > n_max:
        raise ValueError('n_min exceeds n_max')
    if distance_at_least is not None and not metric_definition_id:
        raise ValueError('A distance hard condition needs an exact metric_definition_id')
    if metric_revision is not None and distance_at_least is None:
        raise ValueError('metric_revision requires a distance hard condition')
    if sector not in {'X', 'Z', 'joint'}:
        raise ValueError('Unknown distance sector')
    registry = Registry(corpus)
    state, fixed = registry.read(registry_revision)
    records = registry.records_from_state(state)
    reviews = review_states(registry, state, records)
    from ..lean.integration import lean_record_states
    builds = lean_record_states(registry, state, records, reviews, check_live_inputs=check_live_lean)
    results = []
    metric = records.get(metric_definition_id) or {}
    metric_matches = metric_revision is None or metric.get('revision') == metric_revision
    for identifier, code in sorted(records.items()):
        if code['kind'] != 'code_instance' or not metric_matches:
            continue
        if reviews[identifier]['effective_status'] in {'stale', 'disputed'}:
            continue
        data = code['data']
        n = (data.get('parameters') or {}).get('n')
        if (n_min is not None or n_max is not None) and type(n) is not int:
            continue
        if n_min is not None and n < n_min or n_max is not None and n > n_max:
            continue
        constructor = records.get(data.get('construction_id'))
        if construction and (not constructor or construction not in {constructor['id'], constructor['data'].get('construction_kind')}):
            continue
        matching = []
        if distance_at_least is not None:
            for claim_id in data.get('distance_claim_ids') or []:
                claim = records.get(claim_id)
                if claim is None or claim['kind'] != 'claim' or reviews[claim_id]['effective_status'] in {'stale', 'disputed'}:
                    continue
                measurement = claim['data']
                if distance_issues(measurement) or measurement['subject_id'] != identifier:
                    continue
                if measurement['metric_definition_id'] != metric_definition_id or measurement['sector'] != sector:
                    continue
                if measurement['relation'] not in {'lower_bound', 'exact', 'interval'} or measurement['lower_bound'] < distance_at_least:
                    continue
                if measurement['presentation_id'] not in (data.get('presentation_ids') or []):
                    continue
                required = [identifier, measurement['presentation_id'], metric_definition_id, claim_id]
                evidence = [records[e] for e in claim['evidence_ids'] if e in records and records[e]['kind'] == 'evidence'
                            and evidence_current(registry, records[e], records, required, reviews, builds)]
                if evidence:
                    matching.append({'claim_id': claim_id, 'claim_revision': claim['revision'],
                                     'relation': measurement['relation'], 'lower_bound': measurement['lower_bound'],
                                     'upper_bound': measurement['upper_bound'], 'assumptions': measurement['assumptions'],
                                     'evidence': [{'id': e['id'], 'revision': e['revision'],
                                                   'kind': e['data']['evidence_kind']} for e in evidence]})
            if not matching:
                continue
        results.append({'id': identifier, 'revision': code['revision'], 'parameters': data['parameters'],
                        'review_status': code['review']['status'], 'distance_claims': matching})
    scope = {'registry_revision': fixed, 'metric_definition_id': metric_definition_id, 'sector': sector}
    if metric_revision is not None:
        scope['metric_revision'] = metric_revision
    return {'scope': scope,
            'results': results[:limit], 'truncated': limit is not None and len(results) > limit,
            'evidence_policy': 'Known lower bound with evidence bound to the current claim, instance, presentation and metric revisions',
            'absence_note': 'No qualifying record in this fixed scope; not a nonexistence result'}
