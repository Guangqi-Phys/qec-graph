"""RFC-QEC-002 linked research records; validation is not evidence promotion."""
from __future__ import annotations

import copy
import re

from .graph import canonical, hash_text
from .validators import packaged_validator

SCHEMA = 'qecgraph.research.v1'
# The packaged schema owns the portable record structure. Reference target
# kinds also drive the runtime join and the published graph views.
_VALIDATOR = packaged_validator('research.v1')
_CONTRACTS = _VALIDATOR.schema['$defs']['record_data']['$defs']
KINDS = frozenset(_VALIDATOR.schema['properties']['kind']['enum'])
UNKNOWN = frozenset(_VALIDATOR.schema['properties']['field_evidence']['additionalProperties']
                    ['properties']['status']['enum']) - {'known'}
REQUIRED = {kind: tuple(contract['required']) for kind, contract in _CONTRACTS.items()
            if 'required' in contract}
RELATIONS = {kind: {field: tuple(rule['x-qec-target-kinds']) for field, rule in contract['properties'].items()
                    if 'x-qec-target-kinds' in rule}
             for kind, contract in _CONTRACTS.items() if 'properties' in contract}
ASSET_URI_PATTERN = _VALIDATOR.schema['$defs']['managed_asset']['pattern']
ASSET_FIELDS = {kind: {field: rule['x-qec-managed-asset'] == 'multiple'
                       for field, rule in contract.get('properties', {}).items() if 'x-qec-managed-asset' in rule}
                for kind, contract in _CONTRACTS.items()}


def key(ref):
    if not isinstance(ref, dict) or set(ref) != {'id', 'revision'} or not all(
            isinstance(x, str) and x.strip() for x in ref.values()):
        raise ValueError('Expected a specific {id, revision} reference')
    return ref['id'], ref['revision']


def ref(record):
    return {'id': record['id'], 'revision': record['revision']}


def pointer_value(record, pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/data/') or re.search(r'~(?![01])', pointer):
        raise ValueError('Field evidence needs an RFC 6901 pointer into /data')
    value = record
    for part in pointer[1:].split('/'):
        name = part.replace('~1', '/').replace('~0', '~')
        try:
            if isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', name):
                value = value[int(name)]
            elif isinstance(value, dict):
                value = value[name]
            else:
                raise KeyError(name)
        except (KeyError, IndexError) as exc:
            raise ValueError(f'Field evidence pointer does not resolve: {pointer}') from exc
    return value


def _ptr(name):
    return '/data/' + name.replace('~', '~0').replace('/', '~1')


def prepare(record):
    record = copy.deepcopy(record)
    error = next(_VALIDATOR.iter_errors(record), None)
    if error:
        raise ValueError(f'Research record schema at {error.json_path}: {error.message}')
    key(ref(record))
    data, kind = record['data'], record['kind']
    fields = record['field_evidence']
    for field in data:
        path = _ptr(field)
        if path not in fields:
            raise ValueError(f'Missing field-level evidence for {path}')
    for path, evidence in fields.items():
        value = pointer_value(record, path)
        state = evidence['status']
        if state == 'known' and value is None:
            raise ValueError(f'Known value cannot be null: {path}')
        if state in UNKNOWN and value is not None:
            raise ValueError(f'Unknown value must be null: {path}')
    if kind in {'code_instance', 'classical_seed'}:
        for field in ('n_data', 'k_logical', 'K', 'r_gauge'):
            value = data.get(field)
            if value is not None and type(value) is not int:
                raise ValueError(f'Invalid code parameter {field}')
        if data.get('n_data') is not None and data.get('k_logical') is not None and data['k_logical'] > data['n_data']:
            raise ValueError('k cannot exceed n')
    if kind == 'distance_claim':
        lower, upper, relation = (data[f] for f in ('lower_bound', 'upper_bound', 'relation'))
        for value in (lower, upper):
            if value is not None and type(value) is not int:
                raise ValueError('Distance bounds must be positive integers or null')
        if relation == 'exact' and lower != upper or relation == 'interval' and lower > upper:
            raise ValueError('Distance bound direction and values disagree')
    if kind == 'performance_point':
        if not record['is_synthetic']:
            for field in ('value', 'shots', 'failures', 'discards', 'confidence_interval'):
                if data.get(field) is not None and not fields.get(_ptr(field), {}).get('source_locator'):
                    raise ValueError(f'Reported performance {field} needs an exact source locator')
        count_fields = ('shots', 'failures', 'discards')
        shots, failures, discards = (data.get(field) for field in count_fields)
        if any(v is not None and type(v) is not int for v in (shots, failures, discards)):
            raise ValueError('Observation counts must be nonnegative integers or null')
        if shots is not None and (failures or 0) + (discards or 0) > shots:
            raise ValueError('Failures plus discards exceed shots')
    if kind == 'software_release' and not data['version']:
        raise ValueError('A software release needs the exact distribution and version')
    if kind == 'execution_run' and not data['execution_evidence']:
        raise ValueError('An execution run requires actual execution evidence and environment')
    if kind == 'software_usage':
        use = data['usage_kind']
        if use == 'source_reported_use' and not (data.get('source_ref') and data.get('experiment_ref')):
            raise ValueError('Reported use requires an exact source and experiment')
        if use == 'locally_observed_use' and not data.get('execution_run_ref'):
            raise ValueError('Observed use requires a real execution run')
        if use in ('mention', 'citation') and (data.get('experiment_ref') or data.get('execution_run_ref')):
            raise ValueError('Mentions/citations do not establish use by an experiment')
    from .validators.research import validate_details
    validate_details(record)
    canonical(record)  # Reject non-serializable values; readers also use strict JSON.
    return record


def validate_bundle(records):
    lookup = {}
    for raw in records:
        record = prepare(raw)
        identity = key(ref(record))
        if identity in lookup:
            raise ValueError(f'Duplicate research record revision: {identity}')
        lookup[identity] = record

    def resolve(owner, binding, kinds):
        target = lookup.get(key(binding))
        if target is None or target['kind'] not in kinds:
            raise ValueError(f'Unresolved or wrong-type {binding} from {owner["id"]}; expected {kinds}')
        if target['is_synthetic'] != owner['is_synthetic']:
            raise ValueError('Synthetic and research revisions cannot be joined')
        return target['data']

    for record in lookup.values():
        data = record['data']
        for evidence in record['field_evidence'].values():
            if evidence.get('source_ref'):
                resolve(record, evidence['source_ref'], ('paper_version', 'catalog_source'))
        for field, kinds in RELATIONS.get(record['kind'], {}).items():
            value = data.get(field)
            if value is not None:
                for binding in value if field.endswith('_refs') else [value]:
                    resolve(record, binding, kinds)
        if record['kind'] == 'construction' and isinstance(data.get('matrix_recipe'), dict):
            for binding in data['matrix_recipe'].get('seed_refs') or []:
                resolve(record, binding, ('classical_seed',))
        if record['kind'] == 'code_presentation' and data.get('reconstruction_status') in ('complete', 'reconstructable'):
            if not data.get('generator_asset_refs') and resolve(
                    record, data['construction_recipe_ref'], ('construction',)).get('reconstruction_status') not in (
                        'complete', 'reconstructable'):
                raise ValueError('Presentation cites an incomplete matrix recipe')
        if record['kind'] == 'software_usage' and data.get('release_ref'):
            release = resolve(record, data['release_ref'], ('software_release',))
            distribution = resolve(record, release['distribution_ref'], ('software_distribution',))
            if not data.get('project_ref') or distribution['project_ref'] != data['project_ref']:
                raise ValueError('Software use release belongs to a different project')
        if record['kind'] == 'software_usage' and data.get('experiment_ref'):
            experiment = resolve(record, data['experiment_ref'], ('reported_experiment',))
            if data.get('source_ref') != experiment.get('source_ref'):
                raise ValueError('Software use and experiment are bound to different sources')
        if record['kind'] == 'reported_experiment':
            chain = [('presentation_ref', 'code_ref', 'code_ref', 'code_presentation'),
                     ('circuit_ref', 'presentation_ref', 'presentation_ref', 'circuit_protocol')]
            for outer, inner, expected, kind in chain:
                if data.get(outer):
                    actual = resolve(record, data[outer], (kind,)).get(inner)
                    if actual is not None and data.get(expected) is not None and actual != data[expected]:
                        raise ValueError(f'Experiment crosses incompatible {outer}/{expected} revisions')
            for usage in data.get('software_usage_refs') or []:
                use = resolve(record, usage, ('software_usage',))
                if use['usage_kind'] != 'source_reported_use' or use.get('experiment_ref') != ref(record):
                    raise ValueError('Reported experiment requires its own source-reported use')
        if record['kind'] == 'performance_point' and data.get('experiment_ref'):
            exp = resolve(record, data['experiment_ref'], ('reported_experiment',))
            if data.get('noise_instantiation_ref'):
                point_noise = resolve(record, data['noise_instantiation_ref'], ('noise_instantiation',))
                for point_key, exp_key in [('model_ref', 'noise_model_ref'), ('circuit_ref', 'circuit_ref')]:
                    if point_noise.get(point_key) and exp.get(exp_key) and point_noise[point_key] != exp[exp_key]:
                        raise ValueError('Performance point crosses experiment noise or circuit revisions')
            if data.get('curve_ref'):
                curve = resolve(record, data['curve_ref'], ('performance_series',))
                if curve.get('experiment_ref') != data['experiment_ref'] or curve.get('metric_definition_ref') != data['metric_definition_ref']:
                    raise ValueError('Performance point does not belong to the given curve')
    return lookup


def make_record(kind, identifier, revision, data, *, source=None, method, synthetic=False, evidence=None):
    fields = {_ptr(field): ({'status': 'not_extracted'} if value is None else
                           {'status': 'known', 'source_ref': source, 'method': method})
              for field, value in data.items()}
    fields.update(evidence or {})
    return prepare({'schema_version': SCHEMA, 'kind': kind, 'id': identifier, 'revision': revision,
                    'data': data, 'field_evidence': fields, 'is_synthetic': synthetic})


def adapt_synthetic(payload):
    if payload.get('fixture_schema') != 'qecgraph.rfc002.linked-example' or payload.get('is_synthetic') is not True:
        raise ValueError('Expected the marked RFC-002 linked fixture')
    source, = [ref(r) for r in payload['records'] if r['kind'] == 'paper_version']
    records = []
    for item in payload['records']:
        if item.get('is_synthetic') is not True or item.get('exclude_from_default_queries') is not True:
            raise ValueError('Synthetic record flags are missing')
        data = dict(item['data'])
        if item['kind'] == 'paper_version':
            data['source_text'] = payload['source_text']
        if item['kind'] == 'noise_model':
            for field in ('idle', 'loss', 'erasure', 'leakage'):
                if isinstance(data.get(field), dict) and data[field].get('consideration') == 'unknown':
                    data[field] = None
        records.append(make_record(item['kind'], item['id'], item['revision'], data, source=source,
                                   method='synthetic_fixture', synthetic=True, evidence=item.get('field_evidence')))
    validate_bundle(records)
    return records


def pauli_weight(x_bits, z_bits):
    if len(x_bits) != len(z_bits) or any(type(b) is not int or b not in (0, 1) for b in (*x_bits, *z_bits)):
        raise ValueError('Expected equally sized binary X/Z halves')
    return sum(bool(x or z) for x, z in zip(x_bits, z_bits))


def record_fingerprint(records):
    return hash_text(canonical(sorted(records, key=lambda r: key(ref(r)))))
