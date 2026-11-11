#!/usr/bin/env python3
"""Verify the installed RFC-002 CLI in a new directory outside the source tree."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

TEX = b'\\documentclass{article}\n\\begin{document}\nA CSS code has $[[13,1,3]]$.\n\\end{document}\n'
SUBSYSTEM_SHA = '103a027e1258298afbc5de782625eb3a30efd86c68c981adfc2b0b96821ce52f'


def verify(binary, workspace, real_source=None, legacy_binary=None):
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    env.pop('QECGRAPH_WORKSPACE', None)
    # This acceptance run checks local imports, including defaults without a key.
    for name in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY'):
        env.pop(name, None)
    env['NO_COLOR'] = '1'
    checks = []

    def run(label, args, expected=0, stdin=None, json_output=True, executable=None):
        result = subprocess.run([str(executable or binary), *args], cwd=workspace, env=env, input=stdin,
                                capture_output=True, text=True, timeout=120, check=False)
        if result.returncode != expected:
            raise AssertionError(f'{label} returned {result.returncode}: {result.stderr[:1000]}')
        checks.append({'step': label, 'argv': args, 'exit_code': result.returncode})
        if json_output:
            return json.loads(result.stdout)
        return result.stdout

    product, package_version = run('version', ['--version'], json_output=False).strip().split(maxsplit=1)
    assert product == 'qec-graph'
    inbox = workspace / 'inputs'
    inbox.mkdir()
    (inbox / 'format-is-not-an-extension.dat').write_bytes(gzip.compress(TEX, mtime=1))
    if real_source:
        raw = real_source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != SUBSYSTEM_SHA:
            raise ValueError('Real regression expects the recorded Subsystem Codes v1 archive bytes')
        (inbox / 'subsystem-v1.source').write_bytes(raw)
    prepared = run('init', ['init', '--json'])
    assert prepared['status'] == 'initialized'
    ai = run('ai_policy_defaults', ['ai', 'status', '--json'])
    assert ai['structure_fallback'] and ai['extract_proposals']
    assert ai['provider'] == 'openrouter' and ai['model'] == 'deepseek/deepseek-v4.1-flash-1017'
    assert not ai['configured']
    first = run('init_sync', ['sync', '--json'])
    assert first['status'] == 'published'
    assert first['counts']['registered'] == (2 if real_source else 1)
    assert first['human']['status'] == 'current'
    assert all(item['input_consumed'] for item in first['inputs'])
    if real_source:
        actual = next(item for item in first['inputs'] if item['archive_sha256'] == SUBSYSTEM_SHA)
        assert actual['entrypoint'] == 'subsys.tex' and actual['upstream_version'] is None
        assert actual['semantic_status'] == 'semantic_pending'
    note = workspace / 'private-validation-note.md'
    note.write_text('RFC002-PERSONAL-CANARY-9212', encoding='utf-8')
    (inbox / 'same-tree-new-compression').write_bytes(gzip.compress(TEX, mtime=2))
    second = run('sync', ['sync', '--json'])
    assert second['inputs'][0]['input_consumed']
    assert second['inputs'][0]['source_tree_hash'] == next(
        x['source_tree_hash'] for x in first['inputs'] if x['input'].startswith('format-'))
    assert len(list((workspace / 'archive/receipts').glob('*.json'))) == (3 if real_source else 2)
    run('import_catalogue', ['software', 'import-seed'])
    coverage = run('catalogue_coverage', ['software', 'coverage'])
    assert coverage['projects'] == 14 and not coverage['installation_or_benchmarks_verified']
    expected_release = coverage['release_id']
    rebuild = run('rebuild_from_archive', ['rebuild', '--json'])
    assert rebuild['release_id'] == expected_release and rebuild['status'] == 'unchanged'
    assert all(p.name.startswith('.') for p in inbox.iterdir())
    for action in ('sync', 'status', 'validate'):
        outcome = run(f'{action}_without_options', [action], json_output=False)
        assert len(outcome.splitlines()) == 1 and f'{action}: OK' in outcome
    status = run('status_json', ['status', '--json'])
    assert status['release_id'] == expected_release and status['status'] == 'ok'
    assert status['counts']['registered'] == status['counts']['processed'] == (3 if real_source else 2)
    assert status['human']['rendered_release_id'] == expected_release and status['human']['status'] == 'current'
    assert run('validate', ['validate', '--json'])['valid']
    review = run('review_list', ['review', 'list'])
    assert len(review['proposals']) >= (3 if real_source else 1)
    if real_source:
        golden = {'[[15,1,2,5]]': ('quantum', 'subsystem_log_dimensions', 15, 1, 2, None),
                  '[15,8,6]': ('classical', 'classical_seed_parameters', 15, None, None, 8),
                  '((n,K,R,d))': ('quantum', 'subsystem_dimensions', None, None, None, None)}
        for notation, expected in golden.items():
            assert any(row['data']['reported_notation'] == notation
                       and tuple(row['data'].get(field) for field in ('code_type', 'parameter_kind', 'n',
                                                                     'k', 'r', 'k_classical')) == expected
                       and row['data']['distance_interpretation'] is None for row in review['proposals']), notation
    search_args = {'query': 'CSS code', 'limit': 10}
    (workspace / 'args.json').write_text(json.dumps(search_args), encoding='utf-8')
    args = ['qecgraph_search', '--workspace', '.', '--arguments', 'args.json']
    cli = run('query_tool_search', ['query-tool', *args])
    assert cli['ok'] and cli['data']['results']
    direct = run('search', ['search', 'CSS code', '--workspace', '.', '--limit', '10'])
    assert direct == cli
    reading = run('reading_search', ['search', 'CSS code', '--workspace', '.', '--limit', '10',
                                    '--view', 'reading'])
    assert reading['data']['view'] == 'reading'
    assert any('CSS code' in row['reading_excerpt'] for row in reading['data']['results'])
    occurrence = next(r['id'] for r in cli['data']['results'] if r.get('source'))
    (workspace / 'source-args.json').write_text(json.dumps({'identifier': occurrence}), encoding='utf-8')
    span = run('get_exact_source', ['query-tool', 'qec_get_source', '--workspace', '.', '--arguments', 'source-args.json'])['data']
    protocol = '2025-06-18'
    frames = [
        {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': protocol, 'capabilities': {},
                                                    'clientInfo': {'name': 'qecgraph-release-client', 'version': '1'}}},
        {'method': 'notifications/initialized'},
        {'id': 2, 'method': 'tools/list'},
        {'id': 3, 'method': 'tools/call', 'params': {'name': 'qecgraph_search', 'arguments': search_args}},
        {'id': 4, 'method': 'tools/call', 'params': {'name': 'qecgraph_search',
                                                   'arguments': {'query': 'RFC002-PERSONAL-CANARY-9212'}}},
        {'id': 5, 'method': 'tools/call', 'params': {'name': 'qec_find_software', 'arguments': {'query': 'Stim'}}},
        {'id': 6, 'method': 'resources/list'},
        {'id': 7, 'method': 'resources/read', 'params': {'uri': span['resource_uri']}},
        {'id': 8, 'method': 'resources/read', 'params': {'uri': 'file:///human/notes/private-validation-note.md'}},
        {'id': 9, 'method': 'tools/call', 'params': {'name': 'qecgraph_search',
                                                   'arguments': {**search_args, 'view': 'reading'}}},
    ]
    stdio = run('mcp_stdio', ['mcp', 'serve', '--machine', 'machine', '--release', expected_release],
                stdin=''.join(json.dumps({'jsonrpc': '2.0', **frame}) + '\n' for frame in frames), json_output=False)
    replies = {r['id']: r.get('result', r.get('error')) for r in (json.loads(line) for line in stdio.splitlines())}
    assert replies[1]['protocolVersion'] == protocol
    assert len(replies[2]['tools']) >= 11
    assert replies[3]['structuredContent'] == cli
    assert replies[4]['structuredContent']['data']['results'] == []
    assert replies[5]['structuredContent']['data']['results']
    assert replies[6]['resources']
    content, = replies[7]['contents']
    assert content['text'] == span['latex'] and content['_meta']['content_sha256'] == span['content_sha256']
    assert replies[8]['code'] == -32002
    assert replies[9]['structuredContent'] == reading
    assert 'private-validation-note' not in stdio and 'RFC002-PERSONAL-CANARY-9212' not in stdio
    assert note.read_text(encoding='utf-8') == 'RFC002-PERSONAL-CANARY-9212'
    notes = list((workspace / 'human').rglob('*_thoughts.md'))
    assert len(notes) == (2 if real_source else 1)
    assert all(expected_release in page.read_text(encoding='utf-8') for page in notes)
    assert all(page.read_text(encoding='utf-8').startswith('---\ntags:') for page in notes)
    assert not (workspace / 'human/Index.md').exists()
    upgrade = None
    if legacy_binary:
        def legacy(label, args):
            return run('legacy_' + label, args, executable=legacy_binary)
        def put(name, value):
            (workspace / name).write_text(json.dumps(value), encoding='utf-8')
        (workspace / 'legacy.tex').write_bytes(TEX)
        legacy('ingest', ['ingest', 'legacy.tex', '--project-id', 'legacy-demo', '--out', 'legacy-store'])
        legacy('register', ['register', '--corpus', 'legacy-corpus', '--store', 'legacy-store',
                            '--work-id', 'work:legacy', '--source-version-id', 'source:legacy'])
        base = {'schema': 'qecgraph.record', 'id': 'claim:legacy', 'kind': 'claim',
                'title': 'Legacy claim', 'revision': 'original',
                'data': {'statement': 'Legacy draft wording', 'hypotheses': [], 'quantifiers': []}}
        put('legacy-claim.json', base)
        before = legacy('record', ['record-add', 'legacy-claim.json', '--corpus', 'legacy-corpus'])
        revised = {**base, 'revision': 'human-revision',
                   'data': {**base['data'], 'statement': 'Legacy human-reviewed wording'}}
        put('legacy-proposal.json', {'changes': [{'record': revised, 'expected_revision': base['revision'],
                                                'expected_content_sha256': before['record']['content_sha256']}],
                                     'rationale': 'Release upgrade fixture'})
        proposal = legacy('review', ['review', 'legacy-proposal.json', '--corpus', 'legacy-corpus',
                                     '--actor-id', 'fixture:ai', '--actor-kind', 'ai'])
        decision = legacy('decision', ['review-decide', proposal['id'], '--corpus', 'legacy-corpus',
                                       '--actor-id', 'fixture:human', '--actor-kind', 'human',
                                       '--decision', 'approve', '--rationale', 'Checked fixture wording',
                                       '--checked-scope', 'statement', '--checked-scope', 'hypotheses', '--checked-scope', 'dependencies'])
        applied = legacy('apply', ['apply', proposal['id'], '--review-id', decision['id'], '--corpus', 'legacy-corpus'])
        legacy_fixed = applied['receipt']['registry_revision']
        unchanged = (workspace / 'legacy-corpus/CURRENT.json').read_bytes()
        migrated = run('migrate_0_3_0', ['workspace-migrate', '--corpus', 'legacy-corpus', '--workspace', 'upgraded'])
        assert migrated['legacy_registry_revision'] == legacy_fixed
        migrated_fixed = migrated['release_id']
        rebuilt = run('rebuild_migrated_workspace', ['rebuild', '--workspace', 'upgraded', '--json'])
        assert rebuilt['release_id'] == migrated_fixed
        after = run('read_migrated_claim', ['show', 'claim:legacy', '--corpus', 'upgraded/machine'])
        assert after['node']['record']['review']['status'] == 'reviewed'
        assert after['node']['record']['revision'] == 'human-revision'
        old = run('read_preserved_history', ['show', 'claim:legacy', '--corpus', 'upgraded/machine',
                                             '--registry-revision', before['registry_revision']])
        assert old['node']['record']['data']['statement'] == 'Legacy draft wording'
        assert (workspace / 'legacy-corpus/CURRENT.json').read_bytes() == unchanged
        upgrade = {'from_version': '0.3.0', 'legacy_release': legacy_fixed, 'migrated_release': migrated_fixed,
                   'review_and_history_preserved': True, 'legacy_pointer_unchanged': True}
    return {'passed': True, 'platform': platform.platform(), 'package_version': package_version,
            'release_id': expected_release, 'protocol_version': protocol, 'checks': checks,
            'source_count': first['counts']['registered'], 'software_projects': coverage['projects'],
            'code_mention_proposals': len(review['proposals']),
            'real_source': ({'url': 'https://arxiv.org/src/quant-ph/0610153v1', 'sha256': SUBSYSTEM_SHA,
                             'entrypoint': 'subsys.tex', 'scope': 'structural and three notation golden checks, not mathematical verification'}
                            if real_source else None),
            'upgrade': upgrade, 'human_pages': rebuild['human']['generated_pages'], 'note_canary_preserved': True,
            'observed_at': datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bin-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--real-source', type=Path)
    parser.add_argument('--legacy-bin-dir', type=Path)
    args = parser.parse_args()
    binary = (args.bin_dir / 'qec-graph').resolve(strict=True)
    real_source = args.real_source.resolve(strict=True) if args.real_source else None
    legacy = (args.legacy_bin_dir / 'qec-graph').resolve(strict=True) if args.legacy_bin_dir else None
    with tempfile.TemporaryDirectory(prefix='qecgraph-installed-') as directory:
        report = verify(binary, Path(directory), real_source, legacy)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
