"""Replay the actual Lean export, source occurrence, proposed claim and fixed read query."""
import argparse
from pathlib import Path

from qecgraph import query
from qecgraph.ai_tools import ReadOnlySession
from qecgraph.corpus import project
from qecgraph.graph import read_json
from qecgraph.lean_integration import import_build
from qecgraph.registry import Registry
from qecgraph.store import ingest
from qecgraph.transactions import atomic_json

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples/lean'


def replay(report, out, lean_project=ROOT / 'lean'):
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Mapping replay requires an empty output directory')
    out.mkdir(parents=True, exist_ok=True)
    store = out / 'source-store'
    registry = Registry(out / 'corpus')
    source = ingest(EXAMPLE / 'paper/main.tex', 'lean-demo', store, strict=True)
    assert source['extraction_status'] == 'complete_for_supported_syntax'
    registry.register_source('work:lean-demo', 'version:lean-demo:1', store)
    claim = registry.add_record(read_json(EXAMPLE / 'claim.json'))['record']
    mapping = read_json(EXAMPLE / 'mapping.json')
    registry.link_claim('link:lean-demo:1', 'version:lean-demo:1', 'lem:boolean-row-pair', claim['id'])
    result = import_build(registry.root, report, project_id='qec-core', project=lean_project, mappings=[mapping])
    graph, scope = project(registry.root, result['registry_revision'])
    declaration_id = 'lean:qec-core:' + mapping['declaration']
    declaration = query.show(graph, declaration_id)
    mapped = query.show(graph, mapping['id'])
    ctx = query.context(graph, mapping['id'], depth=2, include_candidates=True, max_nodes=15)
    ai = ReadOnlySession(corpus=registry.root, registry_revision=result['registry_revision'])
    bounded = ai.invoke('qecgraph_context', {'identifier': declaration_id, 'depth': 1, 'max_nodes': 8})
    validation = registry.validate(result['registry_revision'])
    assert validation['passed'], validation['issues']
    assert declaration['node']['build_binding']['effective_status'] == 'current'
    assert declaration['node']['data']['type_expr_sha256'] == mapping['expected_type_expr_sha256']
    assert declaration['node']['source']['path'] == 'QEC/Binary.lean'
    assert mapped['node']['build_binding']['effective_status'] == 'current'
    assert mapped['node']['data']['semantic_review'] == 'not_reviewed'
    assert mapped['node']['data']['planned_dependencies'] == ['def:boolean-dot']
    assert registry.record(claim['id']) == claim
    assert {edge['status'] for edge in mapped['outgoing'] if edge['relation'] in {'formalizes', 'maps_source_occurrence'}} == {'candidate'}
    assert any(edge['relation'] == 'lean_proof_depends_on' for edge in declaration['outgoing'])
    assert any(edge['relation'] == 'lean_type_depends_on_transitive' for edge in declaration['outgoing'])
    assert bounded['ok'], bounded
    assert bounded['data']['nodes'][0]['data']['type'] == declaration['node']['data']['type']
    assert 'refs' not in bounded['data']['nodes'][0]['record']
    atomic_json(out / 'mapping-replay.json', {'status': 'passed', 'import': result, 'source_snapshot': source['snapshot_id'],
                 'registry_revision': scope['registry_revision'], 'validation_issue_count': len(validation['issues']),
                 'type_expr_sha256': mapping['expected_type_expr_sha256'], 'semantic_review': 'not_reviewed',
                 'proof_edges': sum(edge['relation'] == 'lean_proof_depends_on' for edge in declaration['outgoing']),
                 'candidate_source_and_claim': True, 'bounded_tool': bounded})
    atomic_json(out / 'formalization.json', mapped)
    atomic_json(out / 'mapping-context.json', ctx)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--out', required=True, help='New or empty replay output directory')
    parser.add_argument('--project', default=ROOT / 'lean')
    args = parser.parse_args()
    replay(args.report, args.out, args.project)


if __name__ == '__main__':
    main()
