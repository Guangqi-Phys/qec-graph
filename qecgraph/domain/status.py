"""Shared query eligibility and derived review freshness; no authority rewrites."""
from __future__ import annotations

from copy import deepcopy

INACTIVE = {'stale', 'unbound_review', 'unresolved'}
LEAN_RECORD_KINDS = {'lean_declaration', 'formalization'}


def eligible(edge, include_candidates=False):
    if edge['status'] in INACTIVE:
        return False
    candidate = edge['status'] in {'candidate', 'proposed'} or edge['relation'].endswith('_candidate')
    return include_candidates or not candidate


def annotation_eligible(annotation, include_candidates=False):
    status = annotation.get('effective_status', annotation.get('review_status', 'draft'))
    return status not in INACTIVE and (
        include_candidates or status not in {'candidate', 'proposed', 'needs_review'})


def review_states(registry, state, records, *, verified_versions=()):
    from ..review import final_records, read_proposal, read_review
    result, assets, checked_reviews = {}, {}, {}
    sources = dict.fromkeys(verified_versions)

    def reasons_for(binding):
        reasons = []
        try:
            review = read_review(registry, binding['review_id'])
            proposal = read_proposal(registry, review['proposal_id'])
            expected = {binding['id']: binding for binding in review['input_bindings']['records']}
            for final in final_records(proposal, review):
                expected[final['id']] = {key: final[key] for key in ('id', 'revision', 'content_sha256')}
            for target_id, expected_record in expected.items():
                target = records.get(target_id)
                if target is None or any(target[key] != expected_record[key] for key in ('revision', 'content_sha256')):
                    reasons.append({'code': 'review_input_changed', 'target': target_id, 'expected': expected_record})
            for asset in review['input_bindings']['assets']:
                uri = asset['uri']
                if uri not in assets:
                    try:
                        registry.asset_bytes(uri)
                        assets[uri] = None
                    except (OSError, ValueError) as exc:
                        assets[uri] = str(exc)
                if assets[uri]:
                    reasons.append({'code': 'review_asset_unavailable', 'asset': uri, 'message': assets[uri]})
            for version_id, expected_source in review['input_bindings']['source_versions'].items():
                if state['versions'].get(version_id) != expected_source:
                    reasons.append({'code': 'review_source_changed', 'source_version_id': version_id})
                    continue
                if version_id not in sources:
                    try:
                        registry.validate_source_snapshot(expected_source)
                        sources[version_id] = None
                    except (OSError, ValueError) as exc:
                        sources[version_id] = str(exc)
                if sources[version_id]:
                    reasons.append({'code': 'review_source_unavailable', 'source_version_id': version_id,
                                    'message': sources[version_id]})
        except (OSError, ValueError, KeyError) as exc:
            reasons.append({'code': 'review_binding_unavailable', 'message': str(exc)})
        return reasons

    for identifier, record in records.items():
        binding = record['review']
        status = binding['status']
        reasons = []
        if status == 'reviewed':
            review_id = binding.get('review_id')
            if not isinstance(review_id, str):
                reasons = reasons_for(binding)
            else:
                if review_id not in checked_reviews:
                    checked_reviews[review_id] = reasons_for(binding)
                if checked_reviews[review_id]:
                    reasons = deepcopy(checked_reviews[review_id])
            if reasons:
                status = 'stale'
        result[identifier] = {'effective_status': status, 'reasons': reasons}
    return result


def lean_build_states(registry, state, records, reviews, *, check_live_inputs=True):
    """Load deferred Lean freshness only when the state actually contains Lean material.

    Read projections must not import the experimental Lean builder for an ordinary
    corpus/workspace. The import stays inside this helper so the database, query and
    MCP boundaries stay independent of Lean as documented in the system design.
    """
    if not state.get('lean_projects') and not any(
            record.get('kind') in LEAN_RECORD_KINDS
            or record.get('kind') == 'evidence' and (record.get('data') or {}).get('evidence_kind') == 'lean_build'
            for record in records.values()):
        return {}
    from ..lean.integration import lean_record_states
    return lean_record_states(registry, state, records, reviews, check_live_inputs=check_live_inputs)


def reviewed_cycles(graph):
    """SCCs only in the active, reviewed logical subgraph; citation rings are legal."""
    edges = [edge for edge in graph['edges'] if edge['relation'] == 'depends_on_reviewed' and eligible(edge)]
    adjacent, reverse = {}, {}
    for edge in edges:
        source, target = edge['source'], edge['target']
        adjacent.setdefault(source, set()).add(target)
        adjacent.setdefault(target, set())
        reverse.setdefault(target, set()).add(source)
        reverse.setdefault(source, set())
    visited, order = set(), []
    for root in sorted(adjacent):
        if root in visited:
            continue
        visited.add(root)
        stack = [(root, iter(sorted(adjacent[root])))]
        while stack:
            node, children = stack[-1]
            target = next(children, None)
            if target is None:
                order.append(node)
                stack.pop()
            elif target not in visited:
                visited.add(target)
                stack.append((target, iter(sorted(adjacent[target]))))
    visited, issues = set(), []
    for root in reversed(order):
        if root in visited:
            continue
        component, queue = set(), [root]
        visited.add(root)
        while queue:
            node = queue.pop()
            component.add(node)
            for target in reverse[node]:
                if target not in visited:
                    visited.add(target)
                    queue.append(target)
        if len(component) > 1 or root in adjacent[root]:
            issues.append({'code': 'reviewed_dependency_cycle', 'severity': 'warning',
                           'node_ids': sorted(component),
                           'edge_ids': sorted(e['id'] for e in edges if e['source'] in component and e['target'] in component),
                           'disposition': 'requires_judgment; preserved, not automatically removed'})
    return issues
