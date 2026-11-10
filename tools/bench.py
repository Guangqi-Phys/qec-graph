#!/usr/bin/env python3
"""Measure local graph ingestion and queries with fixed inputs."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sqlite3
from statistics import median
import subprocess
import sys
import tempfile
from time import perf_counter

from qecgraph import __version__
from qecgraph.corpus import occurrence_id
from qecgraph.core.transactions import atomic_json
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession

from reproduce_golden import MANIFEST, configure_entrypoints, stage_archives


ROOT = Path(__file__).resolve().parents[1]
SEARCH = {'query': 'thm:main', 'kind': 'theorem', 'limit': 10}
CONTEXT = {'depth': 1, 'max_nodes': 8}


def _samples(values):
    return {'seconds': values, 'median_seconds': median(values),
            'min_seconds': min(values), 'max_seconds': max(values)}


def _synthetic(root, runs):
    out = root / 'synthetic'
    command = [sys.executable, str(ROOT / 'tools/reproduce_incremental.py'),
               '--files', '12', '--lemmas-per-file', '8', '--runs', str(runs), '--out', str(out)]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
    latest = json.loads((out / 'LATEST.json').read_text(encoding='utf-8'))['path']
    result = json.loads((out / latest).read_text(encoding='utf-8'))
    grouped = defaultdict(list)
    for sample in result['measurements']:
        for mode in ('full', 'incremental'):
            grouped[f'{sample["scenario"]}_{mode}'].append(sample[f'{mode}_seconds'])
    return {'workload': result['workload'], 'paired_projection_equality': result['status'] == 'passed',
            'timings': {key: _samples(samples) for key, samples in grouped.items()}}


def _measure(timings, name, operation):
    start = perf_counter()
    value = operation()
    timings[name].append(perf_counter() - start)
    return value


def _query(session, tool, arguments):
    response = session.invoke(tool, arguments)
    if not response['ok']:
        raise RuntimeError(f'{tool} failed: {response["error"]}')
    return response['data']


def _real_run(root, archive_dir, cases, timings):
    workspace = Workspace(root)
    workspace.init(no_ingest=True)
    configure_entrypoints(root, cases)
    stage_archives(archive_dir, root / 'inputs', cases)
    publication = _measure(timings, 'fresh_workspace_sync', workspace.sync)
    if publication['counts']['processed'] != len(cases):
        raise RuntimeError('The benchmark did not publish the whole pinned corpus')
    release = publication['release_id']
    validation = _measure(timings, 'validate_release', workspace.validate)
    if not validation['passed']:
        raise RuntimeError('Benchmark publication did not pass validation')
    state, _ = workspace.registry.read(release)
    homological = next(case for case in cases if case['arxiv'] == '1311.0885v1')
    version_id = state['materials'][homological['archive_sha256']]['source_version_id']
    graph, _, _ = workspace.registry.source_graph(version_id, release)
    identifier = occurrence_id(version_id, graph['labels']['thm:main'][0])
    session = _measure(timings, 'open_fixed_session', lambda: WorkspaceSession(workspace.registry.root, release))
    search = _measure(timings, 'fixed_search', lambda: _query(session, 'qecgraph_search', SEARCH))
    context = _measure(timings, 'fixed_context', lambda: _query(
        session, 'qec_get_context', {'identifier': identifier, **CONTEXT}))
    if not search['results'] or context['root_id'] != identifier:
        raise RuntimeError('Benchmark queries did not find the expected graph records')
    return {'search_results': len(search['results']), 'context_nodes': len(context['nodes'])}


def _real(root, archive_dir, runs):
    manifest = MANIFEST.read_bytes()
    cases = json.loads(manifest)
    timings = defaultdict(list)
    outcomes = [_real_run(root / f'workspace-{run}', archive_dir, cases, timings) for run in range(runs)]
    if any(result != outcomes[0] for result in outcomes):
        raise RuntimeError('The benchmark query workload changed between repetitions')
    return {'arxiv_versions': [case['arxiv'] for case in cases],
            'manifest_sha256': hashlib.sha256(manifest).hexdigest(), 'query_result_counts': outcomes[0],
            'query_arguments': {'search': SEARCH, 'context': {**CONTEXT, 'label': '1311.0885v1::thm:main'}},
            'timings': {key: _samples(samples) for key, samples in timings.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--archive-dir', type=Path, help='Optional directory for the six pinned arXiv archives')
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error('--runs must be 1..10')
    with tempfile.TemporaryDirectory(prefix='qecgraph-bench-') as directory:
        root = Path(directory)
        report = {
            'format': 'qecgraph.benchmark.v1',
            'runtime': {'qecgraph': __version__, 'python': platform.python_version(),
                        'platform': platform.platform(), 'sqlite': sqlite3.sqlite_version,
                        'pylatexenc': version('pylatexenc'), 'jsonschema': version('jsonschema')},
            'runs': args.runs,
            'scope': 'Local elapsed times with fresh application state and ordinary OS caches.',
            'synthetic_incremental': _synthetic(root, args.runs),
            'arxiv_workspace': _real(root, args.archive_dir.resolve(), args.runs) if args.archive_dir else None,
        }
    atomic_json(args.out, report)
    print(f'Benchmark report: {args.out}')


if __name__ == '__main__':
    main()
