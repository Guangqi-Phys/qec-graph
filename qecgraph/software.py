"""Offline adapter for a bounded directory of upstream software identities."""
from __future__ import annotations

from importlib.resources import files

from .graph import canonical, hash_text, strict_json_loads
from .research import make_record, ref, validate_bundle

SEED_SCHEMA = 'qecgraph.software_catalog.seed.v1'


def adapt_seed(seed):
    if seed.get('schema_version') != SEED_SCHEMA or seed.get('completeness') != 'non_exhaustive':
        raise ValueError('Expected a non-exhaustive v1 software catalog seed')
    method = 'catalog_seed_upstream_metadata_not_tested'
    identity = seed['catalogue_id']
    source = {'id': identity, 'revision': hash_text(canonical(seed))}
    records = [make_record('catalog_source', identity, source['revision'],
                           {field: seed[field] for field in ('catalogue_scope', 'completeness', 'checked_at', 'verification_policy')},
                           source=source, method=method)]
    algorithms = set()
    for entry in seed['entries']:
        project_id = entry['id']
        data = {field: value for field, value in entry.items() if field not in ('id', 'distributions', 'algorithms')}
        # Algorithm names are discovery terms. They are not package aliases or Usage assertions.
        data['documented_algorithm_names'] = entry['algorithms']
        algorithms.update(entry['algorithms'])
        project = make_record('software_project', project_id, hash_text(canonical([source, data])), data, source=source, method=method)
        records.append(project)
        for item in entry['distributions']:
            data = {**item, 'project_ref': ref(project)}
            identifier = 'distribution:' + hash_text(canonical([project_id, item['ecosystem'], item['name']]))
            records.append(make_record('software_distribution', identifier, hash_text(canonical([source, data])), data,
                                       source=source, method=method))
    for name in sorted(algorithms):
        data = {'name': name}
        records.append(make_record('algorithm', 'algorithm:' + hash_text(name.casefold()), hash_text(canonical([source, data])),
                                   data, source=source, method=method))
    validate_bundle(records)
    return records


def bundled_seed():
    """Byte-identical packaging copy of the design attachment seed."""
    return strict_json_loads(files('qecgraph').joinpath('catalog/software_catalog.seed.json').read_text(encoding='utf-8'))


def coverage(records):
    records = list(records)
    projects = [r for r in records if r['kind'] == 'software_project']
    discovery = [r for r in records if r['kind'] == 'software_usage' and r['data'].get('project_ref') is None]
    return {'projects': len({r['id'] for r in projects}),
            'catalog_sources': [r['data'] for r in records if r['kind'] == 'catalog_source'],
            'unresolved_usage_revisions': [ref(r) for r in discovery],
            'coverage': 'non_exhaustive', 'installation_or_benchmarks_verified': False}
