#!/usr/bin/env python3
"""Exercise the production Compose isolation profile with a temporary workspace."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


PROBE = """
import errno
import json
from pathlib import Path
import platform
import socket

def refused_write(path):
    try:
        Path(path).write_text('probe')
    except OSError as exc:
        return exc.errno in {errno.EROFS, errno.EACCES, errno.EPERM}
    return False

status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
checks = {
    'read_machine': bool(json.loads(Path('/machine/CURRENT.json').read_text())['revision']),
    'write_machine_denied': refused_write('/machine/isolation-probe'),
    'write_root_denied': refused_write('/tmp/qecgraph-isolation-probe'),
    'no_network_interface': {name for _, name in socket.if_nameindex()} == {'lo'},
    'no_capabilities': int(status['CapEff'].strip(), 16) == 0,
    'no_new_privileges': status['NoNewPrivs'].strip() == '1',
    'nonroot': int(status['Uid'].split()[0]) != 0,
}
print(json.dumps({'checks': checks, 'platform': platform.platform(), 'python': platform.python_version()}))
"""

PHRASE = 'QEC Linux isolation fixture'
CANARY = 'QEC-LINUX-PRIVATE-CANARY'
ROOT = Path(__file__).resolve().parents[1]


def _run(command, *, env=None, cwd=None, input_text=None):
    result = subprocess.run(command, env=env, cwd=cwd, input=input_text, text=True,
                            capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f'{command[0]} exited {result.returncode}\n{result.stdout}{result.stderr}')
    return result.stdout


def _workspace(root):
    inbox = root / 'inputs'
    inbox.mkdir()
    (inbox / 'sample.tex').write_text(
        '\\documentclass{article}\n\\begin{document}\n' + PHRASE + '\n\\end{document}\n', encoding='utf-8')
    result = json.loads(_run([sys.executable, '-I', '-m', 'qecgraph', 'init', '--json', '--no-human'], cwd=root))
    if result['status'] != 'published' or result['counts']['processed'] != 1:
        raise RuntimeError('Fixture ingestion did not publish one source')
    notes = root / 'human/notes'
    notes.mkdir(parents=True, exist_ok=True)
    (notes / 'private.md').write_text(CANARY, encoding='utf-8')
    (inbox / 'pending.tex').write_text(CANARY, encoding='utf-8')
    return result['release_id']


def _compose(root, env):
    project = 'qec-isolation-' + uuid.uuid4().hex[:12]
    env = {**env, 'QEC_MACHINE_DIR': str(root / 'machine'),
           'QEC_MCP_UID': str(os.getuid()), 'QEC_MCP_GID': str(os.getgid())}
    command = ['docker', 'compose', '-f', str(ROOT / 'compose.mcp-isolated.yaml'), '--project-name', project]
    return command, env


def _requests():
    messages = [
        {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                    'clientInfo': {'name': 'linux-isolation-replay', 'version': '1'}}},
        {'method': 'notifications/initialized'},
        {'id': 2, 'method': 'tools/call', 'params': {'name': 'qecgraph_search', 'arguments': {'query': PHRASE}}},
        {'id': 3, 'method': 'tools/call', 'params': {'name': 'qecgraph_search', 'arguments': {'query': CANARY}}},
        {'id': 4, 'method': 'resources/read', 'params': {'uri': 'file:///human/notes/private.md'}},
    ]
    return ''.join(json.dumps({'jsonrpc': '2.0', **message}) + '\n' for message in messages)


def verify(root):
    if os.getuid() == 0:
        raise RuntimeError('Run the verification as the nonroot owner of the fixture workspace')
    release = _workspace(root)
    command, env = _compose(root, os.environ)
    try:
        service = json.loads(_run([*command, 'config', '--format', 'json'], env=env))['services']['qec-mcp']
        mounts = service.get('volumes', [])
        if len(mounts) != 1 or any(mounts[0].get(k) != v for k, v in {
                'source': str(root / 'machine'), 'target': '/machine', 'type': 'bind', 'read_only': True}.items()):
            raise RuntimeError('Expected exactly one read-only bind mount for machine')
        _run([*command, 'build', 'qec-mcp'], env=env)
        run = [*command, 'run', '--rm', '--no-deps', '-T']
        probe = json.loads(_run([*run, '--entrypoint', 'python', 'qec-mcp', '-I', '-c', PROBE], env=env))
        checks = probe['checks']
        output = _run([*run, 'qec-mcp'], env=env, input_text=_requests())
        responses = {row['id']: row for row in map(json.loads, output.splitlines())}
        found = responses[2]['result']['structuredContent']['data']
        private = responses[3]['result']['structuredContent']['data']
        checks.update(single_machine_mount=True, mcp_search=bool(found['results']),
                      mcp_pinned_release=found['scope']['release_id'] == release,
                      mcp_notes_hidden=not private['results'] and CANARY not in output,
                      mcp_file_uri_denied='error' in responses[4])
        if not all(checks.values()):
            raise RuntimeError(f'Isolation checks failed: {checks}')
        return {**probe, 'passed': True, 'release_id': release,
                'base_image': service['build']['args']['PYTHON_IMAGE']}
    finally:
        failure = sys.exc_info()[1]
        try:
            _run([*command, 'down', '--rmi', 'local'], env=env)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            if failure is None:
                raise
            failure.add_note(f'Compose cleanup also failed: {exc}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='qecgraph-linux-isolation-') as directory:
        report = verify(Path(directory).resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
