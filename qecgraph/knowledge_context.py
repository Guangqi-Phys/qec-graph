"""Bounded typed traversal and task context; selection is not inference."""
from __future__ import annotations

from collections import defaultdict, deque

from .core.graph import canonical, hash_text
from .corpus import occurrence_id
from .domain.research import RELATIONS, key
from .domain.status import eligible
from .core.errors import ToolError
from .query import answer_node

PURPOSES = ('theorem', 'performance', 'construction', 'thought', 'lean')


def _identity(node):
    return node['id'], node.get('revision') if node.get('schema') == 'qecgraph.research' else None


def _binding(identity):
    return {'id': identity[0], 'revision': identity[1]}


def current_field(session, record, field):
    evidence = record['field_evidence'].get('/data/' + field, {})
    span = evidence.get('source_locator') or {}
    return (evidence.get('status') == 'known' and bool(span)
            and session.source_snapshot_id(span.get('source_version_id')) == span.get('snapshot_id'))


def trace(session, args):
    candidates = args.get('include_candidates', False)
    nodes = {_identity(n): answer_node(n, candidates)[0] for n in session.graph.source.graph['nodes']}
    nodes.update({k: v for k, v in session.visible.items()})
    root_record = session._research(args['identifier'], args.get('revision'))
    if root_record:
        root = _identity(root_record)
    elif args.get('revision') or args['identifier'] in session._research_ids:
        raise ToolError('NOT_FOUND', 'No eligible record revision')
    else:
        from .query import resolve, SelectionError
        try:
            root = resolve(session.graph.source.graph, args['identifier']), None
        except SelectionError as exc:
            raise ToolError(exc.code, str(exc), exc.details) from exc
    edges = []
    for edge in session.graph.source.graph['edges']:
        if eligible(edge, candidates):
            edges.append({**edge, 'source': _binding((edge['source'], None)), 'target': _binding((edge['target'], None))})
    unresolved = defaultdict(list)
    for identity, record in session.visible.items():
        for field in RELATIONS.get(record['kind'], {}):
            value = record['data'].get(field)
            if value is None:
                unresolved[identity].append({'id': record['id'], 'revision': record['revision'], 'field': field,
                                             'status': record['field_evidence'].get('/data/' + field, {}).get('status', 'not_extracted')})
                continue
            evidence = record['field_evidence'].get('/data/' + field, {})
            status = 'proposed' if record['data'].get('review_status') == 'proposed' else 'declared'
            if record['kind'] == 'research_thought' and record['data']['attribution'] == 'editorial_inference':
                status = 'candidate'
            if field == 'source_ref':
                status = 'observed'
            span = evidence.get('source_locator')
            if span and not current_field(session, record, field):
                status = 'stale'
            for ref in value if field.endswith('_refs') else [value]:
                edge = {'source': _binding(identity), 'target': ref, 'relation': field,
                        'status': status, 'evidence': {'record_ref': _binding(identity), 'field_pointer': '/data/' + field}}
                if key(ref) not in nodes:
                    unresolved[identity].append({'id': record['id'], 'revision': record['revision'],
                                                 'field': field, 'target': ref, 'status': 'unresolved'})
                elif eligible(edge, candidates):
                    edges.append(edge)
        evidence_edges = {}
        for field, evidence in record['field_evidence'].items():
            span = evidence.get('source_locator')
            if not span or not current_field(session, record, field.removeprefix('/data/')):
                continue
            target = occurrence_id(span['source_version_id'], span['node_id']), None
            if target in nodes:
                signature = canonical(span)
                edge = evidence_edges.setdefault(signature, {'source': _binding(identity), 'target': _binding(target),
                    'relation': 'evidenced_by', 'status': 'observed',
                    'evidence': {'record_ref': _binding(identity), 'field_pointers': []}})
                edge['evidence']['field_pointers'].append(field)
        edges.extend(evidence_edges.values())
    allowed = set(args.get('relations') or [])
    known = {e['relation'] for e in session.graph.source.graph['edges']} | {f for fields in RELATIONS.values() for f in fields} | {'evidenced_by'}
    if allowed - known:
        raise ToolError('INVALID_ARGUMENT', 'Unknown relation filter', {'relations': sorted(allowed - known)})
    direction = args.get('direction', 'outgoing')
    adjacent = defaultdict(list)
    for edge in edges:
        if allowed and edge['relation'] not in allowed:
            continue
        source, target = (edge['source']['id'], edge['source'].get('revision')), (edge['target']['id'], edge['target'].get('revision'))
        if direction in ('outgoing', 'both'):
            adjacent[source].append((target, edge))
        if direction in ('incoming', 'both'):
            adjacent[target].append((source, edge))
    depth, maximum = args.get('depth', min(2, session.graph.max_depth)), args.get('max_nodes', session.graph.max_nodes)
    chosen, seen, pending, selected, omitted = [root], {root}, deque([(root, 0)]), [], set()
    while pending:
        current, level = pending.popleft()
        for target, edge in adjacent[current]:
            if target not in seen:
                if level >= depth or len(chosen) >= maximum:
                    omitted.add(target)
                    continue
                chosen.append(target)
                seen.add(target)
                pending.append((target, level + 1))
            if edge not in selected:
                selected.append(edge)
    return {'root_id': root[0], 'root_revision': root[1], 'nodes': [nodes[k] for k in chosen],
            'edges': selected, 'unresolved': [u for identity in chosen for u in unresolved[identity]],
            'truncated': bool(omitted-seen), 'omitted_frontier_count': len(omitted-seen),
            'interpretation': 'Typed source/record associations; references and proximity are not proof dependencies'}


def bounded_trace(session, args, maximum, metadata):
    """Reduce traversal breadth/depth while preserving the complete root."""
    options = dict(args)
    options.setdefault('depth', min(2, session.graph.max_depth))
    options.setdefault('max_nodes', session.graph.max_nodes)
    reduced = False
    while True:
        data = trace(session, options)
        data['effective_parameters'] = {k: options[k] for k in ('depth', 'max_nodes')}
        data['truncated'] = data['truncated'] or reduced
        required = len(canonical({**data, **metadata, 'continuation': None}))
        if required <= maximum:
            return data
        if options['depth'] > 1:
            options['depth'] -= 1
        elif options['max_nodes'] > 1 and len(data['nodes']) > 1:
            options['max_nodes'] = max(1, len(data['nodes']) // 2)
        elif options['depth'] > 0:
            options['depth'] = 0
        else:
            raise ToolError('BUDGET_TOO_SMALL', 'Complete root exceeds the response budget',
                            {'required_chars': required, 'session_max_chars': session.graph.max_chars,
                             'suggestions': [{'tool': 'qec_fetch', 'identifier': args['identifier'],
                                              'char_start': (data['nodes'][0].get('source') or {}).get('char_start')} ]})
        reduced = True


def context(session, args, maximum, metadata):
    purpose = args['purpose']
    data = trace(session, {k: v for k, v in args.items() if k != 'purpose'})
    root = data['nodes'][0]
    selected = {_identity(n) for n in data['nodes']}
    candidates = args.get('include_candidates', False)
    omitted = data['omitted_frontier_count']
    max_nodes = args.get('max_nodes', session.graph.max_nodes)

    def append(node, reason):
        nonlocal omitted
        identity = _identity(node)
        if identity in selected:
            return
        if len(selected) == max_nodes:
            omitted += 1
            return
        projected = answer_node(node, candidates)[0] if 'origin' in node else dict(node)
        data['nodes'].append({**projected, 'context_role': reason})
        selected.add(identity)

    if purpose in {'theorem', 'lean'} and root.get('source'):
        graph = session.graph.source.graph
        lookup = {n['id']: n for n in graph['nodes']}
        for edge in graph['edges']:
            if edge['target'] == root['id'] and edge['relation'] in {'proof_of', 'proof_of_candidate'} and eligible(edge, candidates):
                append(lookup[edge['source']], 'proof_text')
                proof = trace(session, {'identifier': edge['source'], 'depth': args.get('depth', 2),
                                         'max_nodes': max_nodes, 'include_candidates': candidates})
                for node in proof['nodes']:
                    append(node, 'proof_context')
                omitted += proof['omitted_frontier_count']
        ancestor = session.knowledge.parents.get(root['id'])
        if ancestor in lookup:
            append(lookup[ancestor], 'section_heading')
            for child in session.knowledge.children[ancestor]:
                node = lookup[child]
                if node['kind'] in {'definition', 'assumption', 'notation'}:
                    append(node, 'local_context_not_inferred_dependency')
    kinds = {n['kind'] for n in data['nodes']}
    requirements = {
        'theorem': {'definitions': {'definition'}, 'explicit_assumptions': {'assumption'}, 'proof': {'proof'}},
        'lean': {'definitions': {'definition'}, 'explicit_assumptions': {'assumption'},
                 'formalization_mapping': {'formalization', 'lean_declaration'}},
        'performance': {'metric': {'metric'}, 'experiment': {'experiment'}, 'code': {'quantum_code'},
                        'check_matrix': {'check_matrix'}, 'circuit': {'syndrome_measurement_circuit'},
                        'noise_instance': {'noise_model_instance'}, 'noise_model': {'noise_model'}, 'decoder': {'decoder'}},
        'construction': {'construction': {'construction'}, 'code': {'quantum_code'}, 'check_matrix': {'check_matrix'}},
        'thought': {'thought': {'research_thought'}, 'source': {'paper_version', 'paragraph', 'section'}},
    }[purpose]
    unknown = [{'id': n['id'], 'revision': n.get('revision'), 'field': field, **evidence}
               for n in data['nodes'] for field, evidence in n.get('field_evidence', {}).items()
               if evidence['status'] != 'known']
    missing = [name for name, types in requirements.items() if not kinds & types]
    data.update(purpose=purpose, missing_components=missing, unknown_fields=unknown,
                conflicts=[f for f in unknown if f['status'] == 'conflicting'],
                context_complete=False, completeness='Structural selection only; semantic prerequisites require reading',
                omitted_node_count_at_least=omitted, truncated=bool(omitted), continuation=None)
    if purpose == 'lean':
        data['formalization_status'] = 'Preparation only; no Lean build or semantic equivalence claim'
    # Preserve the root whole, trimming only complete supporting records/blocks.
    while len(canonical({**data, **metadata})) > maximum and len(data['nodes']) > 1:
        removed = data['nodes'].pop()
        selected.discard(_identity(removed))
        data['edges'] = [e for e in data['edges'] if
                         (e['source']['id'], e['source'].get('revision')) in selected and
                         (e['target']['id'], e['target'].get('revision')) in selected]
        data['truncated'] = True
        data['omitted_node_count_at_least'] += 1
        ids = {n['id'] for n in data['nodes']}
        for field in ('unknown_fields', 'conflicts', 'unresolved'):
            data[field] = [entry for entry in data[field] if entry.get('id') in ids]
        kinds = {n['kind'] for n in data['nodes']}
        data['missing_components'] = [name for name, types in requirements.items() if not kinds & types]
    if len(canonical({**data, **metadata})) > maximum:
        raise ToolError('BUDGET_TOO_SMALL', 'Root context/evidence cannot fit without truncation',
                        {'required_chars': len(canonical({**data, **metadata})),
                         'suggestions': [{'tool': 'qec_fetch', 'identifier': args['identifier'], 'view': 'outline'}]})
    return data


def filter_codes(session, rows, args):
    result = []
    weight_fields = {'check_weight_max', 'check_weight_sector', 'check_weight_scope'}
    if weight_fields & args.keys() and not weight_fields <= args.keys():
        raise ToolError('INVALID_ARGUMENT', 'Check-weight filter requires max, sector and scope together')
    if args.get('k_min', 0) > args.get('k_max', 10**9):
        raise ToolError('INVALID_ARGUMENT', 'k_min exceeds k_max')
    for row in rows:
        record = row.get('record', row)
        data = record.get('data', {})
        if args.get('classification') and (data.get('classification') != args['classification'] or
                                           not current_field(session, record, 'classification')):
            continue
        k = data.get('k')
        if ('k_min' in args and (k is None or k < args['k_min'])) or ('k_max' in args and (k is None or k > args['k_max'])):
            continue
        if 'check_weight_max' in args:
            matrices = []
            for binding in data.get('check_matrix_refs') or []:
                matrix = session.visible.get(key(binding))
                if not matrix or matrix['data'].get('code_ref') != {'id': record['id'], 'revision': record['revision']}:
                    continue
                if not current_field(session, matrix, 'check_weight_statistics'):
                    continue
                if any(metric['sector'] == args['check_weight_sector'] and metric['scope'] == args['check_weight_scope']
                       and metric.get('max') is not None and metric['max'] <= args['check_weight_max']
                       for metric in matrix['data'].get('check_weight_statistics') or []):
                    matrices.append(matrix)
            if not matrices:
                continue
            if 'distance_estimates' in row:
                matches = [c for c in row['distance_estimates'] if key(c['data']['subject_ref']) in {_identity(m) for m in matrices}]
                if not matches:
                    continue
                row = {**row, 'distance_estimates': matches}
            row = {'record': record, **({k: v for k, v in row.items() if k != 'record'} if 'record' in row else {}),
                   'matching_check_matrices': matrices}
        result.append(row)
    return result


def comparison_group(bindings, missing):
    if missing:
        return None
    return hash_text(canonical({name: {'id': row['id'], 'revision': row['revision']}
                               for name, row in bindings.items() if row is not None and name not in {'source', 'experiment'}}))
