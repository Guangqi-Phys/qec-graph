"""Shared query eligibility and derived review freshness; no authority rewrites."""
from __future__ import annotations


INACTIVE = {'stale', 'unbound_review', 'unresolved'}


def eligible(edge, include_candidates=False):
    if edge['status'] in INACTIVE:
        return False
    candidate = edge['status'] in {'candidate', 'proposed'} or edge['relation'].endswith('_candidate')
    return include_candidates or not candidate


def annotation_eligible(annotation, include_candidates=False):
    status = annotation.get('effective_status', annotation.get('review_status', 'draft'))
    return status not in INACTIVE and (
        include_candidates or status not in {'candidate', 'proposed', 'needs_review'})


def reviewed_cycles(graph):
    """SCCs only in the active, reviewed logical subgraph; citation rings are legal."""
    edges = [edge for edge in graph['edges'] if edge['relation'] == 'depends_on_reviewed' and eligible(edge)]
    adjacent: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
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
