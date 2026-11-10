"""Measure this implementation and replay backup/recovery on generated inputs.

This is a bounded synthetic workload, not an upstream CodeGraph performance
claim or a benchmark on real QEC papers. Every invocation uses a fresh run dir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sqlite3
import statistics
import sys
import time
import uuid
from importlib.metadata import version
from pathlib import Path

from qecgraph.core.graph import read_json
from qecgraph.query import context, search
from qecgraph.store import SnapshotReference, current_snapshot, ingest, recover_store, validate_snapshot
from qecgraph.core.transactions import atomic_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='build/reproduce-incremental')
    parser.add_argument('--files', type=int, default=12)
    parser.add_argument('--lemmas-per-file', type=int, default=8)
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args(argv)
    if not 1 <= args.files <= 100 or not 1 <= args.lemmas_per_file <= 100 or not 1 <= args.runs <= 10:
        parser.error('files/lemmas must be 1..100; runs must be 1..10')
    out = Path(args.out).resolve()
    marker = out / '.qecgraph-incremental-reproduce.json'
    if out.exists() and any(out.iterdir()) and not marker.exists():
        parser.error('--out must be empty or managed by this script')
    if marker.exists() and read_json(marker) != {'format': 'qecgraph.incremental-reproduce'}:
        parser.error('Incompatible output marker')
    atomic_json(marker, {'format': 'qecgraph.incremental-reproduce'})
    run = out / ('run-' + str(uuid.uuid4()))
    paper = run / 'input'
    paper.mkdir(parents=True)
    entry = paper / 'main.tex'
    entry.write_text('\\newtheorem{lemma}{Lemma}\n' + ''.join(f'\\input{{part-{i:03}}}\n' for i in range(args.files))
                     + '\\includegraphics{figure.svg}\n', encoding='utf-8')
    for i in range(args.files):
        text = '\n'.join(f'\\begin{{lemma}}\\label{{lemma:{i}:{j}}}Generated bounded input {i}, item {j}, value A.\\end{{lemma}}'
                         for j in range(args.lemmas_per_file))
        (paper / f'part-{i:03}.tex').write_text(text, encoding='utf-8')
    asset = paper / 'figure.svg'
    asset.write_text('<svg>asset-A</svg>', encoding='utf-8')
    full, incremental = run / 'full', run / 'incremental'
    report = {'format': 'qecgraph.incremental-reproduction', 'status': 'running',
              'command': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'runtime': {'python': platform.python_version(), 'platform': platform.platform(),
                          'sqlite': sqlite3.sqlite_version, 'pylatexenc': version('pylatexenc'), 'jsonschema': version('jsonschema')},
              'workload': {'generated_source_files': args.files + 1, 'lemmas_per_file': args.lemmas_per_file,
                           'lemma_count': args.files * args.lemmas_per_file, 'runs_per_scenario': args.runs,
                           'scope': 'generated fixtures, not user papers or mathematical validation'},
              'measurements': [], 'recovery': {}, 'not_executed': ['Docker', 'Lean']}

    def pair(scenario, iteration):
        order = ['full', 'incremental'] if len(report['measurements']) % 2 == 0 else ['incremental', 'full']
        outputs, timings = {}, {}
        for mode in order:
            started = time.perf_counter()
            outputs[mode] = ingest(entry, 'incremental-reproduction', full if mode == 'full' else incremental,
                                   incremental=mode == 'incremental')
            timings[mode] = time.perf_counter() - started
        ordinary, cached = outputs['full'], outputs['incremental']
        full_seconds, incremental_seconds = timings['full'], timings['incremental']
        if ordinary['snapshot_id'] != cached['snapshot_id']:
            raise RuntimeError('Full/incremental snapshot identity mismatch')
        left, right = Path(ordinary['snapshot']), Path(cached['snapshot'])
        for filename in ('graph.json', 'sourcegraph.json', 'lemmagraph.json', 'datagraph.json'):
            if read_json(left / filename) != read_json(right / filename):
                raise RuntimeError('Full/incremental projection mismatch: ' + filename)
        a, b = SnapshotReference(left, ordinary['snapshot_id']), SnapshotReference(right, cached['snapshot_id'])
        if context(a, 'lemma:0:0') != context(b, 'lemma:0:0') or search(a, 'bounded') != search(b, 'bounded'):
            raise RuntimeError('Full/incremental query mismatch')
        report['measurements'].append({'scenario': scenario, 'iteration': iteration, 'snapshot_id': cached['snapshot_id'],
                                       'execution_order': order,
                                       'full_seconds': full_seconds, 'incremental_seconds': incremental_seconds,
                                       'ast': cached['incremental'], 'semantic_equality': True})
        return cached

    try:
        result = pair('cold', 0)
        for i in range(args.runs):
            result = pair('unchanged', i)
        leaf = paper / 'part-000.tex'
        for i in range(args.runs):
            leaf.write_text(leaf.read_text(encoding='utf-8').replace(f'value {"A" if i == 0 else str(i - 1)}.', f'value {i}.'), encoding='utf-8')
            result = pair('leaf_edit', i)
        for i in range(args.runs):
            asset.write_text(f'<svg>asset-{i}</svg>', encoding='utf-8')
            result = pair('asset_edit', i)
        expected_id = result['snapshot_id']
        backup_input = run / 'backup-input'
        backup_store = run / 'restored-store'
        started = time.perf_counter()
        shutil.copytree(paper, backup_input)
        shutil.copytree(incremental, backup_store)
        paper.rename(run / 'original-input-moved')
        report['recovery']['archive_without_original_paths'] = validate_snapshot(current_snapshot(backup_store))
        if context(backup_store, 'lemma:0:0')['snapshot_id'] != expected_id:
            raise RuntimeError('Restored query changed snapshot')
        rebuilt = ingest(backup_input / 'main.tex', 'incremental-reproduction', run / 'rebuilt-store')
        if rebuilt['snapshot_id'] != expected_id:
            raise RuntimeError('Backup input replay changed snapshot')
        report['recovery']['rebuild_snapshot_id'] = rebuilt['snapshot_id']
        abandoned = backup_store / 'snapshots/.building-recovery-demo'
        abandoned.mkdir()
        atomic_json(abandoned / '.qecgraph-building.json', {'format': 'qecgraph.building', 'snapshot_id': '0' * 64})
        report['recovery']['abandoned_cleanup'] = recover_store(backup_store, remove_abandoned=True)
        if abandoned.exists():
            raise RuntimeError('Owned abandoned build was not cleaned')
        # The same restored input version can fail/stage and recover without
        # changing the published snapshot to partial under strict policy.
        missing = backup_input / 'part-000.tex'
        raw = missing.read_bytes()
        missing.unlink()
        partial = ingest(backup_input / 'main.tex', 'incremental-reproduction', backup_store, strict=True, incremental=True)
        if partial['published'] or current_snapshot(backup_store).name != expected_id:
            raise RuntimeError('Strict partial overwrote the restored CURRENT')
        missing.write_bytes(raw)
        recovered = ingest(backup_input / 'main.tex', 'incremental-reproduction', backup_store, strict=True, incremental=True)
        if recovered['snapshot_id'] != expected_id or not recovered['published']:
            raise RuntimeError('Restored include did not recover the same published snapshot')
        report['recovery']['strict_partial_snapshot_id'] = partial['snapshot_id']
        report['recovery']['restored_include_snapshot_id'] = recovered['snapshot_id']
        corrupted = run / 'tampered-store'
        shutil.copytree(backup_store, corrupted)
        snapshot = current_snapshot(corrupted)
        graph = read_json(snapshot / 'graph.json')
        fragment = next(node['fragment_path'] for node in graph['nodes'] if node.get('fragment_path'))
        (snapshot / fragment).write_bytes((snapshot / fragment).read_bytes() + b'changed')
        try:
            validate_snapshot(snapshot)
        except ValueError as exc:
            report['recovery']['tamper_detection'] = {'passed': True, 'observed_error': str(exc)}
        else:
            raise RuntimeError('Tampered fragment was not detected')
        report['recovery']['elapsed_seconds'] = time.perf_counter() - started
        summary = {}
        for scenario in ('cold', 'unchanged', 'leaf_edit', 'asset_edit'):
            samples = [item for item in report['measurements'] if item['scenario'] == scenario]
            full_time = statistics.median(item['full_seconds'] for item in samples)
            cached_time = statistics.median(item['incremental_seconds'] for item in samples)
            summary[scenario] = {'median_full_seconds': full_time, 'median_incremental_seconds': cached_time,
                                 'full_over_incremental_ratio': full_time / cached_time,
                                 'sample_count': len(samples)}
        report['performance'] = summary
        report['performance_note'] = 'Actual local samples only; full semantic/SQLite rebuilding and cache I/O may dominate. No guaranteed speedup.'
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = str(exc)
    report['input_manifest'] = {str(path.relative_to(run)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in sorted((run / 'backup-input').rglob('*')) if path.is_file()}
    atomic_json(run / 'results.json', report)
    atomic_json(out / 'LATEST.json', {'path': str((run / 'results.json').relative_to(out))})
    print(json.dumps({'status': report['status'], 'report': str(run / 'results.json'),
                      'performance': report.get('performance'), 'error': report.get('error')}, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
