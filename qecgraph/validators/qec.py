"""Explicit mathematical checks; these never confer human or Lean review."""
from __future__ import annotations

from ..graph import canonical


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def matrix_rows(matrix):
    if matrix.get('field') != 'GF(2)' or matrix.get('format') != 'coordinate-ones-v1' or type(matrix.get('index_base')) is not int or matrix['index_base'] != 0:
        raise ValueError('Expected GF(2) coordinate-ones-v1 with index_base=0')
    shape = matrix.get('shape')
    if not isinstance(shape, list) or len(shape) != 2:
        raise ValueError('Matrix needs explicit [rows, columns] shape')
    m, n = [_integer(x, 'matrix shape') for x in shape]
    coordinates = matrix.get('ones')
    if not isinstance(coordinates, list):
        raise ValueError('Matrix ones must be a sorted coordinate list')
    rows, prior = [0] * m, None
    for coordinate in coordinates:
        if not isinstance(coordinate, list) or len(coordinate) != 2:
            raise ValueError('Invalid matrix coordinate')
        i, j = [_integer(x, 'matrix coordinate') for x in coordinate]
        if i >= m or j >= n:
            raise ValueError('Matrix coordinate outside explicit shape')
        if prior is not None and (i, j) <= prior:
            raise ValueError('Coordinates must be sorted and unique')
        prior = (i, j)
        rows[i] |= 1 << j
    return rows, n


def basis(rows):
    pivots = {}
    for row in rows:
        while row:
            pivot = row.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = row
                break
            row ^= pivots[pivot]
    return pivots


def in_span(row, pivots):
    while row:
        pivot = row.bit_length() - 1
        if pivot not in pivots:
            return False
        row ^= pivots[pivot]
    return True


def _orthogonal(left, right):
    return all((a & b).bit_count() % 2 == 0 for a in left for b in right)


def check_css(hx, hz, lx=None, lz=None, *, enumerate_distance=False, max_n=20):
    x, n = matrix_rows(hx)
    z, nz = matrix_rows(hz)
    if n != nz:
        raise ValueError('HX and HZ have different qubit column counts')
    bx, bz = basis(x), basis(z)
    commutes = _orthogonal(x, z)
    result = {'checker': 'qecgraph.binary-css.v1', 'n': n, 'rank_HX_gf2': len(bx), 'rank_HZ_gf2': len(bz),
              'commutes': commutes, 'passed': commutes, 'k': n - len(bx) - len(bz) if commutes else None,
              'distance': None, 'phase_convention': '+1 binary CSS stabilizers',
              'lean_status': 'not_performed', 'human_review': 'not_performed'}
    if not commutes:
        result['failure'] = 'HX * transpose(HZ) != 0 over GF(2)'
        return result
    k = result['k']
    if (lx is None) != (lz is None):
        raise ValueError('Logical validation needs both LX and LZ')
    if lx is not None:
        logical_x, nx = matrix_rows(lx)
        logical_z, nz = matrix_rows(lz)
        correct = nx == n == nz and len(logical_x) == len(logical_z) == k
        correct &= _orthogonal(z, logical_x) and _orthogonal(x, logical_z)
        correct &= all((a & b).bit_count() % 2 == int(i == j)
                       for i, a in enumerate(logical_x) for j, b in enumerate(logical_z))
        result['logical_pairing_valid'] = correct
        result['passed'] &= correct
    if enumerate_distance:
        if not 0 <= max_n <= 22 or n > max_n:
            raise ValueError('Finite enumeration exceeds configured n budget (maximum 22)')
        if not k:
            result['distance_status'] = 'out_of_domain_k_zero'
            return result
        dx, dz = n + 1, n + 1
        for vector in range(1, 1 << n):
            weight = vector.bit_count()
            if weight < dx and _orthogonal([vector], z) and not in_span(vector, bx):
                dx = weight
            if weight < dz and _orthogonal([vector], x) and not in_span(vector, bz):
                dz = weight
        result['distance'] = {'dX': dx, 'dZ': dz, 'd': min(dx, dz), 'relation': 'exact',
                              'evidence_kind': 'computed_exact', 'vectors': 1 << n,
                              'method': 'complete_binary_vector_enumeration'}
    return result


def distance_issues(data):
    issues = []
    relation = data.get('relation')
    if relation not in {'exact', 'lower_bound', 'upper_bound', 'interval'}:
        return ['Unknown distance relation']
    lower, upper = data.get('lower_bound'), data.get('upper_bound')
    for name, value in [('lower_bound', lower), ('upper_bound', upper)]:
        if value is not None and (type(value) is not int or value < 1):
            issues.append(f'{name} must be a positive integer or null')
    if issues:
        return issues
    if relation == 'upper_bound' and (upper is None or lower is not None):
        issues.append('An upper bound cannot supply a lower bound')
    if relation == 'lower_bound' and (lower is None or upper is not None):
        issues.append('A lower-bound claim must keep its unknown upper bound null')
    if relation == 'exact' and (lower is None or lower != upper):
        issues.append('Exact distance needs equal known lower and upper bounds')
    if relation == 'interval' and (lower is None or upper is None or lower > upper):
        issues.append('Distance interval needs ordered known endpoints')
    for field in ('subject_id', 'presentation_id', 'metric_definition_id', 'sector', 'method', 'assumptions'):
        if data.get(field) is None:
            issues.append('Distance claim missing ' + field)
    if data.get('sector') not in {'X', 'Z', 'joint'}:
        issues.append('Distance sector must be X, Z or joint')
    return issues


def check_experiment(record, metric):
    data, definition = record['data'], metric['data']
    sampling, stats = data['sampling'], data['statistics']
    if not isinstance(sampling, dict) or not isinstance(stats, dict):
        raise ValueError('Experiment needs explicit sampling and statistics objects')
    for field in ('event', 'denominator', 'sector', 'rounds', 'boundaries', 'postselection', 'timeout_policy'):
        if definition.get(field) is None:
            raise ValueError('Metric missing ' + field)
    bindings = data['input_revisions']
    if not isinstance(bindings, dict) or not {'code', 'presentation', 'circuit', 'noise', 'decoder', 'metric'} <= bindings.keys():
        raise ValueError('Experiment must bind code/presentation/circuit/noise/decoder/metric revisions')
    for binding in bindings.values():
        if not isinstance(binding, dict) or not all(binding.get(k) for k in ('id', 'revision', 'content_sha256')):
            raise ValueError('Experiment input binding needs ID, revision and content hash')
    method = sampling.get('method')
    result = {'checker': 'qecgraph.experiment.v1', 'sampling_method': method,
              'metric_definition_id': metric['id'], 'estimate': None, 'lean_status': 'not_performed',
              'input_binding_validation': 'structure_only; resolve referenced inputs separately'}
    if data['metric'] != metric['id'] or bindings['metric']['id'] != metric['id']:
        raise ValueError('Experiment and metric input IDs disagree')
    if method == 'iid':
        shots, discards, accepted, failures = [_integer(stats.get(k), k) for k in ('shots', 'discarded', 'accepted', 'failures')]
        if accepted != shots - discards or failures > accepted or discards > shots:
            raise ValueError('IID counts inconsistent with postselection denominator')
        if not all(sampling.get(k) for k in ('stopping_rule', 'random_stream', 'interval_method')):
            raise ValueError('IID sampling needs stopping rule, random stream and interval method')
        interval = stats.get('confidence_interval', {})
        if not (0 < interval.get('level', 0) < 1 and 0 <= interval.get('lower', -1) <= interval.get('upper', -1) <= 1):
            raise ValueError('Explicit valid confidence interval and level required')
        if failures == 0 and accepted and interval['upper'] == 0:
            raise ValueError('Zero observed failures do not prove zero probability')
        if definition['denominator'] != 'accepted_shots':
            raise ValueError('IID ratio checker supports only explicitly accepted_shots metrics')
        result['estimate'] = failures / accepted if accepted else None
        result['acceptance_rate'] = accepted / shots if shots else None
    elif method == 'importance':
        required = ('target_distribution', 'proposal_distribution', 'weights_asset', 'estimator', 'sufficient_statistics')
        if not all(sampling.get(k) for k in required):
            raise ValueError('Importance sampling lacks estimator/weight provenance')
    elif method == 'mcmc':
        required = ('transition_kernel', 'burn_in', 'chains', 'batches', 'diagnostics', 'estimator')
        if not all(k in sampling and sampling[k] is not None for k in required):
            raise ValueError('MCMC needs chain and correlation diagnostics')
    else:
        raise ValueError('Unknown sampling scheme; no implicit errors/shots estimate')
    result['passed'] = True
    return result


def comparable_experiments(first, second, first_metric, second_metric):
    check_experiment(first, first_metric)
    check_experiment(second, second_metric)
    keys = ('input_revisions', 'configuration', 'metric')
    differences = [key for key in keys if canonical(first['data'][key]) != canonical(second['data'][key])]
    if canonical(first_metric) != canonical(second_metric):
        differences.append('metric_definition')
    if canonical(first['data']['sampling']) != canonical(second['data']['sampling']):
        differences.append('sampling')
    return {'comparable': not differences, 'differences': differences, 'conversion': 'none'}
