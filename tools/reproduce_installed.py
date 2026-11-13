"""Replay the CLI from an installed wheel in a separate working directory."""
import argparse
import json
import os
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', required=True, help='bin directory of a fresh wheel installation')
    parser.add_argument('--out', required=True, help='New or empty replay output directory')
    args = parser.parse_args()
    executables = Path(args.bin_dir).resolve()
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Installed replay requires an empty output directory')
    out.mkdir(parents=True, exist_ok=True)
    report = {'status': 'running', 'steps': []}
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)

    def save():
        (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def call(name, executable, *arguments, as_json=True):
        command = [str(executables / executable), *(str(arg) for arg in arguments)]
        result = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
        for stream in ('stdout', 'stderr'):
            (out / f'{name}.{stream}.txt').write_text(getattr(result, stream), encoding='utf-8')
        report['steps'].append({'name': name, 'command': command, 'exit_code': result.returncode,
                                'stdout': f'{name}.stdout.txt', 'stderr': f'{name}.stderr.txt'})
        save()
        if result.returncode:
            raise RuntimeError(f'{name} exited {result.returncode}; see saved logs')
        return json.loads(result.stdout) if as_json else result.stdout

    try:
        pkg = call('installed_package', 'python', '-I', '-c', '''
import importlib.metadata as m
import importlib.resources as r
import json
import qecgraph
from jsonschema import Draft202012Validator
schemas = r.files("qecgraph.validators").joinpath("schemas")
names = sorted(p.name for p in schemas.iterdir() if p.name.endswith(".json"))
for name in names:
    Draft202012Validator.check_schema(json.loads(schemas.joinpath(name).read_text(encoding="utf-8")))
print(json.dumps({"metadata_version": m.version("qec-graph"), "module_version": qecgraph.__version__,
                  "module_path": qecgraph.__file__, "schemas": names}))
''')
        assert not Path(pkg['module_path']).resolve().is_relative_to(ROOT / 'qecgraph')
        assert pkg['metadata_version'] == pkg['module_version']
        assert {'registry.schema.json', 'research.schema.json'} <= set(pkg['schemas'])
        source = EXAMPLES / 'paper/main.tex'
        split = call('split', 'qec-latex-split', source, '--project-id', 'demo', '--out', 'split')
        assert split['fragment_count'] > 0
        call('mcp_entrypoint', 'qecgraph-mcp', '--help', as_json=False)
        scope = ('--workspace', 'workspace')
        call('init', 'qec-graph', 'init', *scope, '--json')
        with tarfile.open(out / 'workspace/inputs/demo.tar', 'w') as bundle:
            for path in sorted(source.parent.rglob('*')):
                if path.is_file():
                    bundle.add(path, arcname=path.relative_to(source.parent))
        result = call('sync', 'qec-graph', 'sync', *scope, '--no-human', '--json')
        assert result['counts']['processed'] == 1
        validated = call('validate', 'qec-graph', 'validate', *scope, '--json')
        assert validated['valid']
        call('mcp_config', 'qec-graph', 'mcp', 'config', *scope)
        report.update(status='passed', installed=pkg, release_id=result['release_id'])
        save()
    except (OSError, ValueError, RuntimeError, KeyError, AssertionError, subprocess.SubprocessError) as exc:
        report.update(status='failed', error=str(exc))
        save()
        raise
    print(json.dumps({'status': report['status'], 'commands': len(report['steps'])}, indent=2))


if __name__ == '__main__':
    main()
