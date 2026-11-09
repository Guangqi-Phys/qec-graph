"""Explicit Lean build jobs. Never imported as an action by read-only tools."""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from importlib.resources import files
from importlib.metadata import version
from jsonschema import Draft202012Validator

from . import __version__
from .graph import canonical, hash_text, read_json, strict_json_loads
from .transactions import atomic_json, writer_lock


def producer_manifest():
    package = Path(__file__).parent
    names = ('lean.py', 'graph.py', 'transactions.py', '__init__.py', 'validators/schemas/lean-export.v1.schema.json')
    return {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in names}


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
    elan = shutil.which('elan')
    if elan:
        selected_lake = subprocess.run([elan, 'which', 'lake'], cwd=project, capture_output=True,
                                       text=True, timeout=15, check=False)
        if selected_lake.returncode == 0 and Path(selected_lake.stdout.strip()).is_file():
            return Path(selected_lake.stdout.strip()).resolve()
        raise ValueError('The pinned Elan toolchain is unavailable; install it explicitly or pass --lake')
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
    return {'project_commit': commit, 'repository_project_path': relative, 'project_worktree_dirty': bool(status or untracked),
            'worktree_status': status, 'patch_sha256': hash_text(canonical(payload)),
            'patch_protocol': 'sha256:canonical-json-of-git-binary-diff-and-untracked-input-hashes-v1',
            'untracked_inputs': untracked}


def audit_export(export, policy, targets):
    schema = json.loads(files('qecgraph.validators').joinpath('schemas/lean-export.v1.schema.json').read_text(encoding='utf-8'))
    errors = list(Draft202012Validator(schema).iter_errors(export))
    if errors:
        raise ValueError('Lean export schema: ' + errors[0].message)
    if policy.get('schema_version') != 'qecgraph.axiom-policy.v1' or not isinstance(policy.get('allowed_axioms'), list):
        raise ValueError('Unknown axiom policy schema')
    if targets.get('schema_version') != 'qecgraph.lean-targets.v1':
        raise ValueError('Unknown Lean target policy schema')
    declarations = {item['name']: item for item in export['declarations']}
    if len(declarations) != len(export['declarations']):
        raise ValueError('Duplicate declarations in actual Lean export')
    issues = []
    for name, expected in targets['required_declarations'].items():
        actual = declarations.get(name)
        if actual is None or any(actual.get(key) != value for key, value in expected.items()):
            issues.append({'code': 'missing_or_wrong_target', 'declaration': name, 'expected': expected})
    allowed = set(policy['allowed_axioms'])
    bindings = {}
    for name, declaration in declarations.items():
        if declaration['type_has_metavariables'] or declaration['dependencies_filtered']:
            issues.append({'code': 'incomplete_actual_declaration', 'declaration': name})
        rejected = sorted(axiom for axiom in declaration['axioms_transitive']
                          if axiom not in allowed or axiom == 'sorryAx' or axiom.endswith('.sorryAx'))
        if rejected:
            issues.append({'code': 'axiom_policy_rejected', 'declaration': name, 'axioms': rejected})
        bindings[name] = {'module': declaration['module'], 'kind': declaration['kind'],
                          'type_expr_sha256': hash_text(canonical(declaration['type_expr'])),
                          'type_hash_protocol': 'sha256:json-sort-utf8-v1:exported-Lean.Expr-structure-v1',
                          'axioms_transitive': declaration['axioms_transitive']}
    return {'status': 'allowed' if not issues else 'rejected', 'policy': policy, 'issues': issues,
            'axioms_observed': sorted({axiom for item in export['declarations'] for axiom in item['axioms_transitive']}),
            'declaration_bindings': bindings, 'semantic_review': 'not_reviewed'}


def build_project(project, out, *, lake=None, clean=True, export_declarations=True):
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
              'producer_inputs': producer_manifest(),
              'runtime': {'platform': platform.platform(), 'machine': platform.machine(),
                          'python': platform.python_version(), 'jsonschema': version('jsonschema')},
              'declaration_export': 'not_performed', 'axiom_audit': 'not_run', 'semantic_review': 'not_reviewed'}
    started = time.perf_counter()

    def execute(name, arguments):
        command = [str(x) for x in arguments]
        proc = subprocess.run(command, cwd=project, capture_output=True, text=True, encoding='utf-8', timeout=180)
        (run / (name + '.stdout.txt')).write_text(proc.stdout, encoding='utf-8')
        (run / (name + '.stderr.txt')).write_text(proc.stderr, encoding='utf-8')
        report['commands'].append({'name': name, 'command': command, 'exit_code': proc.returncode,
                                   'stdout': name + '.stdout.txt', 'stderr': name + '.stderr.txt',
                                   'stdout_sha256': hashlib.sha256(proc.stdout.encode('utf-8')).hexdigest(),
                                   'stderr_sha256': hashlib.sha256(proc.stderr.encode('utf-8')).hexdigest()})
        if proc.returncode:
            raise ValueError(f'Lean command {name} failed with exit {proc.returncode}; see saved logs')
        return proc.stdout.strip()

    try:
        with writer_lock(project / '.lake'):
            executable = resolve_lake(project, lake)
            lock = read_json(project / 'toolchain-lock.json')
            report['toolchain_lock'] = lock
            report['lean_toolchain'] = (project / 'lean-toolchain').read_text(encoding='utf-8').strip()
            if report['lean_toolchain'] != 'leanprover/lean4:v' + lock['lean_version']:
                raise ValueError('lean-toolchain and the explicit toolchain lock disagree')
            report['lake_version'] = execute('lake_version', [executable, '--version'])
            lean_version = execute('lean_version', [executable, 'env', 'lean', '--version'])
            if 'version ' + lock['lean_version'] + ',' not in lean_version or lock['lean_commit'][:12] not in lean_version:
                raise ValueError('Selected Lean binary differs from the pinned version/commit')
            report['lean_version'] = lean_version
            prefix = Path(execute('lean_prefix', [executable, 'env', 'lean', '--print-prefix'])).resolve()
            if executable != (prefix / 'bin/lake').resolve():
                raise ValueError('Pass the real Lake binary from the selected Lean toolchain, not a launcher')
            binaries = {name: (prefix / 'bin' / name).resolve() for name in ('lake', 'lean')}
            report['tool_binaries'] = {name: str(path) for name, path in binaries.items()}
            for name, path in binaries.items():
                report[name + '_binary_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            before = source_manifest(project)
            report['input_manifest'] = before
            report['git'] = git_binding(project, before)
            for relative in before:
                target = run / 'inputs' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = (project / relative).read_bytes()
                if hashlib.sha256(raw).hexdigest() != before[relative]:
                    raise ValueError('Lean input changed while archiving: ' + relative)
                target.write_bytes(raw)
            manifest = read_json(project / 'lake-manifest.json')
            report['lake_manifest'] = manifest
            mathlib = next((item for item in manifest.get('packages', []) if item.get('name') == 'mathlib'), None)
            report['mathlib_commit'] = mathlib.get('rev') if mathlib else None
            report['mathlib_status'] = 'locked_dependency' if mathlib else 'not_a_dependency'
            if report['mathlib_commit'] != lock['mathlib_commit']:
                raise ValueError('Lake mathlib dependency differs from the explicit toolchain lock')
            if manifest.get('packages') != []:
                raise ValueError('This adapter requires core-only Lake inputs; external package contents are not yet bound')
            if clean:
                execute('clean', [executable, 'clean'])
            execute('build', [executable, 'build'])
            report['build_status'] = 'build_passed'
            if export_declarations:
                targets = read_json(project / 'targets.json')
                driver = Path(targets['driver'])
                if driver.is_absolute() or not (project / driver).resolve().is_relative_to(project):
                    raise ValueError('Lean export driver escapes the project')
                raw_export = execute('export', [executable, 'env', 'lean', driver])
                export = strict_json_loads(raw_export, source='actual Lean environment export')
                if export.get('lean_version') != lock['lean_version']:
                    raise ValueError('Export and build toolchain versions disagree')
                atomic_json(run / 'export.json', export)
                report['export_ref'] = {'path': 'export.json', 'sha256': hashlib.sha256((run / 'export.json').read_bytes()).hexdigest(),
                                        'raw_stdout_sha256': hashlib.sha256((run / 'export.stdout.txt').read_bytes()).hexdigest()}
                report['declaration_export'] = 'exported'
                policy = read_json(project / 'axiom-policy.json')
                audit = audit_export(export, policy, targets)
                atomic_json(run / 'audit.json', audit)
                report['axiom_audit'] = audit['status']
                report['axioms_observed'] = audit['axioms_observed']
                report['declaration_bindings'] = audit['declaration_bindings']
                report['axiom_policy_sha256'] = hashlib.sha256((project / 'axiom-policy.json').read_bytes()).hexdigest()
                report['audit_ref'] = {'path': 'audit.json', 'sha256': hashlib.sha256((run / 'audit.json').read_bytes()).hexdigest()}
            if source_manifest(project) != before:
                raise ValueError('Lean inputs changed during build; evidence is not current')
            if producer_manifest() != report['producer_inputs']:
                raise ValueError('Lean evidence producer changed during build; retry with a fixed revision')
            if any(hashlib.sha256(path.read_bytes()).hexdigest() != report[name + '_binary_sha256']
                   for name, path in binaries.items()):
                raise ValueError('Lean executable changed during build')
            report['compiled_olean_sha256'] = {str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
                                               for path in sorted((project / '.lake/build').rglob('*.olean'))}
            report['status'] = ('validated_build' if report['axiom_audit'] == 'allowed' else 'trust_rejected') if export_declarations else 'build_passed'
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        report['status'], report['error'] = 'failed', str(exc)
    report['elapsed_seconds'] = time.perf_counter() - started
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    atomic_json(run / 'report.json', report)
    atomic_json(out / 'LATEST.json', {'path': str((run / 'report.json').relative_to(out))})
    return {'status': report['status'], 'report': str(run / 'report.json'), 'error': report.get('error'),
            'suggested_exit_code': 0 if report['status'] in {'build_passed', 'validated_build'} else 1}
