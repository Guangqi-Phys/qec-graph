"""Structural/type validation. Passing these checks is not mathematical evidence."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from ..core.graph import KNOWN_RELATIONS


@lru_cache
def _packaged_schema(name):
    return json.loads(files(__package__).joinpath('schemas/' + name + '.schema.json').read_text(encoding='utf-8'))


STATEMENTS = {'lemma', 'theorem', 'proposition', 'corollary', 'conjecture', 'claim', 'statement_other'}
MATHEMATICS = STATEMENTS | {'definition', 'assumption', 'notation', 'proof', 'equation'}
DOMAIN_FIELDS = {entry['if']['properties']['kind']['const']: entry['then']['properties']['data']['required']
                 for entry in _packaged_schema('record')['allOf'] if 'data' not in entry['if']['properties']}
ENDPOINTS = {
    'cites_paper': ({'bib_entry'}, {'document'}),
    'proof_of': ({'proof'}, STATEMENTS),
    'proof_of_candidate': ({'proof'}, STATEMENTS),
    'depends_on_declared': (MATHEMATICS, MATHEMATICS),
    'depends_on_candidate': (MATHEMATICS, MATHEMATICS),
    'depends_on_reviewed': (MATHEMATICS, MATHEMATICS),
    'formalizes': ({'lean_declaration', 'formalization'}, MATHEMATICS),
    'supports': ({'evidence'}, {'claim'}),
    'contradicts': ({'evidence', 'claim'}, {'claim'}),
    'has_matrix': ({'quantum_code', 'check_matrix', 'classical_code'}, {'matrix', 'asset'}),
    'has_check_matrix': ({'quantum_code'}, {'check_matrix'}),
    'uses_circuit': ({'experiment', 'circuit', 'quantum_code', 'check_matrix'}, {'circuit'}),
    'uses_noise': ({'experiment', 'circuit'}, {'noise'}),
    'uses_decoder': ({'experiment'}, {'decoder'}),
    'normalizes_to': (MATHEMATICS | {'paragraph', 'table', 'remark'}, {'claim'}),
    'maps_declaration': ({'formalization'}, {'lean_declaration'}),
    'maps_source_occurrence': ({'formalization'}, MATHEMATICS | {'paragraph', 'remark'}),
    'has_build_evidence': ({'formalization', 'lean_declaration'}, {'evidence'}),
    'lean_type_depends_on': ({'lean_declaration'}, {'lean_declaration'}),
    'lean_proof_depends_on': ({'lean_declaration'}, {'lean_declaration'}),
    'lean_type_depends_on_transitive': ({'lean_declaration'}, {'lean_declaration'}),
    'lean_proof_depends_on_transitive': ({'lean_declaration'}, {'lean_declaration'}),
}

@lru_cache
def packaged_validator(name, *, check_formats=True):
    return Draft202012Validator(_packaged_schema(name), format_checker=FormatChecker() if check_formats else None)


def validate_record(record):
    errors = sorted(packaged_validator('record', check_formats=False).iter_errors(record), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise ValueError('Record schema at ' + '/'.join(map(str, error.path)) + ': ' + error.message)
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
    if record['kind'] == 'quantum_code':
        parameters = data['parameters']
        n, k = parameters['n'], parameters['k']
        if n is not None and k is not None and k > n:
            raise ValueError('Code dimension k cannot exceed n')
        if any(x is None for x in (n, k)) and not data.get('unknown_reason'):
            raise ValueError('Unknown code parameter requires unknown_reason')
    if record['review']['status'] == 'reviewed' and not record['review'].get('review_id'):
        raise ValueError('Reviewed status requires an independently bound review record')


def validate_endpoint(source_kind, target_kind, relation):
    if relation.startswith('catalog:'):
        return  # Legacy semantics are retained, never upgraded to typed proof edges.
    endpoints = ENDPOINTS.get(relation)
    if endpoints is not None:
        sources, targets = endpoints
        if source_kind not in sources or target_kind not in targets:
            raise ValueError(f'Invalid {relation} endpoint types: {source_kind} -> {target_kind}')
    elif relation not in KNOWN_RELATIONS:
        raise ValueError(f'Unknown typed relation: {relation}')


def validate_graph_types(graph):
    lookup = {node['id']: node for node in graph['nodes']}
    for edge in graph['edges']:
        source, target = lookup.get(edge['source']), lookup.get(edge['target'])
        if source is None or target is None:
            raise ValueError(f"Dangling edge {edge['id']}")
        source_kind, target_kind = source['kind'], target['kind']
        relation = edge['relation']
        if edge['status'] == 'unresolved' and (source_kind == 'unresolved_reference' or target_kind == 'unresolved_reference'):
            if relation in KNOWN_RELATIONS or relation.startswith('catalog:'):
                continue  # Explicit unknown endpoint, never a usable typed dependency.
        validate_endpoint(source_kind, target_kind, relation)


def registry_issues(registry, records):
    issues = []
    for identifier, record in records.items():
        if record['schema'] != 'qecgraph.record':
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
            'quantum_code': {'construction_id': {'construction'}, 'check_matrix_ids': {'check_matrix'}, 'distance_estimate_ids': {'claim'}},
            'check_matrix': {'instance_id': {'quantum_code'}, 'matrix_definition_id': {'definition'}},
            'formalization': {'claim_id': {'claim'}},
            'claim': {'subject_id': {'quantum_code', 'check_matrix', 'circuit', 'family', 'construction',
                                      'classical_code'},
                      'check_matrix_id': {'check_matrix'}, 'metric_id': {'definition', 'metric'}},
        }.get(record['kind'], {})
        for field, kinds in fields.items():
            values = record['data'].get(field)
            if values is None:
                continue
            for target_id in values if isinstance(values, list) else [values]:
                target = records.get(target_id)
                if target is None:
                    issues.append({'code': 'domain_reference', 'record_id': identifier, 'field': field,
                                   'target': target_id})
                elif target['kind'] not in kinds:
                    issues.append({'code': 'domain_reference', 'severity': 'warning', 'record_id': identifier,
                                   'field': field, 'target': target_id, 'target_kind': target['kind']})
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
