"""Structural/type validation. Passing these checks is not mathematical evidence."""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files

from jsonschema import Draft202012Validator

STATEMENTS = {'lemma', 'theorem', 'proposition', 'corollary', 'conjecture', 'claim'}
MATHEMATICS = STATEMENTS | {'definition', 'proof', 'equation'}
_SCHEMA = json.loads(files(__package__).joinpath('schemas/record.v3.schema.json').read_text(encoding='utf-8'))
DOMAIN_FIELDS = {entry['if']['properties']['kind']['const']: entry['then']['properties']['data']['required']
                 for entry in _SCHEMA['allOf']}
ENDPOINTS = {
    'proof_of': ({'proof'}, STATEMENTS),
    'proof_of_candidate': ({'proof'}, STATEMENTS),
    'depends_on_declared': (MATHEMATICS, MATHEMATICS),
    'depends_on_candidate': (MATHEMATICS, MATHEMATICS),
    'depends_on_reviewed': (MATHEMATICS, MATHEMATICS),
    'formalizes': ({'lean_declaration', 'formalization'}, MATHEMATICS),
    'supports': ({'evidence'}, {'claim'}),
    'contradicts': ({'evidence', 'claim'}, {'claim'}),
    'has_matrix': ({'code_instance', 'presentation', 'classical_seed'}, {'matrix', 'asset'}),
    'has_presentation': ({'code_instance'}, {'presentation'}),
    'uses_circuit': ({'experiment', 'circuit', 'code_instance', 'presentation'}, {'circuit'}),
    'uses_noise': ({'experiment', 'circuit'}, {'noise'}),
    'uses_decoder': ({'experiment'}, {'decoder'}),
    'normalizes_to': (MATHEMATICS | {'paragraph', 'table', 'remark'}, {'claim'}),
}


def validate_record(record):
    name = 'record.v2.schema.json' if record['schema_version'] == 'qecgraph.record.v2' else 'record.v3.schema.json'
    schema = json.loads(files(__package__).joinpath('schemas/' + name).read_text(encoding='utf-8'))
    errors = sorted(Draft202012Validator(schema).iter_errors(record), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise ValueError('Record schema at ' + '/'.join(map(str, error.path)) + ': ' + error.message)
    if record['schema_version'] == 'qecgraph.record.v2':
        return
    data = record['data']
    for field in DOMAIN_FIELDS[record['kind']]:
        if data[field] is None and not data.get('unknown_reason'):
            raise ValueError(f'Unknown {record["kind"]} {field} requires unknown_reason')
    for asset in record['assets']:
        if asset['uri'] != 'qecasset:sha256:' + asset['sha256'] or asset['path'] != 'assets/' + asset['sha256']:
            raise ValueError('Managed asset URI/path must bind its exact byte hash')
    if record['kind'] == 'claim':
        for field in ('statement', 'hypotheses', 'quantifiers'):
            if data[field] is None and not data.get('unknown_reason'):
                raise ValueError(f'Unknown claim {field} requires unknown_reason')
    if record['kind'] == 'code_instance':
        parameters = data['parameters']
        n, k = parameters['n'], parameters['k']
        if n is not None and k is not None and k > n:
            raise ValueError('Code dimension k cannot exceed n')
        if any(x is None for x in (n, k)) and not data.get('unknown_reason'):
            raise ValueError('Unknown code parameter requires unknown_reason')
    if record['review']['status'] == 'reviewed' and not record['review'].get('review_id'):
        raise ValueError('Reviewed status requires an independently bound review record')


def validate_endpoint(source_kind, target_kind, relation):
    from ..graph import KNOWN_RELATIONS
    if relation.startswith('catalog:'):
        return  # Legacy semantics are retained, never upgraded to typed proof edges.
    if relation not in KNOWN_RELATIONS | {'normalizes_to'}:
        raise ValueError(f'Unknown typed relation: {relation}')
    if relation in ENDPOINTS:
        sources, targets = ENDPOINTS[relation]
        if source_kind not in sources or target_kind not in targets:
            raise ValueError(f'Invalid {relation} endpoint types: {source_kind} -> {target_kind}')


def validate_graph_types(graph):
    lookup = {node['id']: node for node in graph['nodes']}
    for edge in graph['edges']:
        if edge['source'] not in lookup or edge['target'] not in lookup:
            raise ValueError(f"Dangling edge {edge['id']}")
        validate_endpoint(lookup[edge['source']]['kind'], lookup[edge['target']]['kind'], edge['relation'])


def registry_issues(registry, state, fixed):
    issues = []
    records = {identifier: registry.record(identifier, registry_revision=fixed) for identifier in state['records']}
    for identifier, record in records.items():
        if record['schema_version'] != 'qecgraph.record.v3':
            issues.append({'code': 'legacy_record_requires_migration', 'record_id': identifier})
            continue
        for asset in record['assets']:
            try:
                raw = registry.asset_bytes(asset['uri'])
                if len(raw) != asset['size_bytes'] or hashlib.sha256(raw).hexdigest() != asset['sha256']:
                    raise ValueError('Asset size/hash mismatch')
            except (OSError, ValueError) as exc:
                issues.append({'code': 'asset_unavailable', 'record_id': identifier, 'asset': asset['uri'], 'message': str(exc)})
        for ref in record['refs']:
            target = records.get(ref['target'])
            if target is None:
                issues.append({'code': 'unresolved_reference', 'record_id': identifier, 'target': ref['target']})
                continue
            try:
                validate_endpoint(record['kind'], target['kind'], ref['relation'])
                if ref.get('revision') and ref['revision'] != target['revision']:
                    raise ValueError('Reference binds a historical revision, not the selected current revision')
            except ValueError as exc:
                issues.append({'code': 'reference_type_or_revision', 'record_id': identifier, 'target': ref['target'], 'message': str(exc)})
    return issues
