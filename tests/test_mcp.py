import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qecgraph.ai_tools import ReadOnlySession, TOOL_NAMES
from qecgraph.mcp_server import MAX_REQUEST_BYTES, MCPServer, PROTOCOL_VERSION, serve_stdio
from qecgraph.store import ingest


def request(identifier, method, params=None):
    return {'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params or {}}


def initialization(version=PROTOCOL_VERSION):
    return request(1, 'initialize', {'protocolVersion': version, 'capabilities': {},
                                    'clientInfo': {'name': 'qecgraph-contract-test', 'version': '1'}})


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.entry = self.root / 'main.tex'
        self.marker = self.root / 'must-not-execute'
        self.entry.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{a}Full assumption H and conclusion.'
                              + '\\immediate\\write18{touch ' + str(self.marker) + '}' + r'\end{lemma}')
        self.store = self.root / 'store'
        ingest(self.entry, 'mcp', self.store)
        self.session = ReadOnlySession(store=self.store)

    def ready(self, **kwargs):
        server = MCPServer(self.session, **kwargs)
        response = server.handle(initialization())
        self.assertEqual(response['result']['protocolVersion'], PROTOCOL_VERSION)
        self.assertIsNone(server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
        return server

    def test_lifecycle_version_offer_tools_and_exact_query_envelope(self):
        server = MCPServer(self.session)
        self.assertEqual(server.handle(request(0, 'tools/list'))['error']['code'], -32002)
        response = server.handle(initialization('future-client-version'))
        self.assertEqual(response['result']['protocolVersion'], PROTOCOL_VERSION)
        self.assertFalse(response['result']['capabilities']['tools']['listChanged'])
        self.assertEqual(server.handle(request(2, 'tools/list'))['error']['code'], -32002)
        server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        tools = server.handle(request(3, 'tools/list'))['result']['tools']
        self.assertEqual(tuple(tool['name'] for tool in tools), TOOL_NAMES)
        arguments = {'identifier': 'a'}
        result = server.handle(request(4, 'tools/call', {'name': 'qecgraph_show', 'arguments': arguments}))['result']
        self.assertEqual(result['structuredContent'], self.session.invoke('qecgraph_show', arguments))
        self.assertEqual(json.loads(result['content'][0]['text']), result['structuredContent'])
        self.assertFalse(result['isError'])
        self.assertEqual(server.handle(request(5, 'ping'))['result'], {})

    def test_protocol_errors_execution_errors_and_rate_limit_are_distinct(self):
        server = self.ready()
        self.assertEqual(server.handle(request(2, 'tools/call', {'name': 'write_file'}))['error']['code'], -32602)
        self.assertEqual(server.handle(request(3, 'tools/call', {'name': 'qecgraph_show', 'arguments': {'identifier': 'a', 'store': '/tmp/other'}}))['error']['code'], -32602)
        missing = server.handle(request(4, 'tools/call', {'name': 'qecgraph_show', 'arguments': {'identifier': 'missing'}}))['result']
        self.assertTrue(missing['isError'])
        self.assertEqual(missing['structuredContent']['error']['code'], 'NOT_FOUND')
        self.assertEqual(server.handle(request(5, 'unknown/method'))['error']['code'], -32601)
        limited = self.ready(calls_per_second=1, clock=lambda: 0)
        call = request(6, 'tools/call', {'name': 'qecgraph_show', 'arguments': {'identifier': 'a'}})
        self.assertIn('result', limited.handle(call))
        self.assertEqual(limited.handle(call)['error']['code'], -32029)

    def test_strict_json_framing_and_byte_limit(self):
        invalid = b'{"jsonrpc":"2.0","id":1,"id":2}\n{"value":NaN}\n\xff\n'
        valid = (json.dumps(initialization()) + '\n').encode()
        output = io.BytesIO()
        self.assertEqual(serve_stdio(self.session, input_stream=io.BytesIO(invalid + valid), output_stream=output), 0)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([item['error']['code'] for item in responses[:3]], [-32700] * 3)
        self.assertEqual(responses[3]['result']['protocolVersion'], PROTOCOL_VERSION)
        output = io.BytesIO()
        self.assertEqual(serve_stdio(self.session, input_stream=io.BytesIO(b'x' * (MAX_REQUEST_BYTES + 1)), output_stream=output), 1)
        self.assertEqual(json.loads(output.getvalue())['error']['code'], -32700)
        self.assertEqual(MCPServer(self.session).handle([])['error']['code'], -32600)
        self.assertEqual(MCPServer(self.session).handle({'jsonrpc': '2.0', 'id': True, 'method': 'ping'})['error']['code'], -32600)

    def test_invalid_unicode_request_id_does_not_stop_stdio(self):
        messages = [request('\ud800', 'ping'), request('量子😀', 'ping')]
        incoming = io.BytesIO(''.join(json.dumps(message) + '\n' for message in messages).encode('ascii'))
        output = io.BytesIO()
        self.assertEqual(serve_stdio(self.session, input_stream=incoming, output_stream=output), 0)
        invalid, valid = map(json.loads, output.getvalue().splitlines())
        self.assertIsNone(invalid['id'])
        self.assertEqual(invalid['error']['code'], -32600)
        self.assertEqual(valid, {'jsonrpc': '2.0', 'id': '量子😀', 'result': {}})

    def test_actual_stdio_process_is_read_only_and_never_executes_source(self):
        before = {str(p.relative_to(self.store)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.store.rglob('*') if p.is_file()}
        messages = [initialization(), {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, request(2, 'tools/list'),
                    request(3, 'tools/call', {'name': 'qecgraph_context', 'arguments': {'identifier': 'a'}})]
        proc = subprocess.run([sys.executable, '-m', 'qecgraph', 'serve-mcp', '--store', str(self.store)],
                               input=''.join(json.dumps(item) + '\n' for item in messages), capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[-1]['result']['structuredContent'], self.session.invoke('qecgraph_context', {'identifier': 'a'}))
        self.assertFalse(self.marker.exists())
        self.assertEqual(before, {str(p.relative_to(self.store)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in self.store.rglob('*') if p.is_file()})
        self.assertEqual(proc.stderr, '')

    def test_full_interactive_client_reproduction(self):
        script = Path(__file__).resolve().parents[1] / 'tools/reproduce_mcp.py'
        proc = subprocess.run([sys.executable, str(script), '--out', str(self.root / 'client-reproduction')],
                               capture_output=True, text=True, timeout=45)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        summary = json.loads(proc.stdout)
        self.assertEqual(summary['status'], 'passed')
        self.assertGreaterEqual(summary['checks'], 22)
        config = subprocess.run([sys.executable, '-m', 'qecgraph', 'mcp-config', '--store', str(self.store)],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(config.returncode, 0, config.stderr)
        server = json.loads(config.stdout)['mcpServers']['qecgraph']
        self.assertEqual(server['command'], sys.executable)
        self.assertIn('--snapshot', server['args'])


if __name__ == '__main__':
    unittest.main()
