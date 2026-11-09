"""Domain checks that cannot be expressed as generic record/edge shapes."""
from __future__ import annotations

def check_weight_metrics(metrics):
    for metric in metrics:
        low, high, mean = (metric.get(k) for k in ('min', 'max', 'mean'))
        if any(v is not None and type(v) is not int for v in (low, high)):
            raise ValueError('Check weight min/max must be nonnegative integers or null')
        if low is not None and high is not None and low > high or mean is not None and (
                low is not None and mean < low or high is not None and mean > high):
            raise ValueError('Check weight statistics disagree')
        if any(type(v) is not int for v in (metric.get('histogram') or {}).values()):
            raise ValueError('Check weight histogram requires nonnegative weight keys and positive counts')


def validate_details(record):
    kind, data, evidence = record['kind'], record['data'], record['field_evidence']
    if kind == 'construction' and data.get('reconstruction_status') in ('complete', 'reconstructable'):
        if any(type(size) is not int for size in data['matrix_recipe']['shape']):
            raise ValueError('Matrix dimensions must be integers')
    if kind == 'code_presentation' and data.get('check_weight_metrics') is not None:
        check_weight_metrics(data['check_weight_metrics'])
    if kind == 'noise_model':
        for field in ('idle', 'loss', 'erasure', 'leakage'):
            value = data[field]
            if value is not None and value['consideration'] == 'excluded' and not evidence.get('/data/' + field, {}).get('source_locator'):
                raise ValueError(f'Explicit exclusion of {field} requires a source locator')
    if kind == 'circuit_protocol':
        for depth in data.get('depth_metrics') or []:
            if depth['kind'] != 'physical_duration' and type(depth['value']) is not int:
                raise ValueError('Counted depth must use an integer')
    if kind == 'performance_point' and data.get('confidence_interval') is not None:
        interval = data['confidence_interval']
        if not interval['lower'] <= interval['upper']:
            raise ValueError('Confidence interval endpoints are out of order')
