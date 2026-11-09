#!/usr/bin/env python3
"""Replay the pinned arXiv fixtures without changing the source archives."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from qecgraph.workspace import Workspace


MANIFEST = Path(__file__).resolve().parents[1] / 'tests/golden/arxiv_sources.json'


def stage_archives(directory, inbox, cases):
    for case in cases:
        digest, paper = case['archive_sha256'], case['arxiv']
        source = directory / digest
        if not source.exists():
            source = directory / f'{paper}.source'
        if not source.is_file() or source.is_symlink():
            raise ValueError(f'Missing regular source archive for arXiv:{paper}: {source}')
        with source.open('rb') as stream:
            raw = stream.read((32 << 20) + 1)
        if len(raw) > 32 << 20:
            raise ValueError(f'Source archive exceeds 32 MiB: arXiv:{paper}')
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f'Archive checksum differs for arXiv:{paper}')
        (inbox / f'{paper}.source').write_bytes(raw)


def _expected(actual, expected, name):
    if actual != expected:
        raise ValueError(f'{name}: expected {expected!r}, received {actual!r}')


def _check_graph(graph, case):
    _expected(graph['extraction_status'], 'complete_for_supported_syntax', 'extraction status')
    files = sorted(node['data']['path'] for node in graph['nodes'] if node['kind'] == 'source_file')
    _expected(files, case['source_files'], 'source files')
    nodes = {node['id']: node for node in graph['nodes']}
    selected = {}
    for label, kind in case['labels'].items():
        matches = graph['labels'].get(label, [])
        _expected(len(matches), 1, f'label count for {label}')
        node = nodes[matches[0]]
        _expected(node['kind'], kind, f'kind for {label}')
        selected[label] = node
    for label in case.get('reference_only_labels', []):
        relations = {edge['relation'] for edge in graph['edges'] if edge['target'] == selected[label]['id']}
        _expected(relations & {'references', 'depends_on_candidate', 'depends_on_declared', 'depends_on_reviewed'},
                  {'references'}, f'citation boundary for {label}')
    if supplement := case.get('supplement_label'):
        _expected(selected[supplement['label']]['source']['path'], supplement['source'], 'supplement source path')


def configure_entrypoints(root, cases):
    overrides = [case for case in cases if case.get('requires_entrypoint_override')]
    if not overrides:
        return
    with (root / 'qecgraph.toml').open('a', encoding='utf-8') as config:
        config.write('\n[entrypoints]\n')
        for case in overrides:
            config.write(f'{case["source_tree_sha256"]} = {json.dumps(case["entrypoint"])}\n')


def verify(directory, root):
    cases = json.loads(MANIFEST.read_text(encoding='utf-8'))
    workspace = Workspace(root)
    workspace.init(no_ingest=True)
    inbox = root / 'inputs'
    stage_archives(directory, inbox, cases)
    sync = workspace.sync()
    overrides = [case for case in cases if case.get('requires_entrypoint_override')]
    statuses = {row['input']: row['status'] for row in sync['inputs']}
    for case in cases:
        paper = case['arxiv']
        expected = 'needs_entrypoint' if case in overrides else 'processing_completed'
        _expected(statuses.get(f'{paper}.source'), expected, f'initial import of arXiv:{paper}')
        if case in overrides:
            _expected((inbox / f'{paper}.source').is_file(), True, f'ambiguous input retained for arXiv:{paper}')
    if overrides:
        configure_entrypoints(root, overrides)
        sync = workspace.sync()
    _expected(sync['counts']['processed'], len(cases), 'processed archive count')
    _expected(len(list(inbox.glob('*.source'))), 0, 'unconsumed inbox copies')
    _expected(workspace.status()['pending_claims'], 0, 'unconsumed claims')
    validation = workspace.validate()
    if not validation['passed']:
        raise ValueError(f'Golden workspace failed validation: {validation["issues"]}')
    state, release = workspace.registry.read(sync['release_id'])
    results = []
    for case in cases:
        material = state['materials'][case['archive_sha256']]
        try:
            for field in ('entrypoint', 'format'):
                _expected(material[field], case[field], field)
            _expected(material['source_tree_hash'], case['source_tree_sha256'], 'source tree hash')
            graph, _, _ = workspace.registry.source_graph(material['source_version_id'], release)
            _check_graph(graph, case)
        except (KeyError, ValueError) as exc:
            raise ValueError(f'arXiv:{case["arxiv"]}: {exc}') from exc
        results.append({'arxiv': case['arxiv'], 'archive_sha256': case['archive_sha256'],
                        'entrypoint': case['entrypoint'],
                        'entrypoint_override': bool(case.get('requires_entrypoint_override')),
                        'labels_checked': sorted(case['labels']),
                        'nodes': len(graph['nodes']), 'edges': len(graph['edges'])})
    return {'passed': True, 'release_id': release, 'papers': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='qecgraph-golden-') as directory:
        report = verify(args.archive_dir.resolve(), Path(directory))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'{len(report["papers"])} arXiv sources passed. Report: {args.out}')


if __name__ == '__main__':
    main()
