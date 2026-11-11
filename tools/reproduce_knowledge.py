#!/usr/bin/env python3
"""Record direct-reading, search-reading and task-context evidence packs (no LLM)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
from statistics import median
import tempfile
from time import perf_counter

from qecgraph import __version__
from qecgraph.core.graph import canonical, hash_text, read_json
from qecgraph.core.transactions import atomic_json
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession


def fixture(root):
    workspace = Workspace(root)
    workspace.prepare()
    config = root / 'qecgraph.toml'
    config.write_text(config.read_text().replace('enabled = false', 'enabled = true', 1).replace(
        '[ai]\nenabled = true', '[ai]\nenabled = false'))
    for name in ('memory', 'decoder', 'circuit'):
        text = (r'\documentclass{article}' + '\n' + r'\begin{document}' + '\n' +
                r'\section{Example}' + '\n' +
                r'\begin{definition}' + f'A {name} object obeys fixture convention H.' + r'\end{definition}' + '\n' +
                r'\begin{lemma}' + f'The {name} result requires hypothesis H.' + r'\end{lemma}' + '\n' +
                r'\begin{proof}The fixture argument uses H.\end{proof}' + '\n' + r'\end{document}')
        (root / 'inputs' / (name + '.tex')).write_text(text)
    workspace.sync()
    session = WorkspaceSession(root / 'machine', profile='research', max_chars=1000000)
    cases = []
    for node in session._source_nodes.values():
        if node['kind'] != 'lemma':
            continue
        name = next(n for n in ('memory', 'decoder', 'circuit') if n in node['latex'])
        cases.append({'name': name, 'query': f'{name} result', 'kind': 'lemma', 'purpose': 'theorem',
                      'source_version_id': node['source']['source_version_id'], 'identifier': node['id'],
                      'expected_evidence': [f'The {name} result requires hypothesis H.',
                                            f'A {name} object obeys fixture convention H.']})
    return session, cases


def sample_cases(session):
    """Discover source-bound mechanical probes, not a curated scientific QA set."""
    cases = []
    for version in session.state['versions']:
        nodes = [n for n in session._source_nodes.values() if n['source']['source_version_id'] == version]
        preferred = [n for n in nodes if n['kind'] in {'theorem', 'lemma', 'definition'}]
        for node in (preferred or nodes)[:2]:
            cases.append({'name': node['id'], 'identifier': node['id'], 'source_version_id': version,
                          'query': node['latex'][:180], 'kind': node['kind'], 'purpose': 'theorem',
                          'expected_evidence': [node['latex'][:180]]})
    return cases


def evaluate(session, cases, *, include_payloads=False):
    measurements = []
    all_calls = []
    for case in cases:
        outcomes = {}
        for baseline in ('A_direct', 'B_search_read', 'C_search_context'):
            calls, evidence_text, errors = [], [], []
            missing_components = None

            def call(tool, arguments):
                start = perf_counter()
                response = session.invoke(tool, arguments)
                elapsed = perf_counter() - start
                raw = canonical(response)
                calls.append({'tool': tool, 'arguments': arguments, 'seconds': elapsed,
                              'returned_chars': len(raw), 'response_sha256': hash_text(raw), 'ok': response['ok'],
                              **({'response': response} if include_payloads else {})})
                all_calls.append(calls[-1])
                if not response['ok']:
                    errors.append(response['error']['code'])
                    return None
                # Evidence quality counts only actual text/records, never query metadata.
                return response['data']

            if baseline == 'A_direct':
                data = call('qec_fetch', {'identifier': case['source_version_id'], 'view': 'raw'})
                if data:
                    evidence_text.extend(f['text'] for f in data.get('files', []))
            else:
                data = call('qec_search', {'query': case['query'], 'kind': case['kind'],
                                         'source_version_id': case['source_version_id'], 'limit': 5,
                                         'mode': 'keyword' if baseline.startswith('B_') else 'hybrid'})
                if data and data['results']:
                    identifier = data['results'][0]['id']
                    if baseline.startswith('B_'):
                        result = call('qec_fetch', {'identifier': identifier})
                        if result:
                            evidence_text.append(result.get('text', canonical(result.get('entity', {}))))
                    else:
                        result = call('qec_get_context', {'identifier': identifier, 'purpose': case['purpose']})
                        if result:
                            evidence_text.extend(n.get('latex') or canonical(n.get('data', {})) for n in result['nodes'])
                            missing_components = result['missing_components']
                elif data:
                    errors.append('NO_CANDIDATES')
            joined = '\n'.join(evidence_text)
            expected = case.get('expected_evidence', [])
            found = [text in joined for text in expected]
            outcomes[baseline] = {'calls': calls, 'call_count': len(calls),
                                  'returned_chars': sum(c['returned_chars'] for c in calls),
                                  'seconds': sum(c['seconds'] for c in calls), 'errors': errors,
                                  'context_missing_components': missing_components,
                                  'expected_passages': len(expected), 'found_passages': sum(found),
                                  'passage_recall': sum(found)/len(found) if found else None}
        measurements.append({'case': case, 'baselines': outcomes})
    times = sorted(c['seconds'] for c in all_calls)
    return {'format': 'qecgraph.knowledge-evaluation.v1', 'package_version': __version__,
            'python': platform.python_version(), 'scope': session.scope,
            'cases_sha256': hash_text(canonical(cases)), 'cases': measurements,
            'coverage': session.knowledge.coverage(), 'query_count': len(times),
            'p50_seconds': median(times) if times else None,
            'p95_seconds': times[max(0, (95*len(times)+99)//100-1)] if times else None,
            'tool_errors': sum(not c['ok'] for c in all_calls),
            'baseline_errors': sum(len(b['errors']) for m in measurements for b in m['baselines'].values()),
            'model_execution': None,
            'interpretation': 'Evidence-pack mechanics only. No model answer accuracy, mathematical correctness or production capacity claim.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='Local JSON measurement report')
    parser.add_argument('--machine', type=Path, help='Optional existing read-only machine release; otherwise use synthetic papers')
    parser.add_argument('--release', help='Pin an existing machine release')
    parser.add_argument('--cases', type=Path, help='Optional JSON task list for the selected release')
    parser.add_argument('--include-payloads', action='store_true', help='Save exact source/tool responses in the local report')
    args = parser.parse_args()
    if args.release and not args.machine or args.cases and not args.machine:
        parser.error('--release and --cases require --machine')
    with tempfile.TemporaryDirectory(prefix='qec-knowledge-eval-') as directory:
        if args.machine:
            session = WorkspaceSession(args.machine, args.release, profile='research', max_chars=1000000)
            cases = read_json(args.cases) if args.cases else sample_cases(session)
        else:
            session, cases = fixture(Path(directory))
        if not isinstance(cases, list) or not cases:
            parser.error('A nonempty case list is required')
        report = evaluate(session, cases, include_payloads=args.include_payloads)
        report['dataset'] = 'selected registered source probes' if args.machine else 'synthetic offline fixtures'
    atomic_json(args.out, report)
    print(json.dumps({'report': str(args.out.resolve()), 'cases': len(cases), 'tool_errors': report['tool_errors'],
                      'dataset': report['dataset']}, ensure_ascii=False))
    return 1 if report['baseline_errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
