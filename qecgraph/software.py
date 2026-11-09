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
    """Load the canonical software catalog packaged with QEC Graph."""
    return strict_json_loads(files('qecgraph').joinpath('catalog/software_catalog.seed.json').read_text(encoding='utf-8'))


def coverage(records):
    records = list(records)
    projects = [r for r in records if r['kind'] == 'software_project']
    discovery = [r for r in records if r['kind'] == 'software_usage' and r['data'].get('project_ref') is None]
    return {'projects': len({r['id'] for r in projects}),
            'catalog_sources': [r['data'] for r in records if r['kind'] == 'catalog_source'],
            'unresolved_usage_revisions': [ref(r) for r in discovery],
            'coverage': 'non_exhaustive', 'installation_or_benchmarks_verified': False}


def _official_repo_url(value):
    import re
    from urllib.parse import urlsplit
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment
            or not re.fullmatch(r'/[A-Za-z0-9-]+/[A-Za-z0-9._-]+/?', parsed.path)):
        return None
    fullname = parsed.path.strip('/')
    if any(p in ('.', '..') for p in fullname.split('/')):
        return None
    return fullname, f'https://api.github.com/repos/{fullname}'


def _fetch_metadata(url, timeout):
    from urllib.request import HTTPRedirectHandler, Request, build_opener
    from .source_package import read_bounded

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    request = Request(url, headers={'Accept': 'application/vnd.github+json',
                                    'X-GitHub-Api-Version': '2026-03-10',
                                    'User-Agent': 'QEC-Graph-Catalogue'})
    with build_opener(NoRedirect).open(request, timeout=timeout) as response:
        return read_bounded(response, 128 * 1024)


def refresh(registry, *, project_id=None, limit=20, timeout=8):
    """Observe allowlisted public repository metadata, never install or infer historical versions."""
    from hashlib import sha256
    from urllib.error import HTTPError
    from .research_store import load_records, publish_records
    from .workspace import now
    if type(limit) is not int or not 1 <= limit <= 20 or not 1 <= timeout <= 30:
        raise ValueError('Refresh limit must be 1..20 and timeout 1..30 seconds')
    state, release = registry.read()
    projects = [r for r in load_records(registry, state)
                if r['kind'] == 'software_project' and not r['is_synthetic']
                and (project_id is None or r['id'] == project_id)]
    if not projects:
        raise ValueError('No matching project in this workspace; import the seed first')
    prepared, reports = [], []
    for project in projects[:limit]:
        origin = _official_repo_url(project['data'].get('repository_url'))
        if origin is None:
            reports.append({'project_ref': ref(project), 'status': 'unsupported_source'})
            continue
        fullname, url = origin
        try:
            raw = _fetch_metadata(url, timeout)
            info = strict_json_loads(raw.decode('utf-8'), source='GitHub repository response')
            if (not isinstance(info, dict) or not isinstance(info.get('full_name'), str)
                    or info['full_name'].casefold() != fullname.casefold()
                    or info.get('private') is not False
                    or not all(type(info.get(f)) is bool for f in ('archived', 'disabled'))):
                raise ValueError('Public upstream identity or response fields did not match')
        except HTTPError as exc:
            reports.append({'project_ref': ref(project), 'status': 'http_unavailable', 'http_status': exc.code})
            continue
        except (OSError, ValueError):
            reports.append({'project_ref': ref(project), 'status': 'not_observed'})
            continue
        metadata = {'observed_at': now(), 'api_url': url, 'body_sha256': sha256(raw).hexdigest(),
                    'upstream_repository': info['full_name']}
        source = {'id': 'catalog-source:github:' + hash_text(fullname.casefold()),
                  'revision': hash_text(canonical(metadata))}
        method = 'github_public_repository_observation_v1'
        prepared.append(make_record('catalog_source', source['id'], source['revision'], metadata,
                                    source=source, method=method))
        observation = make_record('software_catalog_observation',
                                  'catalog-observation:' + hash_text(project['id']),
                                  hash_text(canonical([source, ref(project)])),
                                  {'project_ref': ref(project), 'archived': info['archived'],
                                   'disabled': info['disabled'], 'upstream_checked_at': metadata['observed_at']},
                                  source=source, method=method)
        prepared.append(observation)
        reports.append({'project_ref': ref(project), 'status': 'observed', 'observation_ref': ref(observation)})
    if prepared:
        release = publish_records(registry, prepared)['release_id']
    return {'status': 'observed' if reports and all(r['status'] == 'observed' for r in reports) else 'partial',
            'release_id': release, 'results': reports, 'truncated': len(projects) > limit,
            'coverage': 'public GitHub repository metadata only; no installed capabilities or historical release inference'}
