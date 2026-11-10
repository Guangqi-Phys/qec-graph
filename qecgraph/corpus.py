"""Read-only corpus projection, fixed once per query and shared across transports."""
from __future__ import annotations

from urllib.parse import quote

from .core.graph import canonical, hash_text
from .registry import Registry
from .store import GraphInput, source_span_index
from . import query
from .domain.status import lean_build_states, review_states
from .validators import ENDPOINTS


def occurrence_id(version_id, node_id):
    return 'occurrence:' + hash_text(version_id) + ':' + node_id


def project(corpus, registry_revision=None, source_version_id=None, *,
            check_live_lean=True, verify_sources=False, manifest_hashes=None):
    registry = Registry(corpus)
    state, fixed = registry.read(registry_revision)
    return _project_state(registry, state, fixed, source_version_id,
                          check_live_lean=check_live_lean, verify_sources=verify_sources, manifest_hashes=manifest_hashes)


def _project_state(registry, state, fixed, source_version_id=None, *,
                   check_live_lean=True, verify_sources=False, records=None, verified_spans=None, manifest_hashes=None):
    if source_version_id and source_version_id not in state['versions']:
        raise ValueError(f'Unknown source version in scope: {source_version_id}')
    selected = [source_version_id] if source_version_id else sorted(state['versions'])
    nodes, edges, labels, versions = [], [], {}, {}
    partial = False
    for version_id in selected:
        graph, snapshot, version = registry.source_graph_from_state(
            state, version_id, fixed, verify=verify_sources, manifest_hashes=manifest_hashes)
        if verify_sources and verified_spans is not None:
            verified_spans[snapshot, version['snapshot_id']] = source_span_index(graph)
        versions[version_id] = version
        partial |= graph['extraction_status'] == 'partial'
        occurrence_prefix = occurrence_id(version_id, '')
        label_prefix = version_id + '::'
        archive_prefix = 'qecgraph://source/' + quote(version_id, safe='') + '/'
        # The loader gives this projection its own freshly decoded graph.
        for node in graph['nodes']:
            original_id = node['id']
            node['id'] = occurrence_prefix + original_id
            node['original_node_id'] = original_id
            node['provenance'] = {'source_version_id': version_id, 'work_id': version['work_id'],
                                  'snapshot_id': version['snapshot_id']}
            if node.get('source'):
                node['source'].update(node['provenance'])
                node['source']['archive_uri'] = archive_prefix + quote(node['source']['path'])
            node['labels'] = [label_prefix + label for label in node['labels']]
            # Full original IDs are also version-qualified to disambiguate revisions.
            for label in node['labels'] + [label_prefix + original_id]:
                labels.setdefault(label, []).append(node['id'])
            nodes.append(node)
        for edge in graph['edges']:
            edge['id'] = occurrence_prefix + edge['id']
            edge['source'] = occurrence_prefix + edge['source']
            edge['target'] = occurrence_prefix + edge['target']
            edges.append(edge)
    if records is None:
        records = registry.records_from_state(state, sorted(state['records']))
    reviews = review_states(registry, state, records, verified_versions=versions if verify_sources else ())
    builds = lean_build_states(registry, state, records, reviews, check_live_inputs=check_live_lean)
    for identifier in sorted(records):
        record = records[identifier]
        node = {'id': identifier, 'kind': record['kind'], 'title': record['title'],
                      'labels': record['aliases'], 'latex': '', 'data': record['data'], 'record': record,
                      'review_status': reviews[identifier]['effective_status'], 'review_binding': reviews[identifier],
                      'verification_status': 'not_verified',
                      'content_sha256': record['content_sha256'], 'origin': 'registry', 'source': None,
                      'provenance': record['provenance']}
        if identifier in builds:
            node['build_binding'] = builds[identifier]
            if record['kind'] == 'lean_declaration':
                node['source'] = record['data'].get('source_locator')
                node['verification_status'] = ('actual_formal_statement_build_and_axiom_policy_passed'
                    if builds[identifier]['effective_status'] == 'current' and record['data']['proof_progress'] == 'build_passed'
                    else 'historical_or_name_only_Lean_export')
        nodes.append(node)
    lookup = {n['id']: n for n in nodes}
    if len(lookup) != len(nodes):
        raise ValueError('Domain ID collides with source occurrence namespace')
    for link in state['links']:
        source = occurrence_id(link['source_version_id'], link['source_node_id'])
        occurrence, target = lookup.get(source), lookup.get(link['claim_id'])
        if occurrence is None or 'original_node_id' not in occurrence or target is None:
            continue
        source_matches = (occurrence['provenance']['snapshot_id'] == link['source_snapshot_id']
                          and occurrence['content_sha256'] == link['source_content_sha256'])
        if not source_matches and occurrence['kind'] not in ENDPOINTS['normalizes_to'][0]:
            continue  # The historical link remains bound to the original occurrence.
        fresh = (source_matches and target['record']['revision'] == link['claim_revision']
                 and target['content_sha256'] == link['claim_content_sha256'])
        edges.append({'id': link['id'], 'source': source, 'target': link['claim_id'], 'relation': 'normalizes_to',
                      'status': ('candidate' if link['status'] == 'proposed' else link['status']) if fresh else 'stale',
                      'evidence': link})
    unresolved = []
    for node in nodes:
        record = node.get('record')
        if not record:
            continue
        if record['kind'] == 'formalization' and node['id'] in builds:
            for source in record['data'].get('source_refs', []):
                if not all(key in source for key in ('source_version_id', 'node_id')):
                    continue
                target_id = occurrence_id(source['source_version_id'], source['node_id'])
                if target_id in lookup:
                    edges.append({'id': 'mapping-source:' + hash_text(canonical([node['id'], source])),
                                  'source': node['id'], 'target': target_id, 'relation': 'maps_source_occurrence',
                                  'status': 'candidate' if builds[node['id']]['effective_status'] == 'current' else 'stale',
                                  'evidence': source})
        for ref in record['refs']:
            target = lookup.get(ref.get('target'))
            if not target:
                unresolved.append({'code': 'unresolved_reference', 'record_id': node['id'], 'reference': ref})
                continue
            fresh = not ref.get('revision') or target.get('record', {}).get('revision') == ref['revision']
            status = ref.get('status', 'declared') if fresh else 'stale'
            if ref['relation'] == 'depends_on_reviewed':
                review_status = reviews[node['id']]['effective_status']
                if review_status == 'stale':
                    status = 'stale'
                elif fresh and review_status != 'reviewed':
                    status = 'unbound_review'
            if any(endpoint in builds and builds[endpoint]['effective_status'] != 'current'
                   for endpoint in (node['id'], ref['target'])):
                status = 'stale'
            if ref['relation'] == 'formalizes' and record['provenance'].get('method') == 'actual_lean_environment_export':
                matched = builds[node['id']]['semantic_review'] == 'matched'
                if not matched and status not in {'stale', 'unbound_review', 'unresolved'}:
                    status = 'candidate'
            edges.append({'id': 'ref:' + hash_text(canonical([node['id'], ref])), 'source': node['id'],
                          'target': ref['target'], 'relation': ref['relation'],
                          'status': status, 'evidence': ref})
    graph = {'schema': 'qecgraph.corpus_graph', 'snapshot_id': fixed,
             'project_source_hash': hash_text(canonical(versions)), 'nodes': nodes, 'edges': edges,
             'labels': labels, 'diagnostics': unresolved,
             'extraction_status': 'partial' if partial else 'complete_for_supported_syntax'}
    scope = {'registry_revision': fixed, 'source_versions': versions,
             'entity_revisions': {k: v['current_revision'] for k, v in state['records'].items()}}
    return GraphInput(graph), scope


def execute(corpus, action, identifier=None, *, registry_revision=None, source_version_id=None,
            text=None, kind=None, limit=20, depth=2, include_candidates=False, max_nodes=60):
    graph_input, scope = project(corpus, registry_revision, source_version_id)
    session = query.QuerySession(graph_input)
    if action != 'search':
        identifier = session.corpus_identifier(identifier, source_version_id)
        if identifier is None:
            raise ValueError('Cross-document labels/IDs require source_version_id::selector or an exact entity/occurrence ID')
    result = session.execute(action, identifier, text=text, kind=kind, limit=limit, depth=depth,
                             include_candidates=include_candidates, max_nodes=max_nodes)
    result['scope'] = scope
    result['extraction_status'] = graph_input.graph['extraction_status']
    result['diagnostics'] = graph_input.graph['diagnostics']
    result['absence_note'] = 'No match means no result in this fixed scope; it does not establish nonexistence.'
    return result
