"""Connect a real stdio client and compare CLI/Python/MCP on fixed scopes."""
from __future__ import annotations

import argparse
import hashlib
import json
import select
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from qecgraph.ai_tools import ReadOnlySession, TOOL_NAMES
from qecgraph.graph import read_json
from qecgraph.mcp_server import PROTOCOL_VERSION
from qecgraph.registry import Registry
from qecgraph.store import ingest
from qecgraph.transactions import atomic_json

ROOT = Path(__file__).resolve().parents[1]


class StdioClient:
    def __init__(self, arguments, transcript):
        self.process = subprocess.Popen([sys.executable, '-m', 'qecgraph', 'serve-mcp', *arguments], cwd=ROOT,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True, encoding='utf-8', bufsize=1)
        self.transcript, self.sequence = transcript, 0
        try:
            initialized = self.request('initialize', {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {},
                                                      'clientInfo': {'name': 'qecgraph-reproduction-client', 'version': '1'}})
            if initialized.get('result', {}).get('protocolVersion') != PROTOCOL_VERSION:
                raise RuntimeError('MCP protocol negotiation failed')
            self.notify('notifications/initialized')
        except Exception:
            self.process.terminate()
            self.process.wait(timeout=5)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()
            raise

    def notify(self, method):
        message = {'jsonrpc': '2.0', 'method': method}
        self.transcript.append({'direction': 'client_to_server', 'message': message})
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.sequence += 1
        message = {'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params or {}}
        self.transcript.append({'direction': 'client_to_server', 'message': message})
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
        self.process.stdin.flush()
        if not select.select([self.process.stdout], [], [], 15)[0]:
            raise RuntimeError('MCP client timed out')
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('MCP server closed before responding')
        response = json.loads(line)
        self.transcript.append({'direction': 'server_to_client', 'message': response})
        if response.get('jsonrpc') != '2.0' or response.get('id') != self.sequence:
            raise RuntimeError('MCP response identity mismatch')
        return response

    def call(self, name, arguments):
        response = self.request('tools/call', {'name': name, 'arguments': arguments})
        if 'error' in response:
            return response
        result = response['result']
        if json.loads(result['content'][0]['text']) != result['structuredContent']:
            raise RuntimeError('MCP text and structured content differ')
        return result['structuredContent']

    def close(self):
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            code = self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
            raise RuntimeError('MCP server did not exit on EOF')
        errors = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        if code or errors:
            raise RuntimeError(f'MCP server exit {code}: {errors}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='build/reproduce-mcp')
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    marker = out / '.qecgraph-mcp-reproduce.json'
    if out.exists() and any(out.iterdir()) and not marker.exists():
        parser.error('--out must be empty or managed by this script')
    if marker.exists() and read_json(marker) != {'format': 'qecgraph.mcp-reproduce.v1'}:
        parser.error('Incompatible output marker')
    atomic_json(marker, {'format': 'qecgraph.mcp-reproduce.v1'})
    run = out / ('run-' + str(uuid.uuid4()))
    paper = run / 'paper'
    shutil.copytree(ROOT / 'examples/paper', paper)
    entry, store = paper / 'main.tex', run / 'store'
    result = ingest(entry, 'qec-demo', store, annotations_path=ROOT / 'examples/annotations.example.json')
    registry = Registry(run / 'corpus')
    registered = registry.register_source('work:demo', 'version:demo:1', store)
    transcript, clients = [], []
    report = {'format': 'qecgraph.mcp-reproduction.v1', 'status': 'running',
              'command': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'protocol_version': PROTOCOL_VERSION, 'checks': [], 'client_kind': 'actual subprocess stdio client',
              'external_app_configuration_changed': False}

    def check(name, condition):
        if not condition:
            raise RuntimeError(name)
        report['checks'].append({'name': name, 'passed': True})

    try:
        source = ReadOnlySession(store=store, snapshot_id=result['snapshot_id'])
        client = StdioClient(['--store', str(store), '--snapshot', result['snapshot_id']], transcript)
        clients.append(client)
        tools = client.request('tools/list')['result']['tools']
        check('exact five read-only tools', tuple(tool['name'] for tool in tools) == TOOL_NAMES and all(t['annotations']['readOnlyHint'] for t in tools))
        for name in TOOL_NAMES:
            arguments = {'query': 'HGP'} if name == 'qecgraph_search' else {'identifier': 'thm:hgp-css'}
            expected = source.invoke(name, arguments)
            actual = client.call(name, arguments)
            check(name + ' Python/MCP equality', expected == actual and actual['ok'])
            argument_file = run / (name + '.arguments.json')
            atomic_json(argument_file, arguments)
            command = [sys.executable, '-m', 'qecgraph', 'query-tool', name, '--arguments', str(argument_file),
                       '--store', str(store), '--snapshot', result['snapshot_id']]
            cli = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', cwd=ROOT, timeout=20)
            check(name + ' CLI equality', cli.returncode == 0 and json.loads(cli.stdout) == expected)
        empty = client.call('qecgraph_search', {'query': 'definitely absent phrase'})
        check('empty result retains scope', empty['ok'] and not empty['data']['results'] and empty['data']['scope']['snapshot_id'] == result['snapshot_id'])
        limited = client.call('qecgraph_context', {'identifier': 'thm:hgp-css', 'max_nodes': 1})
        check('node truncation explicit', limited['ok'] and limited['data']['truncated'] and not limited['data']['context_complete'])
        refused = client.call('qecgraph_context', {'identifier': 'thm:hgp-css', 'max_chars': 256})
        check('root budget refuses partial statement', not refused['ok'] and refused['error']['code'] == 'BUDGET_ROOT_TOO_LARGE')
        wrong = client.request('tools/call', {'name': 'qecgraph_show', 'arguments': {'identifier': 'thm:hgp-css', 'store': '/unconfigured'}})
        check('tool cannot switch scope', wrong.get('error', {}).get('code') == -32602)
        for include in (False, True):
            context = client.call('qecgraph_context', {'identifier': 'thm:hgp-css', 'include_candidates': include})
            excluded = {'stale', 'unbound_review', 'unresolved'} | (set() if include else {'candidate'})
            check('context status policy candidates=' + str(include), context['ok'] and all(e['status'] not in excluded for e in context['data']['edges']))
        # Advance both CURRENT pointers while the existing clients keep fixed scopes.
        corpus_client = StdioClient(['--corpus', str(registry.root), '--registry-revision', registered['registry_revision']], transcript)
        clients.append(corpus_client)
        entry.write_bytes(entry.read_bytes() + b'\n% new source revision during a client session\n')
        newer = ingest(entry, 'qec-demo', store, annotations_path=ROOT / 'examples/annotations.example.json')
        registry.register_source('work:demo', 'version:demo:2', store)
        pinned = client.call('qecgraph_show', {'identifier': 'thm:hgp-css'})
        check('MCP stays on old store snapshot', newer['snapshot_id'] != result['snapshot_id'] and pinned['data']['scope']['snapshot_id'] == result['snapshot_id'])
        corpus_result = corpus_client.call('qecgraph_show', {'identifier': 'version:demo:1::thm:hgp-css'})
        check('corpus scope pinned', corpus_result['ok'] and corpus_result['data']['scope']['registry_revision'] == registered['registry_revision'])
        absent_new = corpus_client.call('qecgraph_show', {'identifier': 'version:demo:2::thm:hgp-css'})
        check('new corpus version not silently mixed', not absent_new['ok'] and absent_new['error']['code'] == 'NOT_FOUND')
        duplicate = run / 'duplicates.tex'
        duplicate.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{dup}A.\end{lemma}\begin{lemma}\label{dup}B.\end{lemma}')
        duplicate_store = run / 'duplicates'
        ingest(duplicate, 'duplicates', duplicate_store, project_root=run)
        duplicate_client = StdioClient(['--store', str(duplicate_store)], transcript)
        clients.append(duplicate_client)
        ambiguity = duplicate_client.call('qecgraph_show', {'identifier': 'dup'})
        check('duplicate label remains ambiguous', not ambiguity['ok'] and ambiguity['error']['code'] == 'AMBIGUOUS_SELECTOR')
        partial = run / 'partial.tex'
        partial.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{partial}A.\end{lemma}\input{missing}')
        partial_store = run / 'partial'
        ingest(partial, 'partial', partial_store, project_root=run)
        partial_client = StdioClient(['--store', str(partial_store)], transcript)
        clients.append(partial_client)
        partial_result = partial_client.call('qecgraph_show', {'identifier': 'partial'})
        check('partial extraction visible', partial_result['ok'] and partial_result['data']['extraction_status'] == 'partial')
        report['snapshot_id'] = result['snapshot_id']
        report['registry_revision'] = registered['registry_revision']
        report['status'] = 'passed'
    except Exception as exc:
        report['status'], report['error'] = 'failed', str(exc)
    finally:
        for client in clients:
            try:
                client.close()
            except Exception as exc:
                report['status'], report['shutdown_error'] = 'failed', str(exc)
    transcript_path = run / 'transcript.ndjson'
    transcript_path.write_text(''.join(json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n' for item in transcript), encoding='utf-8')
    report['transcript_sha256'] = hashlib.sha256(transcript_path.read_bytes()).hexdigest()
    atomic_json(run / 'results.json', report)
    atomic_json(out / 'LATEST.json', {'path': str((run / 'results.json').relative_to(out))})
    print(json.dumps({'status': report['status'], 'report': str(run / 'results.json'),
                      'checks': len(report['checks']), 'error': report.get('error')}, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
