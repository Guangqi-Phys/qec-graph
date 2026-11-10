"""Explicit, lossless boundary adapters; never rewrite legacy inputs or hashes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .core.graph import hash_text, read_json
from .domain.records import RECORD_SCHEMA, prepare_record
from .store import safe_relative
from .core.transactions import atomic_json, immutable_json
from .validators import DOMAIN_FIELDS


def _distance_unknowns(data):
    if data.get('relation') in {'exact', 'lower_bound', 'upper_bound', 'interval'}:
        for field in ('subject_id', 'presentation_id', 'metric_definition_id', 'sector', 'method', 'assumptions', 'lower_bound', 'upper_bound'):
            data.setdefault(field, None)
        data.setdefault('unknown_reason', 'Legacy distance scope is not fully specified')


def _copy_asset(source_root, out, asset):
    if source_root is None:
        raise ValueError('Legacy assets require explicit --source-root')
    source = safe_relative(Path(source_root).resolve(), asset['path'])
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != asset['sha256']:
        raise ValueError(f"Asset bytes do not match legacy hash: {asset['path']}")
    legacy_canonical = asset.get('canonical_sha256')
    if legacy_canonical:
        payload = json.dumps(read_json(source), sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        if hash_text(payload) != legacy_canonical:
            raise ValueError('Legacy ensure_ascii=True canonical asset hash mismatch')
    path = out / 'assets' / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError('Managed asset hash collision')
    path.write_bytes(raw)
    binding = {'asset_id': 'asset:sha256:' + digest, 'uri': 'qecasset:sha256:' + digest,
               'path': 'assets/' + digest, 'sha256': digest, 'size_bytes': len(raw),
               'media_type': asset.get('media_type', 'application/octet-stream'), 'original_path': asset['path']}
    if legacy_canonical:
        binding['legacy_canonical_sha256'] = legacy_canonical
        binding['legacy_hash_protocol'] = 'sha256:json-sort-ascii-v1'
    return binding


def adapt_legacy_record(record, source_digest, *, source_root=None, out):
    if record.get('schema_version') != '0.1.0':
        raise ValueError('Unsupported legacy record version')
    assets = [_copy_asset(source_root, out, asset) for asset in record.get('assets', [])]
    path_map = {asset['original_path']: asset['uri'] for asset in assets}

    def managed(value):
        if isinstance(value, dict):
            return {k: managed(v) for k, v in value.items()}
        if isinstance(value, list):
            return [managed(v) for v in value]
        return path_map.get(value, value) if isinstance(value, str) else value

    data = managed(record['data'])
    # Missing legacy fields remain explicitly unknown, never guessed from names.
    missing = [field for field in DOMAIN_FIELDS[record['kind']] if field not in data]
    for field in missing:
        data[field] = None
    unspecified = [field for field in DOMAIN_FIELDS[record['kind']] if data[field] is None]
    if unspecified:
        data.setdefault('unknown_reason', 'Legacy input does not specify: ' + ', '.join(unspecified))
    if record['kind'] == 'claim':
        if data['statement'] is None:
            data['statement'] = data.get('statement_latex')
        data.setdefault('hypotheses', None)
        data.setdefault('quantifiers', None)
        data.setdefault('unknown_reason', 'Legacy record does not explicitly enumerate all quantifiers')
        data.pop('evidence_ids', None)  # v3 stores this once, in the record envelope.
        _distance_unknowns(data)
    adapted = {'schema_version': RECORD_SCHEMA, 'id': record['id'], 'kind': record['kind'],
               'revision': 'legacy-0.1.0-' + source_digest, 'title': record.get('title', record['id']),
               'data': data, 'assets': assets,
               'refs': [{'relation': 'catalog:' + ref['relation'], 'target': ref['target_id'], 'status': 'declared'}
                        for ref in record.get('refs', [])],
               'evidence_ids': record.get('data', {}).get('evidence_ids', []),
               'provenance': {'method': 'legacy_adapter_v1', 'input_schema': '0.1.0',
                              'original_bytes_sha256': source_digest, 'mathematical_recheck': 'not_performed'},
               'review': {'status': 'imported'}, 'extensions': {'legacy_record': record}}
    return prepare_record(adapted)


def migrate(source, out, *, source_root=None):
    source, out = Path(source).resolve(), Path(out).resolve()
    if source == out or (source.is_dir() and out.is_relative_to(source)):
        raise ValueError('Migration output must be separate from original inputs')
    if out.exists() and any(out.iterdir()):
        raise ValueError('Migration output must be new or empty')
    out.mkdir(parents=True, exist_ok=True)
    report = {'schema_version': 'qecgraph.migration.v1', 'adapter_version': '1',
              'source': str(source), 'accepted': [], 'rejected': [], 'id_map': {},
              'semantic_changes': ['Explicit v3 envelope; legacy relations retain catalog: prefix',
                                   'External paths become managed content-addressed asset URIs',
                                   'No human review, numerical recheck or Lean status promotion']}
    paths = sorted(source.rglob('*.json')) if source.is_dir() else [source]
    for path in paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        original = out / 'originals' / (digest + '.json')
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(raw)
        item = {'input': str(path), 'input_bytes_sha256': digest, 'original_path': str(original.relative_to(out))}
        try:
            value = read_json(path)
            schema = value.get('schema_version')
            item['input_schema'] = schema
            if schema == '0.1.0':
                record = adapt_legacy_record(value, digest, source_root=source_root, out=out)
                relative = 'records/' + hash_text(record['id']) + '.json'
                immutable_json(out / relative, record)
                item.update({'output_path': relative, 'output_schema': RECORD_SCHEMA, 'id': record['id']})
                if record['id'] in report['id_map']:
                    raise ValueError('Duplicate legacy ID in migration input')
                report['id_map'][record['id']] = {'id': record['id'], 'revision': record['revision'],
                                                'content_sha256': record['content_sha256']}
            elif schema == 'qecgraph.record.v2':
                old = prepare_record(value, allow_legacy=True)
                record = dict(old)
                record['schema_version'] = RECORD_SCHEMA
                record['revision'] = 'strict-v3-' + digest
                record.pop('content_sha256', None)
                record['extensions'] = {**record['extensions'], 'pre_validation_record': old}
                record['review'] = {'status': 'imported'}
                record['assets'] = [_copy_asset(source_root, out, asset) for asset in old['assets']]
                record['data'] = dict(record['data'])
                nested_evidence = record['data'].pop('evidence_ids', None)
                if nested_evidence is not None:
                    if record['evidence_ids'] and record['evidence_ids'] != nested_evidence:
                        raise ValueError('Conflicting legacy evidence_ids owners require explicit resolution')
                    record['evidence_ids'] = nested_evidence
                for field in DOMAIN_FIELDS[record['kind']]:
                    record['data'].setdefault(field, None)
                record['data'].setdefault('unknown_reason', 'Explicit v2 to v3 migration; unspecified fields remain unknown')
                if record['kind'] == 'claim':
                    _distance_unknowns(record['data'])
                record = prepare_record(record)
                relative = 'records/' + hash_text(record['id']) + '.json'
                immutable_json(out / relative, record)
                item.update({'output_path': relative, 'output_schema': RECORD_SCHEMA, 'id': record['id']})
                report['id_map'][record['id']] = {'id': record['id'], 'revision': record['revision'],
                                                'content_sha256': record['content_sha256']}
            elif schema in {'qecgraph.graph.v1', 'qecgraph.annotations.v1'}:
                # A syntactic source block remains a source block. All fields,
                # including unknown extensions and evidence, remain verbatim.
                relative = 'passthrough/' + digest + '.json'
                destination = out / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
                item.update({'output_path': relative, 'output_schema': schema, 'mode': 'lossless_passthrough'})
                for node in value.get('nodes', []):
                    report['id_map'][node['id']] = {'id': node['id'], 'mode': 'unchanged_source_or_sidecar'}
            else:
                raise ValueError(f'Unknown schema {schema!r}; kept opaque, not interpreted')
            report['accepted'].append(item)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report['rejected'].append({**item, 'reason': str(exc)})
    report['status'] = 'passed' if not report['rejected'] else 'partial'
    report['suggested_exit_code'] = 0 if not report['rejected'] else 2
    atomic_json(out / 'migration-report.json', report)
    return report
