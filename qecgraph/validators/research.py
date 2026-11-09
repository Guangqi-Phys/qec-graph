"""Domain checks that cannot be expressed as generic record/edge shapes."""
from __future__ import annotations

from math import isfinite

DEPTH_UNITS = {'tick_count': 'ticks', 'two_qubit_layers': 'layers', 'operation_layers': 'layers',
               'physical_duration': ('s', 'ms', 'us', 'ns', 'ps')}
RECIPE_FIELDS = {'field', 'shape', 'index_convention', 'bit_order', 'formula', 'version', 'seed_refs'}


def _number(value):
    return type(value) is int or (type(value) is float and isfinite(value))


def _recipe_complete(recipe):
    return (isinstance(recipe, dict) and not any(recipe.get(k) is None for k in RECIPE_FIELDS)
            and isinstance(recipe['seed_refs'], list)
            and isinstance(recipe['shape'], list) and len(recipe['shape']) == 2
            and all(type(x) is int and x >= 0 for x in recipe['shape']))


def check_weight_metrics(metrics):
    if not isinstance(metrics, list):
        raise ValueError('check_weight_metrics must be a list or null')
    for metric in metrics:
        if (not isinstance(metric, dict) or not isinstance(metric.get('check_set_id'), str)
                or not metric['check_set_id'].strip() or metric.get('sector') not in ('X', 'Z', 'mixed')
                or metric.get('scope') not in ('stabilizer', 'gauge', 'measured')):
            raise ValueError('Weight metrics need a check-set ID, sector and scope')
        low, high, mean = (metric.get(k) for k in ('min', 'max', 'mean'))
        if any(v is not None and (type(v) is not int or v < 0) for v in (low, high)):
            raise ValueError('Check weight min/max must be nonnegative integers or null')
        if mean is not None and (not _number(mean) or mean < 0):
            raise ValueError('Mean check weight must be nonnegative or null')
        if low is not None and high is not None and low > high or mean is not None and (
                low is not None and mean < low or high is not None and mean > high):
            raise ValueError('Check weight statistics disagree')
        histogram = metric.get('histogram')
        if histogram is not None and (not isinstance(histogram, dict) or any(
                not isinstance(k, str) or not k.isascii() or not k.isdecimal()
                or (k != '0' and k.startswith('0')) or type(v) is not int or v < 1 for k, v in histogram.items())):
            raise ValueError('Check weight histogram requires nonnegative weight keys and positive counts')


def validate_details(record):
    kind, data, evidence = record['kind'], record['data'], record['field_evidence']
    if kind in {'construction', 'code_presentation'}:
        if data.get('reconstruction_status') in ('complete', 'reconstructable'):
            if kind == 'construction' and not _recipe_complete(data.get('matrix_recipe')):
                raise ValueError('A complete matrix recipe needs the field, shape, indexing, bit order, formula, version and seeds')
            if kind == 'code_presentation' and not (data.get('generator_asset_refs') or data.get('construction_recipe_ref')):
                raise ValueError('A reconstructable presentation needs matrix assets or a complete construction')
        if kind == 'code_presentation' and data.get('check_weight_metrics') is not None:
            check_weight_metrics(data['check_weight_metrics'])
    if kind == 'noise_model':
        for field in ('idle', 'loss', 'erasure', 'leakage'):
            value = data[field]
            if value is None:
                continue
            if not isinstance(value, dict) or value.get('consideration') not in ('included', 'excluded'):
                raise ValueError(f'Noise consideration for {field} must be included, excluded or null')
            if value['consideration'] == 'excluded' and not evidence.get('/data/' + field, {}).get('source_locator'):
                raise ValueError(f'Explicit exclusion of {field} requires a source locator')
    if kind == 'circuit_protocol' and data.get('depth_metrics') is not None:
        if not isinstance(data['depth_metrics'], list):
            raise ValueError('depth_metrics must be a list or null')
        for depth in data['depth_metrics']:
            if not isinstance(depth, dict) or not isinstance(depth.get('kind'), str):
                raise ValueError('Depth needs an explicit counting or timing definition')
            expected = DEPTH_UNITS.get(depth['kind'])
            allowed = (expected,) if isinstance(expected, str) else expected or ()
            value = depth.get('value')
            if (depth.get('unit') not in allowed or not isinstance(depth.get('definition'), str)
                    or not depth['definition'].strip() or not _number(value) or value < 0
                    or depth['kind'] != 'physical_duration' and type(value) is not int):
                raise ValueError('Depth kind, definition, value and unit are incompatible')
    if kind == 'performance_point' and data.get('confidence_interval') is not None:
        interval = data['confidence_interval']
        if not isinstance(interval, dict):
            raise ValueError('Confidence interval requires method, confidence level and endpoints')
        lower, upper, level = (interval.get(k) for k in ('lower', 'upper', 'level'))
        if (not isinstance(interval.get('method'), str) or not interval['method'].strip()
                or not all(_number(v) for v in (lower, upper, level))
                or not 0 <= lower <= upper <= 1 or not 0 < level < 1):
            raise ValueError('Invalid rate confidence interval')
