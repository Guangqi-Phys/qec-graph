"""Run the pinned Lean positive and trust/freshness failure cases in isolated inputs."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from qecgraph import query
from qecgraph.corpus import project
from qecgraph.graph import read_json
from qecgraph.lean import build_project, resolve_lake
from qecgraph.lean_integration import import_build, inspect_build
from qecgraph.registry import Registry
from qecgraph.transactions import atomic_json

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/lean'
LEAN = ROOT / 'lean'
EXAMPLE = ROOT / 'examples/lean'
NAME = 'QEC.Binary.css_example_commutes'


def write(path, source):
    path.write_text(source, encoding='utf-8')


def reproduce(out, lake=None):
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Trust replay requires an empty output directory')
    out.mkdir(parents=True, exist_ok=True)
    lake = resolve_lake(LEAN, lake)
    cases = {}

    def save(status='running'):
        atomic_json(out / 'results.json', {'status': status,
                                           'lake': str(lake), 'cases': cases})

    def build(case, inputs, expected):
        result = build_project(inputs, out / 'runs' / case, lake=lake)
        assert result['status'] == expected, result
        report_path = Path(result['report'])
        report = read_json(report_path)
        cases[case] = {'status': result['status'], 'report': str(report_path.relative_to(out)),
                       'exit_code': result['suggested_exit_code'], 'project_commit': report['git'].get('project_commit'),
                       'project_worktree_dirty': report['git'].get('project_worktree_dirty')}
        save()
        return report_path, report

    fixed_path, fixed = build('fixed', LEAN, 'validated_build')
    head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    assert fixed['git']['project_commit'] == head and not fixed['git']['project_worktree_dirty'], fixed['git']
    assert inspect_build(fixed_path, LEAN)['current']
    cases['fixed']['axioms'] = fixed['axioms_observed']

    trust = shutil.copytree(LEAN, out / 'work' / 'trust', ignore=shutil.ignore_patterns('.lake'))
    for path in FIXTURES.glob('*.lean'):
        shutil.copyfile(path, trust / 'QEC' / path.name)
    write(trust / 'QEC.lean', 'import QEC.BadTargets\nimport QEC.Export\n')
    target_names = ['QEC.BadTargets.depends_on_admitted', 'QEC.BadTargets.depends_on_custom',
                    'QEC.BadTargets.native_computation']
    write(trust / 'ExportMain.lean', 'import QEC.BadTargets\nimport QEC.Export\n\n#qec_export ['
          + ', '.join(target_names) + ']\n')
    targets = read_json(trust / 'targets.json')
    targets['required_declarations'] = {name: {'kind': 'theorem', 'module': 'QEC.BadTargets'} for name in target_names}
    atomic_json(trust / 'targets.json', targets)
    bad_path, bad = build('axioms', trust, 'trust_rejected')
    assert bad['build_status'] == 'build_passed'
    audit = read_json(bad_path.with_name('audit.json'))
    observed = {issue['declaration']: issue['axioms'] for issue in audit['issues'] if issue['code'] == 'axiom_policy_rejected'}
    assert set(observed) == set(target_names), observed
    assert any(name.endswith('sorryAx') for name in observed[target_names[0]])
    assert 'QEC.BadTargets.customTrust' in observed[target_names[1]]
    assert observed[target_names[2]]
    assert 'sorry' not in (trust / 'QEC/BadTargets.lean').read_text(encoding='utf-8')
    try:
        import_build(out / 'rejected-corpus', bad_path, project_id='bad', historical=True)
    except ValueError as exc:
        assert 'actual validated build' in str(exc)
    else:
        raise AssertionError('Trust-rejected build unexpectedly imported')
    cases['axioms']['actual_rejected_axioms_by_target'] = observed

    changed = shutil.copytree(LEAN, out / 'work' / 'changed', ignore=shutil.ignore_patterns('.lake'))
    matrix = changed / 'row-pair.json'
    atomic_json(matrix, {'HX': [[1, 1, 0]], 'HZ': [[1, 1, 1]]})
    base_path, base = build('matrix_input', changed, 'validated_build')
    registry = Registry(out / 'freshness-corpus')
    import_build(registry.root, base_path, project_id='fixture', project=changed)
    graph, scope = project(registry.root)
    declaration_id = 'lean:fixture:' + NAME
    assert query.show(graph, declaration_id)['node']['build_binding']['effective_status'] == 'current'

    def assert_stale(case, file, replacement):
        original = file.read_bytes()
        try:
            file.write_bytes(replacement)
            graph, _ = project(registry.root, scope['registry_revision'])
            shown = query.show(graph, declaration_id)
            binding = shown['node']['build_binding']
            assert binding['effective_status'] == 'stale' and {'code': 'lean_inputs_changed'} in binding['reasons']
            assert shown['outgoing'] and all(edge['status'] == 'stale' for edge in shown['outgoing'])
            assert not query.dependencies(graph, declaration_id, include_candidates=True)['edges']
            assert not inspect_build(base_path, changed)['current']
            cases[case] = {'status': 'passed', 'path': str(file.relative_to(changed)), 'binding': binding}
        finally:
            file.write_bytes(original)
        save()

    binary = changed / 'QEC/Binary.lean'
    source = binary.read_text(encoding='utf-8')
    theorem = 'theorem css_example_commutes : dot 3 exampleHX exampleHZ = false := by\n  decide'
    weakened = ('theorem css_example_commutes (h : dot 3 exampleHX exampleHZ = false) : '
                'dot 3 exampleHX exampleHZ = false := h')
    assert source.count(theorem) == 1
    weakened_source = source.replace(theorem, weakened)
    assert_stale('type_changed', binary, weakened_source.encode('utf-8'))
    assert_stale('imports_changed', binary, source.replace('import Init', 'import Lean', 1).encode('utf-8'))
    assert_stale('toolchain_changed', changed / 'lean-toolchain', b'leanprover/lean4:v0.0.0\n')
    assert_stale('matrix_changed', matrix, b'{"HX":[[1,0,0]],"HZ":[[1,1,1]]}\n')

    write(binary, weakened_source)
    weakened_path, weak = build('extra_assumption', changed, 'validated_build')
    original_type = base['declaration_bindings'][NAME]['type_expr_sha256']
    actual_type = weak['declaration_bindings'][NAME]['type_expr_sha256']
    assert actual_type != original_type
    mapping_registry = Registry(out / 'mapping-corpus')
    revision = mapping_registry.add_record(read_json(EXAMPLE / 'claim.json'))['registry_revision']
    mapping = read_json(EXAMPLE / 'mapping.json')
    mapping['source_refs'] = []
    try:
        import_build(mapping_registry.root, weakened_path, project_id='fixture', project=changed, mappings=[mapping])
    except ValueError as exc:
        assert 'mapping type mismatch' in str(exc), str(exc)
        cases['mapping_rejected'] = {'status': 'passed', 'expected_type_sha256': original_type,
                                     'actual_type_sha256': actual_type, 'error': str(exc)}
    else:
        raise AssertionError('Adding the conclusion as a hypothesis unexpectedly matched')
    assert mapping_registry.read()[1] == revision

    write(changed / 'ExportMain.lean', 'import QEC.Binary\nimport QEC.Export\n\n#qec_export [QEC.Binary.dot_commutes]\n')
    missing_path, missing = build('other_target_only', changed, 'trust_rejected')
    assert missing['build_status'] == 'build_passed'
    missing_audit = read_json(missing_path.with_name('audit.json'))
    assert any(issue['code'] == 'missing_or_wrong_target' and issue['declaration'] == NAME
               for issue in missing_audit['issues'])
    save('passed')
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='New or empty replay output directory')
    parser.add_argument('--lake')
    args = parser.parse_args()
    cases = reproduce(args.out, args.lake)
    print(json.dumps({'status': 'passed', 'cases': len(cases)}, indent=2))


if __name__ == '__main__':
    main()
