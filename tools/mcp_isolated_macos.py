#!/usr/bin/env python3
"""Launch a wheel-installed MCP process with a deny-by-default macOS profile."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

PROFILE = Path(__file__).resolve().parents[1] / 'deploy/mcp-macos.sb'


def command(python, machine):
    if sys.platform != 'darwin':
        raise ValueError('Use the machine-only container profile on non-macOS hosts')
    python = Path(python).absolute()
    if not python.is_file():
        raise ValueError('Expected a Python executable from an installed wheel environment')
    machine = Path(machine)
    if machine.is_symlink():
        raise ValueError('Machine directory must not be a symlink')
    machine = machine.resolve(strict=True)
    if machine.name != 'machine' or not (machine / 'CURRENT.json').is_file():
        raise ValueError('Pass the machine directory itself; never pass the whole workspace')
    probe = subprocess.check_output([str(python), '-I', '-B', '-c',
        'import json, sys; print(json.dumps([sys.prefix, sys.base_prefix]))'], text=True)
    venv, base = map(lambda p: Path(p).resolve(strict=True), json.loads(probe))
    if venv == base or not (venv / 'pyvenv.cfg').is_file():
        raise ValueError('Use a separate virtual environment with the QEC Graph wheel installed')
    if any(machine.is_relative_to(root) or root.is_relative_to(machine.parent) for root in (venv, base)):
        raise ValueError('Keep the wheel environment outside the workspace')
    options = {'QEC_PYTHON': str(python), 'QEC_PYTHON_REAL': str(python.resolve(strict=True)),
               'QEC_FRAMEWORK_EXE': str(base / 'Resources/Python.app/Contents/MacOS/Python'),
               'QEC_VENV': str(venv), 'QEC_PYTHON_BASE': str(base), 'QEC_MACHINE': str(machine),
               'QEC_WORKSPACE': str(machine.parent), 'QEC_HUMAN': str(machine.parent / 'human')}
    args = ['/usr/bin/sandbox-exec', '-f', str(PROFILE)]
    for key, value in options.items():
        args.extend(('-D', key + '=' + value))
    return [*args, str(python), '-I', '-B']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', required=True)
    parser.add_argument('--machine', required=True)
    parser.add_argument('--release')
    args = parser.parse_args()
    try:
        cmd = [*command(args.python, args.machine), '-m', 'qecgraph', 'mcp', 'serve',
               '--machine', str(Path(args.machine).resolve(strict=True))]
        if args.release:
            cmd.extend(('--release', args.release))
        os.execv(cmd[0], cmd)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
