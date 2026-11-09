"""Conservative, offline research proposals from exact TeX source spans."""
from __future__ import annotations

import re

from .graph import canonical, hash_text
from .research import make_record, ref

RULE_VERSION = 'code-mention-rules-v1'
NOTATION = re.compile(r'\[\[\s*(\d{1,8})\s*,\s*(\d{1,8})\s*,\s*(\d{1,8})\s*\]\]')
QUANTUM_CONTEXT = re.compile(r'\b(?:CSS|quantum|stabili[sz]er)\s+code\b', re.I)
CLASSICAL_CONTEXT = re.compile(r'\bclassical\b', re.I)
FRAGMENTS = {'paragraph', 'definition', 'lemma', 'theorem', 'proposition', 'corollary', 'remark'}


def proposals(graph, version):
    """Pass 1 locates mentions; pass 2 binds only values supported in the same clause."""
    source_id, snapshot = version['id'], version['snapshot_id']
    origin = {'id': source_id, 'revision': snapshot}
    source = make_record('paper_version', source_id, snapshot,
                         {'work_id': version['work_id'], 'upstream_version': version['upstream_version'],
                          'source_snapshot_id': snapshot}, source=origin, method='workspace_source_registry')
    candidates = {}
    for node in graph['nodes']:
        span = node.get('source')
        if node['kind'] not in FRAGMENTS or not span or node['origin'] != 'parser':
            continue
        for match in NOTATION.finditer(node['latex']):
            start = span['char_start'] + match.start()
            location = (span['path'], start, start + len(match[0]))
            previous = candidates.get(location)
            if previous is None or len(node['latex']) < len(previous[0]['latex']):
                candidates[location] = (node, match)
    records = [source]
    for (path, start, end), (node, match) in sorted(candidates.items()):
        body = node['latex']
        line_start = body.rfind('\n', 0, match.start()) + 1
        line_end = body.find('\n', match.end())
        context = body[line_start:line_end if line_end != -1 else len(body)]
        explicit_quantum = bool(QUANTUM_CONTEXT.search(context) and not CLASSICAL_CONTEXT.search(context)
                                and len(list(NOTATION.finditer(context))) == 1)
        # Notation alone does not assign dimensions, establish a bound, or establish object identity.
        data = {'source_ref': origin, 'code_ref': None, 'reported_notation': match[0],
                'coding_domain': 'quantum' if explicit_quantum else None,
                'n_data': int(match[1]) if explicit_quantum else None,
                'k_logical': int(match[2]) if explicit_quantum else None,
                'distance_interpretation': None, 'review_status': 'proposed'}
        if data['n_data'] is not None and (data['n_data'] < 1 or data['k_logical'] > data['n_data']):
            data.update(n_data=None, k_logical=None)
        locator = {'source_version_id': source_id, 'snapshot_id': snapshot, 'node_id': node['id'],
                   'node_content_sha256': node['content_sha256'], 'path': path, 'char_start': start, 'char_end': end}
        evidence = {f'/data/{field}': {'status': 'known', 'source_ref': origin, 'source_locator': locator,
                                      'method': RULE_VERSION}
                    for field in ('reported_notation', 'coding_domain', 'n_data', 'k_logical')
                    if data[field] is not None}
        identifier = 'mention:' + hash_text(canonical([source_id, path, start, end]))
        revision = hash_text(canonical([snapshot, RULE_VERSION, data, locator]))
        records.append(make_record('code_mention', identifier, revision, data, source=origin,
                                   method=RULE_VERSION, evidence=evidence))
    return records
