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
                 for entry in _SCHEMA['allOf'] if 'data' not in entry['if']['properties']}
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
        if 'evidence_ids' in data:
            raise ValueError('evidence_ids belongs in the authoritative record envelope, not data')
        for field in ('statement', 'hypotheses', 'quantifiers'):
            if data[field] is None and not data.get('unknown_reason'):
                raise ValueError(f'Unknown claim {field} requires unknown_reason')
        if data.get('relation') in {'exact', 'lower_bound', 'upper_bound', 'interval'}:
            from .qec import distance_issues
            errors = [message for message in distance_issues(data)
                      if not message.startswith(('Distance claim missing', 'Distance sector'))]
            if errors:
                raise ValueError('; '.join(errors))
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


def registry_issues(registry, state, fixed, records=None):
    issues = []
    if records is None:
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
        if record['kind'] == 'claim' and record['data'].get('relation') in {'exact', 'lower_bound', 'upper_bound', 'interval'}:
            from .qec import distance_issues
            issues.extend({'code': 'distance_scope_incomplete', 'severity': 'warning', 'record_id': identifier, 'message': message}
                          for message in distance_issues(record['data']))
        for evidence_id in record['evidence_ids']:
            if evidence_id not in records or records[evidence_id]['kind'] != 'evidence':
                issues.append({'code': 'unresolved_evidence', 'record_id': identifier, 'evidence_id': evidence_id})
        fields = {
            'code_instance': {'construction_id': {'construction'}, 'presentation_ids': {'presentation'}, 'distance_claim_ids': {'claim'}},
            'presentation': {'instance_id': {'code_instance'}, 'matrix_definition_id': {'definition'}},
            'formalization': {'claim_id': {'claim'}},
            'claim': {'presentation_id': {'presentation'}, 'metric_definition_id': {'definition', 'metric'}},
        }.get(record['kind'], {})
        for field, kinds in fields.items():
            values = record['data'].get(field)
            if values is None:
                continue
            for target_id in values if isinstance(values, list) else [values]:
                if target_id not in records or records[target_id]['kind'] not in kinds:
                    issues.append({'code': 'domain_reference', 'record_id': identifier, 'field': field, 'target': target_id})
        if record['kind'] == 'evidence' and isinstance(record['data'].get('inputs'), list):
            for binding in record['data']['inputs']:
                if not isinstance(binding, dict):
                    issues.append({'code': 'evidence_binding', 'record_id': identifier, 'message': 'Input binding must be an object'})
                    continue
                target = records.get(binding.get('id'))
                if target is None or target['revision'] != binding.get('revision') or target['content_sha256'] != binding.get('content_sha256'):
                    issues.append({'code': 'evidence_binding_stale', 'severity': 'warning', 'record_id': identifier, 'binding': binding})
        for ref in record['refs']:
            target = records.get(ref['target'])
            if target is None:
                issues.append({'code': 'unresolved_reference', 'record_id': identifier, 'target': ref['target']})
                continue
            try:
                validate_endpoint(record['kind'], target['kind'], ref['relation'])
            except ValueError as exc:
                issues.append({'code': 'reference_type_or_revision', 'record_id': identifier, 'target': ref['target'], 'message': str(exc)})
            if ref.get('revision') and ref['revision'] != target['revision']:
                issues.append({'code': 'reference_revision_stale', 'severity': 'warning', 'record_id': identifier, 'target': ref['target']})
    return issues
