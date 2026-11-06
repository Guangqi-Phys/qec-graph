"""Independent, revisioned domain identities; never mutate parser blocks."""
from __future__ import annotations

import copy

from .graph import canonical, hash_text

RECORD_SCHEMA = 'qecgraph.record.v2'
HASH_PROTOCOL = 'sha256:json-sort-utf8-v1:record-excluding-content_sha256'
KINDS = {'source_work', 'source_version', 'definition', 'claim', 'family', 'construction',
         'classical_seed', 'code_instance', 'presentation', 'implementation', 'evidence',
         'formalization', 'circuit', 'noise', 'decoder', 'experiment', 'metric', 'asset'}


def record_hash(record):
    return hash_text(canonical({k: v for k, v in record.items() if k != 'content_sha256'}))


def prepare_record(record):
    record = copy.deepcopy(record)
    if record.get('schema_version') != RECORD_SCHEMA:
        raise ValueError('Expected qecgraph.record.v2; use explicit migration for older formats')
    for field in ('id', 'revision', 'title'):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError(f'Record needs nonempty {field}')
    if record.get('kind') not in KINDS:
        raise ValueError('Unknown domain record kind')
    if not isinstance(record.get('data'), dict):
        raise ValueError('Record data must be an object')
    for field in ('aliases', 'refs', 'assets', 'evidence_ids'):
        record.setdefault(field, [])
    record.setdefault('provenance', {})
    record.setdefault('review', {'status': 'proposed'})
    record.setdefault('extensions', {})
    record.setdefault('hash_protocol', HASH_PROTOCOL)
    if record['hash_protocol'] != HASH_PROTOCOL:
        raise ValueError('Unsupported record hash protocol')
    expected = record_hash(record)
    if record.get('content_sha256', expected) != expected:
        raise ValueError('Record content hash mismatch')
    record['content_sha256'] = expected
    return record
