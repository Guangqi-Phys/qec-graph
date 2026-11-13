"""Assemble the source graph of one published workspace."""
from collections import defaultdict
from urllib.parse import quote

from .core.graph import canonical, hash_text
from .source.bibliography import registered_identifier
from .store import GraphInput, source_span_index


def occurrence_id(version_id, node_id):
    return 'occurrence:' + hash_text(version_id) + ':' + node_id


def bibliography_edges(nodes, edges, versions):
    documents = defaultdict(set)
    for node in nodes:
        if node['kind'] == 'document':
            version = versions[node['provenance']['source_version_id']]
            identifier = registered_identifier(version.get('canonical_url'))
            if identifier:
                documents[identifier].add(node['id'])

    cited = {edge['target'] for edge in edges if edge['relation'] == 'cites'}
    for node in nodes:
        if node['kind'] != 'bib_entry':
            continue
        identifiers = node['data'].get('bibliography_ids', [])
        conflicting_ids = len({identifier.split(':', 1)[0] for identifier in identifiers}) < len(identifiers)
        matches = {identifier: documents[identifier] for identifier in identifiers
                   if identifier in documents}
        targets = sorted(set().union(*matches.values()))
        node['data']['registered_targets'] = targets
        ambiguous = conflicting_ids or len(targets) > 1
        node['data']['identity_status'] = 'ambiguous' if ambiguous else 'matched' if targets else 'unmatched'
        if not ambiguous and targets and node['id'] in cited:
            edge = {'source': node['id'], 'target': targets[0], 'relation': 'cites_paper', 'status': 'observed',
                    'evidence': {'method': 'registered_identifier', 'identifiers': sorted(matches),
                                 'source': node['source']}}
            yield {'id': 'edge:' + hash_text(canonical(edge))[:24], **edge}


def project_sources(registry, state, fixed, *, verify_sources=False, verified_spans=None, manifest_hashes=None):
    selected = sorted(state['versions'])
    nodes, edges, labels, versions = [], [], {}, {}
    partial = recovered = False
    normalized = {(m.get('source_version_id'), m.get('source_snapshot_id')): m
                  for m in state.get('materials', {}).values() if m.get('normalization_id')}
    for version_id in selected:
        graph, snapshot, version = registry.source_graph_from_state(
            state, version_id, fixed, verify=verify_sources, manifest_hashes=manifest_hashes)
        if verify_sources and verified_spans is not None:
            verified_spans[snapshot, version['snapshot_id']] = source_span_index(graph)
        versions[version_id] = version
        partial |= graph['extraction_status'] == 'partial'
        recovered |= graph['extraction_status'] == 'recovered_proposed'
        occurrence_prefix = occurrence_id(version_id, '')
        label_prefix = version_id + '::'
        normalization = normalized.get((version_id, version['snapshot_id']))
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
                if normalization and node['source']['path'] == 'main.tex':
                    node['source']['source_kind'] = 'normalized'
                else:
                    node['source']['archive_uri'] = archive_prefix + quote(node['source']['path'])
            node['labels'] = [label_prefix + label for label in node['labels']]
            if node['kind'] == 'citation_key':
                node['data']['candidate_ids'] = [occurrence_prefix + item
                                                 for item in node['data'].get('candidate_ids', [])]
            # Full original IDs are also version-qualified to disambiguate revisions.
            for label in node['labels'] + [label_prefix + original_id]:
                labels.setdefault(label, []).append(node['id'])
            nodes.append(node)
        for edge in graph['edges']:
            edge['id'] = occurrence_prefix + edge['id']
            edge['source'] = occurrence_prefix + edge['source']
            edge['target'] = occurrence_prefix + edge['target']
            edges.append(edge)
    edges.extend(bibliography_edges(nodes, edges, versions))
    graph = {'schema': 'qecgraph.workspace_graph', 'snapshot_id': fixed,
             'project_source_hash': hash_text(canonical(versions)), 'nodes': nodes, 'edges': edges,
             'labels': labels, 'diagnostics': [],
             'extraction_status': ('partial' if partial else
                                   'recovered_proposed' if recovered else 'complete_for_supported_syntax')}
    return GraphInput(graph)
