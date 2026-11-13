"""Measure retrieval on explicit source locators; never grade scientific answers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter

from qecgraph.core.graph import canonical, hash_text, read_json
from qecgraph.core.transactions import atomic_json
from qecgraph.workspace_query import WorkspaceSession


def overlaps(source, expected):
    return bool(source and all(source.get(k) == expected[k] for k in
                               ('source_version_id', 'path', 'file_sha256'))
                and min(source['char_end'], expected['char_end']) > max(source['char_start'], expected['char_start']))


def evaluate(session, dataset):
    if not isinstance(dataset.get('cases'), list) or not dataset['cases']:
        raise ValueError('A nonempty explicit case list is required')
    measurements = []
    for case in dataset['cases']:
        expected = case['expected_sources']
        if not expected:
            raise ValueError('Each case needs at least one source locator')
        for span in expected:
            file = session.knowledge.files[(span['source_version_id'], span['path'])]
            text = session.knowledge.file_text(file)
            if file['data']['sha256'] != span['file_sha256'] or not 0 <= span['char_start'] < span['char_end'] <= len(text):
                raise ValueError('Expected evidence is not bound to this source release')
        outcomes = {}
        for mode in ('literal', 'keyword'):
            args = {'query': case['query'], 'mode': mode, 'include_proposals': False, 'include_ai_extracted': False}
            start = perf_counter()
            response = session.invoke('qec_search', {**args, 'limit': 10, 'detail': 'full'})
            elapsed = perf_counter() - start
            rows = response.get('data', {}).get('results', [])
            ranks = [next((i for i, row in enumerate(rows, 1) if overlaps(row.get('source'), span)), None)
                     for span in expected]
            first = min((rank for rank in ranks if rank is not None), default=None)
            compact = session.invoke('qec_search', {**args, 'limit': 5})
            outcomes[mode] = {'recall_at_5': sum(rank is not None and rank <= 5 for rank in ranks) / len(expected),
                              'recall_at_10': sum(rank is not None for rank in ranks) / len(expected),
                              'reciprocal_rank_at_10': 0 if first is None else 1 / first,
                              'result_count': len(rows), 'seconds': elapsed,
                              'concise_5_chars': len(canonical(compact)), 'ok': response['ok'] and compact['ok'],
                              'evidence_ranks': ranks,
                              'returned_ids': [row['id'] for row in rows],
                              'error': response.get('error') or compact.get('error')}
        measurements.append({'id': case['id'], 'question': case['question'], 'query': case['query'], 'modes': outcomes})
    summary = {}
    for mode in ('literal', 'keyword'):
        rows = [case['modes'][mode] for case in measurements]
        summary[mode] = {metric: mean(row[metric] for row in rows) for metric in
                         ('recall_at_5', 'recall_at_10', 'reciprocal_rank_at_10')}
        summary[mode].update(median_concise_5_chars=median(row['concise_5_chars'] for row in rows),
                             median_seconds=median(row['seconds'] for row in rows), failures=sum(not row['ok'] for row in rows))
    return {'format': 'qecgraph.retrieval-evaluation.v1', 'scope': session.scope,
            'dataset_sha256': hash_text(canonical(dataset)), 'label_status': dataset['label_status'],
            'comparison': 'Literal versus BM25 on the same current implementation, release and eligible units; not an old-code replay',
            'interpretation': 'Source-block discovery only, excluding AI proposals. Labels are engineering smoke, not blinded scientific gold. No model calls.',
            'summary': summary, 'cases': measurements}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--machine', type=Path, required=True, help='Read-only machine copy; never read human or workspace config')
    parser.add_argument('--release', help='Fixed release, default CURRENT')
    parser.add_argument('--cases', type=Path, required=True, help='Explicit source-bound JSON questions')
    parser.add_argument('--out', type=Path, required=True, help='Local measurement report')
    args = parser.parse_args()
    session = WorkspaceSession(args.machine, args.release, profile='research', max_chars=1000000)
    report = evaluate(session, read_json(args.cases))
    atomic_json(args.out, report)
    print(json.dumps({'report': str(args.out.resolve()), 'summary': report['summary']}, indent=2))
    return int(any(row['failures'] for row in report['summary'].values()))


if __name__ == '__main__':
    raise SystemExit(main())
