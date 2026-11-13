"""Connect a real stdio client and compare CLI/Python/MCP on fixed scopes."""
from __future__ import annotations

import argparse
import json
import select
import subprocess
import sys
import tempfile
from pathlib import Path

from qecgraph.core.transactions import atomic_json
from qecgraph.knowledge import RESEARCH_TOOLS
from qecgraph.mcp.server import PROTOCOL_VERSION
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession

ROOT = Path(__file__).resolve().parents[1]


class StdioClient:
    def __init__(self, arguments, transcript):
        self.process = subprocess.Popen([sys.executable, '-m', 'qecgraph', 'mcp', 'serve', *arguments], cwd=ROOT,
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
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    transcript = []
    with tempfile.TemporaryDirectory(prefix='qec-mcp-') as directory:
        workspace = Workspace(directory)
        workspace.prepare()
        (workspace.root / 'inputs/paper.tex').write_text(
            r'\documentclass{article}\begin{document}Quantum memory result.\end{document}')
        release = workspace.sync()['release_id']
        session = WorkspaceSession(workspace.registry.root, release, profile='research')
        scope = ['--machine', str(session.machine), '--release', release]
        client = StdioClient(scope, transcript)
        try:
            tools = client.request('tools/list')['result']['tools']
            assert {tool['name'] for tool in tools} == set(RESEARCH_TOOLS)
            assert all(tool['annotations']['readOnlyHint'] for tool in tools)
            queries = {
                'qec_list_papers': {},
                'qec_search': {'query': 'quantum memory'},
                'qec_status': {},
                'qec_query_codes': {},
                'qec_query_performance': {},
            }
            for name, query in queries.items():
                assert client.call(name, query) == session.invoke(name, query)
        finally:
            client.close()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {'status': 'passed', 'checks': len(queries) + 2, 'release_id': release}
    atomic_json(args.out / 'results.json', {**report, 'transcript': transcript})
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
