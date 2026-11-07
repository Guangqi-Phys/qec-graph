"""Replay the CLI from an installed wheel in a separate working directory."""
import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples'
KNOWLEDGE = ROOT / 'knowledge_starter'


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
        assert {'record.v3.schema.json', 'lean-export.v1.schema.json'} <= set(pkg['schemas'])
        source = EXAMPLES / 'paper/main.tex'
        split = call('split', 'qec-latex-split', source, '--project-id', 'demo', '--out', 'split')
        assert split['fragment_count'] == 26
        call('split_validate', 'qec-graph', 'validate', '--store', 'split')
        call('mcp_entrypoint', 'qecgraph-mcp', '--help', as_json=False)
        call('ingest', 'qecgraph', 'ingest', source, '--project-id', 'demo', '--out', 'store', '--strict',
             '--annotations', EXAMPLES / 'annotations.example.json')
        corpus = ('--corpus', 'corpus')
        call('register', 'qecgraph', 'register', *corpus, '--store', 'store', '--work-id', 'work:demo',
             '--source-version-id', 'version:demo:1')
        call('record', 'qecgraph', 'record-add', EXAMPLES / 'claim.example.json', *corpus)
        call('link', 'qecgraph', 'claim-link', EXAMPLES / 'claim-link.example.json', *corpus)
        ctx = call('context', 'qecgraph', 'context', 'version:demo:1::thm:hgp-length', *corpus, '--include-candidates')
        assert any(edge['relation'] == 'normalizes_to' and edge['status'] == 'candidate' for edge in ctx['edges'])
        call('migrate', 'qecgraph', 'migrate', KNOWLEDGE / 'records', '--source-root', KNOWLEDGE, '--out', 'migration')
        migrated = call('migration_import', 'qecgraph', 'migration-import', 'migration', *corpus)
        actor = ('--actor-id', 'release-smoke', '--actor-kind', 'program')
        proposal = call('proposal', 'qecgraph', 'review', EXAMPLES / 'proposal.example.json', *corpus, *actor)
        decision = call('decision', 'qecgraph', 'review-decide', proposal['id'], *corpus, *actor, '--decision',
                        'approve', '--rationale', 'Fixture transaction only; no human review')
        apply_args = ('apply', proposal['id'], '--review-id', decision['id'], *corpus)
        applied = call('apply', 'qecgraph', *apply_args)
        again = call('apply_repeat', 'qecgraph', *apply_args)
        assert applied['receipt'] == again['receipt'] and decision['status'] == 'machine_accepted'
        shown = call('audit_applied', 'qecgraph', 'show', 'claim:demo:proposal-example', *corpus)
        assert shown['node']['review_status'] == 'proposed'
        call('validate_corpus', 'qecgraph', 'validate-corpus', *corpus)
        call('mcp_config', 'qecgraph', 'mcp-config', *corpus)
        matrix = KNOWLEDGE / 'assets/matrices'
        finite = call('finite_css', 'qecgraph', 'check-css', '--hx', matrix / 'HX.gf2.json', '--hz', matrix / 'HZ.gf2.json',
                      '--lx', matrix / 'LX.gf2.json', '--lz', matrix / 'LZ.gf2.json', '--enumerate-distance')
        assert (finite['n'], finite['k'], finite['distance']['d']) == (13, 1, 3)
        assert finite['distance']['evidence_kind'] == 'computed_exact' and finite['lean_status'] == 'not_performed'
        report.update(status='passed', installed=pkg, migrated=migrated, application_receipt=applied['receipt'],
                      proposed_after_machine_acceptance=True, finite_css=finite)
        save()
    except (OSError, ValueError, RuntimeError, KeyError, AssertionError, subprocess.SubprocessError) as exc:
        report.update(status='failed', error=str(exc))
        save()
        raise
    print(json.dumps({'status': report['status'], 'commands': len(report['steps'])}, indent=2))


if __name__ == '__main__':
    main()
