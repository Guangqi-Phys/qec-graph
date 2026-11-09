"""RFC-QEC-002 linked research records; validation is not evidence promotion."""
from __future__ import annotations

import copy
import re

from .graph import canonical, hash_text

SCHEMA = 'qecgraph.research.v1'
UNKNOWN = {'not_extracted', 'unresolved', 'not_reported', 'not_applicable', 'conflicting'}
# Each field has its own role. A null binding is unknown, never a wildcard join.
RELATIONS = {
    'code_mention': {'source_ref': 'paper_version', 'code_ref': 'code_instance'},
    'construction': {'seed_refs': 'classical_seed'},
    'code_instance': {'construction_ref': 'construction', 'presentation_refs': 'code_presentation',
                      'distance_claim_refs': 'distance_claim'},
    'code_presentation': {'code_ref': 'code_instance', 'construction_recipe_ref': 'construction'},
    'distance_claim': {'subject_ref': ('code_instance', 'code_presentation', 'circuit_protocol'),
                       'metric_definition_ref': 'metric_definition'},
    'circuit_protocol': {'presentation_ref': 'code_presentation'},
    'noise_instantiation': {'model_ref': 'noise_model', 'circuit_ref': 'circuit_protocol'},
    'decoder_configuration': {'algorithm_ref': 'algorithm', 'software_usage_refs': 'software_usage'},
    'reported_experiment': {'source_ref': 'paper_version', 'code_ref': 'code_instance',
                            'presentation_ref': 'code_presentation', 'circuit_ref': 'circuit_protocol',
                            'noise_model_ref': 'noise_model', 'decoder_ref': 'decoder_configuration',
                            'hardware_ref': 'hardware_assumptions', 'software_usage_refs': 'software_usage',
                            'execution_run_refs': 'execution_run'},
    'performance_series': {'experiment_ref': 'reported_experiment', 'metric_definition_ref': 'metric_definition'},
    'performance_point': {'experiment_ref': 'reported_experiment', 'noise_instantiation_ref': 'noise_instantiation',
                          'metric_definition_ref': 'metric_definition', 'curve_ref': 'performance_series'},
    'execution_run': {'reported_experiment_ref': 'reported_experiment', 'environment_ref': 'execution_environment',
                      'software_usage_refs': 'software_usage'},
    'software_distribution': {'project_ref': 'software_project'},
    'software_release': {'distribution_ref': 'software_distribution'},
    'software_usage': {'project_ref': 'software_project', 'release_ref': 'software_release',
                       'source_ref': 'paper_version', 'experiment_ref': 'reported_experiment',
                       'execution_run_ref': 'execution_run'},
}
KINDS = set(RELATIONS) | {'paper_version', 'classical_seed', 'code_family', 'noise_model',
                         'metric_definition', 'hardware_assumptions', 'execution_environment',
                         'software_project', 'algorithm', 'catalog_source'}
REQUIRED = {
    'code_instance': ('coding_domain', 'n_data', 'k_logical'),
    'code_presentation': ('code_ref', 'check_weight_metrics'),
    'distance_claim': ('subject_ref', 'metric_definition_ref', 'relation', 'lower_bound', 'upper_bound'),
    'noise_model': ('idle', 'loss', 'erasure', 'leakage'),
    'noise_instantiation': ('model_ref', 'reported_coordinates', 'resolved_channel_parameters'),
    'reported_experiment': ('source_ref', 'code_ref', 'presentation_ref', 'circuit_ref', 'noise_model_ref', 'decoder_ref'),
    'performance_point': ('experiment_ref', 'noise_instantiation_ref', 'metric_definition_ref', 'value'),
    'software_usage': ('usage_kind', 'project_ref', 'release_ref'),
    'software_distribution': ('project_ref', 'ecosystem', 'name'),
    'software_release': ('distribution_ref', 'version'),
    'execution_run': ('environment_ref', 'execution_evidence'),
}


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
    from .validators import packaged_validator
    record = copy.deepcopy(record)
    error = next(packaged_validator('research.v1').iter_errors(record), None)
    if error:
        raise ValueError(f'Research record schema at {error.json_path}: {error.message}')
    key(ref(record))
    data, kind = record['data'], record['kind']
    if kind not in KINDS or set(REQUIRED.get(kind, ())) - data.keys():
        raise ValueError(f'Unknown kind or missing required explicit fields: {kind}')
    fields = record['field_evidence']
    for field in data:
        path = _ptr(field)
        if path not in fields:
            raise ValueError(f'Missing field-level evidence for {path}')
    for path, evidence in fields.items():
        value = pointer_value(record, path)
        state = evidence['status']
        if state == 'known' and (value is None or not evidence.get('source_ref') or not evidence.get('method')):
            raise ValueError(f'Known value needs a source revision and method: {path}')
        if state in UNKNOWN and value is not None:
            raise ValueError(f'Unknown value must be null: {path}')
        if state in {'not_reported', 'not_applicable', 'conflicting'} and not evidence.get('reason'):
            raise ValueError(f'{state} requires an explanation: {path}')
        if state == 'not_reported' and not all(evidence.get(f) for f in ('source_ref', 'checked_scope', 'checked_at')):
            raise ValueError(f'not_reported requires a dated source scope: {path}')
    for field in RELATIONS.get(kind, {}):
        value = data.get(field)
        if value is None:
            continue
        if field.endswith('_refs'):
            if not isinstance(value, list):
                raise ValueError(f'{field} must be a list of revision references or null')
            if len({key(item) for item in value}) != len(value):
                raise ValueError(f'Duplicate revision reference in {field}')
        else:
            key(value)
    if kind in {'code_instance', 'classical_seed'}:
        for field in ('n_data', 'k_logical', 'K', 'r_gauge'):
            value = data.get(field)
            if value is not None and (type(value) is not int or value < (1 if field in {'n_data', 'K'} else 0)):
                raise ValueError(f'Invalid code parameter {field}')
        if kind == 'code_instance' and data['coding_domain'] not in {None, 'quantum'}:
            raise ValueError('Classical seeds are independent records')
        if data.get('n_data') is not None and data.get('k_logical') is not None and data['k_logical'] > data['n_data']:
            raise ValueError('k cannot exceed n')
    if kind == 'distance_claim':
        lower, upper, relation = (data[f] for f in ('lower_bound', 'upper_bound', 'relation'))
        for value in (lower, upper):
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError('Distance bounds must be positive integers or null')
        valid = {None: lower is None and upper is None, 'reported_unspecified': lower is None and upper is None,
                 'exact': lower is not None and lower == upper, 'lower_bound': lower is not None and upper is None,
                 'upper_bound': upper is not None and lower is None,
                 'interval': lower is not None and upper is not None and lower <= upper}
        if not isinstance(relation, (str, type(None))) or not valid.get(relation):
            raise ValueError('Distance bound direction and values disagree')
    if kind == 'performance_point':
        count_fields = ('shots', 'failures', 'discards')
        shots, failures, discards = (data.get(field) for field in count_fields)
        if any(v is not None and (type(v) is not int or v < 0) for v in (shots, failures, discards)):
            raise ValueError('Observation counts must be nonnegative integers or null')
        if shots is not None and (failures or 0) + (discards or 0) > shots:
            raise ValueError('Failures plus discards exceed shots')
        if data['value'] is not None and (type(data['value']) not in {int, float} or not 0 <= data['value'] <= 1):
            raise ValueError('Performance rate must be in [0,1] or null')
    if kind == 'execution_run' and (not data['execution_evidence'] or not data['environment_ref']):
        raise ValueError('An execution run requires actual execution evidence and environment')
    if kind == 'software_usage':
        use = data['usage_kind']
        if use not in ('mention', 'citation', 'source_reported_use', 'locally_observed_use'):
            raise ValueError('Invalid software usage category')
        if use == 'source_reported_use' and not (data.get('source_ref') and data.get('experiment_ref')):
            raise ValueError('Reported use requires an exact source and experiment')
        if use == 'locally_observed_use' and not data.get('execution_run_ref'):
            raise ValueError('Observed use requires a real execution run')
        if use in ('mention', 'citation') and (data.get('experiment_ref') or data.get('execution_run_ref')):
            raise ValueError('Mentions/citations do not establish use by an experiment')
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
                    resolve(record, binding, (kinds,) if isinstance(kinds, str) else kinds)
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
