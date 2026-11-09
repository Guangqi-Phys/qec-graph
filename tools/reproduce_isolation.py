#!/usr/bin/env python3
"""Verify both OS denial and an actual MCP read under the macOS profile."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from mcp_isolated_macos import command

PROBE = r"""
import errno, json, os, socket, sys, qecgraph
machine, vault, inbox = sys.argv[1:]
def denied(op):
    try:
        op()
    except OSError as exc:
        return exc.errno in (errno.EPERM, errno.EACCES)
    return False
with open(machine + '/CURRENT.json', 'rb') as readable:
    machine_readable = bool(readable.read())
result = {'read_machine': machine_readable,
          'read_note_denied': denied(lambda: open(vault + '/notes/private.md', 'rb')),
          'list_notes_denied': denied(lambda: os.listdir(vault + '/notes')),
          'list_inbox_denied': denied(lambda: os.listdir(inbox)),
          'write_machine_denied': denied(lambda: open(machine + '/isolation-probe', 'xb')),
          'network_bind_denied': denied(lambda: socket.socket().bind(('127.0.0.1', 0)))}
print(json.dumps({'version': qecgraph.__version__, 'checks': result}))
assert all(result.values()), result
"""


def verify(python, root):
    inbox = root / 'inputs'
    inbox.mkdir()
    (inbox / 'fixture').write_bytes(b'\\documentclass{article}\n\\begin{document}\nIsolation fixture\n\\end{document}\n')
    initial = subprocess.check_output([str(python), '-I', '-B', '-m', 'qecgraph', 'init'],
                                      cwd=root, text=True, timeout=30)
    assert json.loads(initial)['human']['status'] == 'current'
    private = root / 'human/notes/private.md'
    private.write_text('ISOLATION-PROBE-43af', encoding='utf-8')
    machine = root / 'machine'
    cmd = command(python, machine)
    checked = subprocess.check_output([*cmd, '-c', PROBE, str(machine), str(root / 'human'), str(inbox)],
                                      cwd=root, text=True, timeout=30)
    report = json.loads(checked)
    requests = [
        {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                    'clientInfo': {'name': 'isolation-replay', 'version': '1'}}},
        {'method': 'notifications/initialized'},
        {'id': 2, 'method': 'tools/call', 'params': {'name': 'qecgraph_search', 'arguments': {'query': 'Isolation fixture'}}},
    ]
    result = subprocess.run([*cmd, '-m', 'qecgraph', 'mcp', 'serve', '--machine', str(machine)], cwd=root,
                            input=''.join(json.dumps({'jsonrpc': '2.0', **r}) + '\n' for r in requests),
                            text=True, capture_output=True, timeout=30, check=True)
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[-1]['result']['structuredContent']['data']['results']
    assert 'ISOLATION-PROBE-43af' not in result.stdout + result.stderr
    return {**report, 'passed': True, 'isolated_mcp_search': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='qecgraph-isolation-') as directory:
        report = verify(args.python.absolute(), Path(directory).resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
