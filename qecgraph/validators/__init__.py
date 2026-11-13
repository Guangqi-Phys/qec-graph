"""Structural/type validation. Passing these checks is not mathematical evidence."""
from __future__ import annotations

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
ENDPOINTS = {
    'cites_paper': ({'bib_entry'}, {'document'}),
    'proof_of': ({'proof'}, STATEMENTS),
    'proof_of_candidate': ({'proof'}, STATEMENTS),
    'depends_on_declared': (MATHEMATICS, MATHEMATICS),
    'depends_on_candidate': (MATHEMATICS, MATHEMATICS),
    'depends_on_reviewed': (MATHEMATICS, MATHEMATICS),
    'supports': ({'evidence'}, {'claim'}),
    'contradicts': ({'evidence', 'claim'}, {'claim'}),
    'has_matrix': ({'quantum_code', 'check_matrix', 'classical_code'}, {'matrix', 'asset'}),
    'has_check_matrix': ({'quantum_code'}, {'check_matrix'}),
    'uses_circuit': ({'experiment', 'circuit', 'quantum_code', 'check_matrix'}, {'circuit'}),
    'uses_noise': ({'experiment', 'circuit'}, {'noise'}),
    'uses_decoder': ({'experiment'}, {'decoder'}),
    'normalizes_to': (MATHEMATICS | {'paragraph', 'table', 'remark'}, {'claim'}),
}

@lru_cache
def packaged_validator(name, *, check_formats=True):
    return Draft202012Validator(_packaged_schema(name), format_checker=FormatChecker() if check_formats else None)


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
