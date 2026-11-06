"""Explicit Lean build jobs. Never imported as an action by read-only tools."""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .graph import canonical, hash_text, read_json
from .transactions import atomic_json, writer_lock


def source_manifest(project):
    result = {}
    for path in sorted(Path(project).rglob('*')):
        if not path.is_file() or '.lake' in path.relative_to(project).parts:
            continue
        if path.suffix in {'.lean', '.toml', '.json'} or path.name == 'lean-toolchain':
            result[str(path.relative_to(project))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def resolve_lake(project, explicit=None):
    if explicit:
        path = Path(shutil.which(str(explicit)) or explicit).resolve()
        if not path.is_file():
            raise ValueError('Explicit Lake executable is missing')
        return path
    selected = (Path(project) / 'lean-toolchain').read_text(encoding='utf-8').strip()
    version = selected.rsplit(':v', 1)[-1]
    candidates = sorted((Path(project).parent / '.tools').glob('lean-' + version + '-*/bin/lake'))
    if candidates:
        return candidates[0].resolve()
    installed = shutil.which('lake')
    if installed:
        return Path(installed).resolve()
    raise ValueError('Lean toolchain is not installed; install the pinned version or pass --lake. No automatic installation was attempted.')


def git_binding(project, manifest):
    def git(*args):
        return subprocess.run(['git', '-C', str(project), *args], capture_output=True, check=False).stdout
    commit = git('rev-parse', 'HEAD').decode().strip()
    if len(commit) != 40:
        return {'project_commit': None, 'worktree_status': 'not_a_git_worktree', 'patch_sha256': None}
    repository = Path(git('rev-parse', '--show-toplevel').decode().strip())
    relative = str(Path(project).relative_to(repository))
    tracked = set(git('ls-files', '--', '.').decode().splitlines())
    untracked = {path: digest for path, digest in manifest.items() if path not in tracked}
    diff = git('diff', '--binary', 'HEAD', '--', '.')
    status = git('status', '--porcelain', '--', '.').decode()
    payload = {'tracked_binary_diff': diff.decode('utf-8'), 'untracked_input_sha256': untracked}
    return {'project_commit': commit, 'repository_project_path': relative, 'project_worktree_dirty': bool(status),
            'worktree_status': status, 'patch_sha256': hash_text(canonical(payload)),
            'patch_protocol': 'sha256:canonical-json-of-git-binary-diff-and-untracked-input-hashes-v1',
            'untracked_inputs': untracked}


def build_project(project, out, *, lake=None, clean=True):
    project, out = Path(project).resolve(), Path(out).resolve()
    if out == project or out.is_relative_to(project):
        raise ValueError('Lean evidence output must be separate from project inputs')
    marker = out / '.qecgraph-lean-build.json'
    if out.exists() and any(out.iterdir()) and not marker.exists():
        raise ValueError('Lean output must be empty or previously managed')
    if marker.exists() and read_json(marker) != {'format': 'qecgraph.lean-build-store.v1'}:
        raise ValueError('Incompatible Lean evidence output marker')
    atomic_json(marker, {'format': 'qecgraph.lean-build-store.v1'})
    run = out / ('run-' + str(uuid.uuid4()))
    run.mkdir()
    report = {'schema_version': 'qecgraph.lean-build.v1', 'status': 'running',
              'project': str(project), 'started_at': datetime.now(timezone.utc).isoformat(), 'commands': [],
              'producer_version': __version__, 'producer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'runtime': {'platform': platform.platform(), 'machine': platform.machine()},
              'declaration_export': 'not_performed', 'axiom_audit': 'not_run', 'semantic_review': 'not_reviewed'}
    started = time.perf_counter()

    def execute(name, arguments):
        command = [str(x) for x in arguments]
        proc = subprocess.run(command, cwd=project, capture_output=True, text=True, encoding='utf-8', timeout=180)
        (run / (name + '.stdout.txt')).write_text(proc.stdout, encoding='utf-8')
        (run / (name + '.stderr.txt')).write_text(proc.stderr, encoding='utf-8')
        report['commands'].append({'name': name, 'command': command, 'exit_code': proc.returncode,
                                   'stdout': name + '.stdout.txt', 'stderr': name + '.stderr.txt'})
        if proc.returncode:
            raise ValueError(f'Lean command {name} failed with exit {proc.returncode}; see saved logs')
        return proc.stdout.strip()

    try:
        with writer_lock(project / '.lake'):
            executable = resolve_lake(project, lake)
            lock = read_json(project / 'toolchain-lock.json')
            report['toolchain_lock'] = lock
            report['lean_toolchain'] = (project / 'lean-toolchain').read_text(encoding='utf-8').strip()
            report['lake_version'] = execute('lake_version', [executable, '--version'])
            lean_version = execute('lean_version', [executable, 'env', 'lean', '--version'])
            if 'version ' + lock['lean_version'] + ',' not in lean_version or lock['lean_commit'][:12] not in lean_version:
                raise ValueError('Selected Lean binary differs from the pinned version/commit')
            report['lean_version'] = lean_version
            report['lake_binary_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
            report['lean_binary_sha256'] = hashlib.sha256((executable.parent / 'lean').read_bytes()).hexdigest()
            before = source_manifest(project)
            report['input_manifest'] = before
            report['git'] = git_binding(project, before)
            for relative in before:
                target = run / 'inputs' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((project / relative).read_bytes())
            manifest = read_json(project / 'lake-manifest.json')
            report['lake_manifest'] = manifest
            mathlib = next((item for item in manifest.get('packages', []) if item.get('name') == 'mathlib'), None)
            report['mathlib_commit'] = mathlib.get('rev') if mathlib else None
            report['mathlib_status'] = 'locked_dependency' if mathlib else 'not_a_dependency'
            if clean:
                execute('clean', [executable, 'clean'])
            execute('build', [executable, 'build'])
            if source_manifest(project) != before:
                raise ValueError('Lean inputs changed during build; evidence is not current')
            report['compiled_olean_sha256'] = {str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
                                               for path in sorted((project / '.lake/build').rglob('*.olean'))}
            report['status'] = 'build_passed'
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        report['status'], report['error'] = 'failed', str(exc)
    report['elapsed_seconds'] = time.perf_counter() - started
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    atomic_json(run / 'report.json', report)
    atomic_json(out / 'LATEST.json', {'path': str((run / 'report.json').relative_to(out))})
    return {'status': report['status'], 'report': str(run / 'report.json'), 'error': report.get('error'),
            'suggested_exit_code': 0 if report['status'] == 'build_passed' else 1}
