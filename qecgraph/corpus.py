"""Read-only corpus projection, fixed once per query and shared across transports."""
from __future__ import annotations

import copy
from urllib.parse import quote

from .graph import canonical, hash_text
from .registry import Registry
from .store import GraphInput
from . import query


def occurrence_id(version_id, node_id):
    return 'occurrence:' + hash_text(version_id) + ':' + node_id


def project(corpus, registry_revision=None, source_version_id=None):
    registry = Registry(corpus)
    state, fixed = registry.read(registry_revision)
    if source_version_id and source_version_id not in state['versions']:
        raise ValueError(f'Unknown source version in scope: {source_version_id}')
    selected = [source_version_id] if source_version_id else sorted(state['versions'])
    nodes, edges, labels, versions = [], [], {}, {}
    partial = False
    for version_id in selected:
        graph, _, version = registry.source_graph(version_id, fixed)
        versions[version_id] = version
        partial |= graph['extraction_status'] == 'partial'
        for original in graph['nodes']:
            node = copy.deepcopy(original)
            node['id'] = occurrence_id(version_id, original['id'])
            node['original_node_id'] = original['id']
            node['provenance'] = {'source_version_id': version_id, 'work_id': version['work_id'],
                                  'snapshot_id': version['snapshot_id']}
            if node.get('source'):
                node['source'].update(node['provenance'])
                node['source']['archive_uri'] = 'qecgraph://source/' + quote(version_id, safe='') + '/' + quote(node['source']['path'])
            node['labels'] = [version_id + '::' + label for label in original['labels']]
            # Full original IDs are also version-qualified to disambiguate revisions.
            for label in node['labels'] + [version_id + '::' + original['id']]:
                labels.setdefault(label, []).append(node['id'])
            nodes.append(node)
        for original in graph['edges']:
            edge = copy.deepcopy(original)
            edge['id'] = occurrence_id(version_id, original['id'])
            edge['source'] = occurrence_id(version_id, edge['source'])
            edge['target'] = occurrence_id(version_id, edge['target'])
            edges.append(edge)
    for identifier in sorted(state['records']):
        record = registry.record(identifier, registry_revision=fixed)
        nodes.append({'id': identifier, 'kind': record['kind'], 'title': record['title'],
                      'labels': record['aliases'], 'latex': '', 'data': record['data'], 'record': record,
                      'review_status': record['review']['status'], 'verification_status': 'not_verified',
                      'content_sha256': record['content_sha256'], 'origin': 'registry', 'source': None,
                      'provenance': record['provenance']})
    lookup = {n['id']: n for n in nodes}
    if len(lookup) != len(nodes):
        raise ValueError('Domain ID collides with source occurrence namespace')
    for link in state['links']:
        source = occurrence_id(link['source_version_id'], link['source_node_id'])
        if source not in lookup or link['claim_id'] not in lookup:
            continue
        target = lookup[link['claim_id']]
        fresh = target['record']['revision'] == link['claim_revision'] and target['content_sha256'] == link['claim_content_sha256']
        edges.append({'id': link['id'], 'source': source, 'target': link['claim_id'], 'relation': 'normalizes_to',
                      'status': ('candidate' if link['status'] == 'proposed' else link['status']) if fresh else 'stale',
                      'evidence': link})
    for node in nodes:
        record = node.get('record')
        if not record:
            continue
        for ref in record['refs']:
            target = lookup.get(ref.get('target'))
            if not target:
                continue
            fresh = not ref.get('revision') or target.get('record', {}).get('revision') == ref['revision']
            edges.append({'id': 'ref:' + hash_text(canonical([node['id'], ref])), 'source': node['id'],
                          'target': ref['target'], 'relation': ref['relation'],
                          'status': ref.get('status', 'declared') if fresh else 'stale', 'evidence': ref})
    graph = {'schema_version': 'qecgraph.corpus_graph.v1', 'snapshot_id': fixed,
             'project_source_hash': hash_text(canonical(versions)), 'nodes': nodes, 'edges': edges,
             'labels': labels, 'extraction_status': 'partial' if partial else 'complete_for_supported_syntax'}
    scope = {'registry_revision': fixed, 'source_versions': versions,
             'entity_revisions': {k: v['current_revision'] for k, v in state['records'].items()}}
    return GraphInput(graph), scope


def execute(corpus, action, identifier=None, *, registry_revision=None, source_version_id=None,
            text=None, kind=None, limit=20, depth=2, include_candidates=False, max_nodes=60):
    graph_input, scope = project(corpus, registry_revision, source_version_id)
    if action != 'search':
        if source_version_id and identifier not in {n['id'] for n in graph_input.graph['nodes']} and '::' not in identifier:
            identifier = source_version_id + '::' + identifier
        if identifier not in {n['id'] for n in graph_input.graph['nodes']} and '::' not in identifier:
            raise ValueError('Cross-document labels/IDs require source_version_id::selector or an exact entity/occurrence ID')
    if action == 'search':
        result = query.search(graph_input, text, kind, limit)
    elif action == 'show':
        result = query.show(graph_input, identifier)
    elif action == 'context':
        result = query.context(graph_input, identifier, depth, include_candidates, max_nodes)
    elif action in {'deps', 'impact'}:
        result = query.dependencies(graph_input, identifier, depth, include_candidates, action == 'impact', max_nodes)
    else:
        raise ValueError('Unknown read-only corpus action')
    result['scope'] = scope
    result['extraction_status'] = graph_input.graph['extraction_status']
    result['absence_note'] = 'No match means no result in this fixed scope; it does not establish nonexistence.'
    return result
