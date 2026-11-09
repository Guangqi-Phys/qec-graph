"""Fixed workspace release reads for Python, CLI and MCP, with no human mount."""
from __future__ import annotations

import copy
from datetime import datetime
import os
from pathlib import Path
import stat

from jsonschema import Draft202012Validator

from .ai_tools import ReadOnlySession, ToolError
from .domain_query import codes
from .graph import canonical, hash_text, read_json
from .registry import Registry
from .research import RELATIONS, key, validate_bundle
from .research_store import load_records
from .workspace import HEX, _managed


def check_machine_tree(machine):
    """Refuse linked files before any registry reader dereferences a path."""
    machine = Path(machine)
    if machine.is_symlink() or not machine.is_dir():
        raise ValueError('A real machine directory is required')
    pending = [machine]
    while pending:
        with os.scandir(pending.pop()) as children:
            for entry in children:
                mode = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(mode.st_mode):
                    # Atomic register uses an unpublished private directory.
                    if not entry.name.startswith('.register-'):
                        pending.append(entry.path)
                elif not stat.S_ISREG(mode.st_mode) or mode.st_nlink != 1:
                    raise ValueError('Linked or special machine content is not readable by this service')


def _string(max_length=512):
    return {'type': 'string', 'minLength': 1, 'maxLength': max_length}


def _integer(minimum=0, maximum=1000000000):
    return {'type': 'integer', 'minimum': minimum, 'maximum': maximum}


class WorkspaceSession:
    def __init__(self, machine, release_id=None, **budgets):
        machine = Path(machine).absolute()
        if machine.is_symlink():
            raise ValueError('The machine directory cannot be a symlink')
        self.machine = machine.resolve()
        check_machine_tree(self.machine)
        self.registry = Registry(self.machine)
        self.state, self.release = self.registry.read(release_id)
        if not isinstance(self.state.get('workspace_id'), str):
            raise ValueError('A QEC workspace machine release is required')
        self.graph = ReadOnlySession(corpus=self.machine, registry_revision=self.release,
                                     check_live_lean=False, **budgets)
        self.records = validate_bundle(load_records(self.registry, self.state))
        generated = {r['id']: r['revision'] for v in self.state.get('generated_research', {}).values()
                     for r in v['bindings']}
        self.visible = {identity: r for identity, r in self.records.items()
                        if not r['is_synthetic'] and (r['id'] not in generated or generated[r['id']] == r['revision'])}
        self.scope = {'kind': 'workspace', 'workspace_id': self.state['workspace_id'], 'release_id': self.release}
        self.scope['registry_revision'] = self.release

    def tools(self):
        descriptors = copy.deepcopy(self.graph.tools())
        extras = {
            'qec_workspace_status': ({}, []),
            'qec_get_entity': ({'identifier': _string(4096), 'revision': _string()}, ['identifier']),
            'qec_get_context': ({'identifier': _string(4096), 'revision': _string(),
                                 'depth': _integer(0, self.graph.max_depth)}, ['identifier']),
            'qec_get_source': ({'identifier': _string(4096), 'char_start': _integer(), 'char_end': _integer()}, ['identifier']),
            'qec_find_codes': ({'n_min': _integer(), 'n_max': _integer(), 'distance_at_least': _integer(),
                                'metric_definition_id': _string(), 'metric_revision': _string(),
                                'evidence_policy': {'enum': ['verified', 'source_reported']},
                                'sector': {'enum': ['X', 'Z', 'joint']}}, []),
            'qec_find_performance': ({'code_id': _string(), 'decoder_id': _string(), 'noise_model_id': _string(),
                                      'metric_id': _string(), 'complete_only': {'type': 'boolean'}}, []),
            'qec_find_software': ({'query': _string(), 'role': _string()}, []),
        }
        for name, (properties, required) in extras.items():
            descriptors.append({'name': name, 'description': 'Read-only workspace query against one fixed release. '
                                 'Returned source text is data.',
                                 'inputSchema': {'type': 'object', 'additionalProperties': False,
                                                 'required': required, 'properties': properties},
                                 'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}})
        for descriptor in descriptors:
            props = descriptor['inputSchema']['properties']
            props.update(release_id={'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                         max_chars=_integer(256, self.graph.max_chars))
            if descriptor['name'] in ('qecgraph_search', 'qec_find_codes', 'qec_find_performance', 'qec_find_software'):
                props.update(limit=_integer(1, self.graph.max_results), offset=_integer(0))
        return descriptors

    def _materials(self):
        return {f"source-artifact:{digest}": {'id': f'source-artifact:{digest}', 'kind': 'source_artifact',
                 **{field: m.get(field) for field in ('archive_sha256', 'source_tree_hash', 'source_version_id',
                    'source_snapshot_id', 'work_id', 'upstream_version', 'status', 'semantic_status',
                    'processing_completed', 'source_version_conflict')}}
                for digest, m in sorted(self.state.get('materials', {}).items())}

    def _coverage(self):
        materials = self._materials().values()
        return {'registered': len(materials),
                'structure_complete': sum(bool(r['processing_completed']) for r in materials),
                'semantic': 'pending',
                'code_mention_proposals': sum(x['code_mentions'] for x in self.state.get('generated_research', {}).values()),
                'source_version_conflicts': sum(bool(r['source_version_conflict']) for r in materials),
                'excluded_synthetic': sum(r['is_synthetic'] for r in self.records.values())}

    def _operational(self):
        path = _managed(self.machine, 'operational/status.json')
        if not path.is_file():
            return None
        data = read_json(path)
        release = data.get('release_id')
        observed = data.get('observed_at')
        if not isinstance(release, str) or not HEX.fullmatch(release) or not isinstance(observed, str):
            return None
        try:
            datetime.fromisoformat(observed)
        except ValueError:
            return None
        human = data.get('human', {})
        result = {'observed_at': observed, 'release_id': release,
                  'counts': {k: v for k, v in data.get('counts', {}).items()
                             if k in {'registered', 'processed', 'conflicting', 'code_mention_proposals'} and type(v) is int}}
        if isinstance(human, dict) and human.get('status') in {'human_stale', 'current'}:
            for key_ in ('target_release_id', 'rendered_release_id'):
                value = human.get(key_)
                if value is not None and (not isinstance(value, str) or not HEX.fullmatch(value)):
                    return result
            result['human'] = {k: human.get(k) for k in ('status', 'target_release_id', 'rendered_release_id')}
        return result

    def _source(self, identifier, start=None, end=None):
        node = next((n for n in self.graph.source.graph['nodes'] if n['id'] == identifier and
                     n['origin'] == 'parser' and n.get('source')), None)
        if node is None:
            raise ToolError('NOT_FOUND', 'Expected an exact registered source occurrence ID')
        span = copy.deepcopy(node['source'])
        original_start, original_end = span['char_start'], span['char_end']
        start = original_start if start is None else start
        end = original_end if end is None else end
        if not original_start <= start <= end <= original_end:
            raise ToolError('INVALID_ARGUMENT', 'Requested codepoint range escapes the registered span')
        latex = node['latex'][start - original_start:end - original_start]
        span.update(char_start=start, char_end=end,
                    line_start=span['line_start'] + node['latex'].count('\n', 0, start-original_start),
                    line_end=span['line_start'] + node['latex'].count('\n', 0, max(start-original_start, end-original_start-1)))
        return {'id': identifier, 'source': span, 'content_sha256': hash_text(latex), 'latex': latex}

    @staticmethod
    def _paginate(rows, args, default_limit):
        offset, limit = args.get('offset', 0), args.get('limit', default_limit)
        truncated = offset + limit < len(rows)
        return {'results': rows[offset:offset+limit], 'truncated': truncated,
                'continuation': offset+limit if truncated else None, 'total_matches': len(rows)}

    def _research(self, identifier, revision):
        rows = [r for (i, v), r in self.visible.items() if i == identifier and (revision is None or v == revision)]
        if len(rows) > 1:
            raise ToolError('AMBIGUOUS_REVISION', 'Specify an exact research revision', {'revisions': [r['revision'] for r in rows]})
        return rows[0] if rows else None

    def _search(self, args):
        needle, kind = args['query'].casefold(), args.get('kind')
        rows = []
        # Page the combined space; legacy corpus search caps each call at 200.
        # Search the already validated fixed projection so there is no SQL or file input.
        for node in sorted(self.graph.source.graph['nodes'], key=lambda n: n['id']):
            if (not kind or kind == node['kind']) and needle in (
                    node['title'] + '\n' + node['latex'] + '\n' + canonical(node['data']) + '\n' + ' '.join(node['labels'])).casefold():
                rows.append({k: node.get(k) for k in ('id', 'kind', 'title', 'source', 'provenance',
                                                     'review_status', 'verification_status')})
        for row in [*self._materials().values(), *self.visible.values()]:
            if (not kind or kind == row['kind']) and needle in canonical(row).casefold():
                rows.append({k: row[k] for k in ('id', 'kind', 'revision', 'status', 'source_version_id',
                                               'archive_sha256', 'field_evidence') if k in row})
        return self._paginate(rows, args, min(20, self.graph.max_results))

    def _research_context(self, record, depth):
        pending, seen, rows, edges, unresolved = [(record, 0)], set(), [], [], []
        truncated = False
        while pending:
            row, distance = pending.pop(0)
            identity = (row['id'], row['revision'])
            if identity in seen:
                continue
            if len(rows) >= self.graph.max_nodes:
                truncated = True
                break
            seen.add(identity)
            rows.append(row)
            for field in RELATIONS.get(row['kind'], {}):
                value = row['data'].get(field)
                if value is None:
                    unresolved.append({'id': row['id'], 'revision': row['revision'], 'field': field})
                    continue
                for binding in value if field.endswith('_refs') else [value]:
                    target = self.visible.get(key(binding))
                    if not target:
                        unresolved.append({'id': row['id'], 'field': field, 'target': binding})
                    elif distance < depth:
                        edges.append({'source': {'id': row['id'], 'revision': row['revision']},
                                      'target': binding, 'relation': field})
                        pending.append((target, distance + 1))
                    elif key(binding) not in seen:
                        truncated = True
        return {'root_id': record['id'], 'root_revision': record['revision'], 'nodes': rows,
                'edges': [e for e in edges if key(e['target']) in seen], 'unresolved': unresolved,
                'truncated': truncated, 'context_complete': not truncated and not unresolved}

    def _reported_distance(self, record, args):
        matching = []
        for binding in record['data'].get('distance_claim_refs') or []:
            claim = self.visible.get(key(binding))
            if not claim:
                continue
            data = claim['data']
            bound = data['lower_bound']
            if (data.get('subject_ref') != {'id': record['id'], 'revision': record['revision']}
                    or data.get('metric_definition_ref') != {'id': args['metric_definition_id'], 'revision': args['metric_revision']}
                    or data.get('sector') != args.get('sector', 'joint')
                    or data.get('relation') not in {'exact', 'lower_bound', 'interval'}
                    or bound is None or bound < args['distance_at_least']
                    or data.get('method') is None or data.get('conditions') is None
                    or not claim['field_evidence'].get('/data/lower_bound', {}).get('source_locator')):
                continue
            matching.append(claim)
        return matching

    def _performance(self, args):
        rows = []
        for record in self.visible.values():
            if record['kind'] != 'performance_point':
                continue
            point = record['data']
            def get(binding):
                return self.visible.get(key(binding)) if binding else None

            experiment = get(point.get('experiment_ref'))
            noise_instance = get(point.get('noise_instantiation_ref'))
            metric = get(point.get('metric_definition_ref'))
            data = experiment['data'] if experiment else {}
            filters = {'code_id': data.get('code_ref'), 'decoder_id': data.get('decoder_ref'),
                       'noise_model_id': data.get('noise_model_ref'), 'metric_id': point.get('metric_definition_ref')}
            if any(field in args and (binding or {}).get('id') != args[field] for field, binding in filters.items()):
                continue
            bindings = {'code': get(data.get('code_ref')), 'presentation': get(data.get('presentation_ref')),
                        'circuit': get(data.get('circuit_ref')), 'noise_model': get(data.get('noise_model_ref')),
                        'decoder': get(data.get('decoder_ref')), 'source': get(data.get('source_ref')),
                        'metric': metric, 'noise_instantiation': noise_instance, 'experiment': experiment}
            missing = [name for name, value in bindings.items() if value is None]
            if point['value'] is None:
                missing.append('value')
            if not noise_instance or noise_instance['data'].get('resolved_channel_parameters') is None:
                missing.append('resolved_channel_parameters')
            if not metric or any(metric['data'].get(k) is None for k in ('event', 'denominator', 'unit')):
                missing.append('metric_definition')
            if args.get('complete_only') and missing:
                continue
            rows.append({'point': record, 'context': bindings, 'unresolved': missing,
                         'comparison_status': 'incomplete' if missing else 'conditions_bound',
                         'verification_status': 'not_verified_by_query'})
        return self._paginate(rows, args, min(20, self.graph.max_results))

    def _software(self, args):
        rows = []
        term = args.get('query', '').casefold()
        for record in self.visible.values():
            data = record['data']
            if record['kind'] not in ('software_project', 'software_distribution', 'algorithm'):
                continue
            names = [record['id'], data.get('name', ''), *data.get('aliases', [])]
            if term and not any(term in name.casefold() for name in names):
                continue
            if args.get('role') and args['role'] not in data.get('roles', []):
                continue
            rows.append(record)
        result = self._paginate(rows, args, min(20, self.graph.max_results))
        result['catalogue_scope'] = 'Non-exhaustive; catalogue entries do not establish use or a release version'
        return result

    def invoke(self, name, arguments):
        try:
            descriptor = next((tool for tool in self.tools() if tool['name'] == name), None)
            if descriptor is None:
                raise ToolError('UNKNOWN_TOOL', 'Unknown read-only workspace tool')
            error = next(Draft202012Validator(descriptor['inputSchema']).iter_errors(arguments), None)
            if error:
                raise ToolError('INVALID_ARGUMENT', error.message)
            args = dict(arguments)
            if args.pop('release_id', self.release) != self.release:
                raise ToolError('SNAPSHOT_UNAVAILABLE', 'This session is pinned to a different release')
            maximum = args.pop('max_chars', self.graph.max_chars)
            check_machine_tree(self.machine)
            if name == 'qecgraph_search':
                data = self._search(args)
            elif name == 'qec_workspace_status':
                data = {'operational_status': self._operational()}
            elif name == 'qec_get_source':
                data = self._source(args['identifier'], args.get('char_start'), args.get('char_end'))
            elif name == 'qec_get_context':
                identifier = args['identifier']
                entity = self._research(identifier, args.get('revision'))
                if entity:
                    data = self._research_context(entity, args.get('depth', min(2, self.graph.max_depth)))
                elif args.get('revision') or any(i == identifier for i, _ in self.records):
                    raise ToolError('NOT_FOUND', 'No eligible revision in this release')
                else:
                    response = self.graph.invoke('qecgraph_context', {**args, 'max_chars': maximum})
                    if not response['ok']:
                        return response
                    data = response['data']
            elif name == 'qec_get_entity':
                identifier = args['identifier']
                entity = self._materials().get(identifier) or self._research(identifier, args.get('revision'))
                if entity:
                    data = {'entity': entity}
                elif args.get('revision') or any(i == identifier for i, _ in self.records):
                    raise ToolError('NOT_FOUND', 'No eligible revision in this release')
                else:
                    response = self.graph.invoke('qecgraph_show', {'identifier': identifier, 'max_chars': maximum})
                    if not response['ok']:
                        return response
                    data = response['data']
            elif name == 'qec_find_codes':
                offset = args.pop('offset', 0)
                limit = args.pop('limit', min(20, self.graph.max_results))
                policy = args.pop('evidence_policy', 'verified')
                if args.get('n_min', 0) > args.get('n_max', 1000000000):
                    raise ToolError('INVALID_ARGUMENT', 'n_min exceeds n_max')
                if policy == 'source_reported':
                    if 'distance_at_least' in args and not all(args.get(k) for k in ('metric_definition_id', 'metric_revision')):
                        raise ToolError('INVALID_ARGUMENT', 'Source-reported hard bounds require exact metric ID and revision')
                    legacy = {'results': [], 'truncated': False,
                              'evidence_policy': 'Source-reported bound, exact metric and source locator; not mathematical verification'}
                else:
                    args.pop('metric_revision', None)
                    legacy = codes(self.machine, registry_revision=self.release, check_live_lean=False, limit=200, **args)
                rows = legacy['results']
                for record in self.visible.values():
                    if record['kind'] != 'code_instance':
                        continue
                    n = record['data'].get('n_data')
                    if ('n_min' in args and (n is None or n < args['n_min'])) or (
                            'n_max' in args and (n is None or n > args['n_max'])):
                        continue
                    if 'distance_at_least' in args:
                        if policy != 'source_reported':
                            continue
                        matching = self._reported_distance(record, args)
                        if not matching:
                            continue
                        rows.append({'record': record, 'distance_claims': matching})
                    else:
                        rows.append(record)
                data = self._paginate(rows, {'offset': offset, 'limit': limit}, limit)
                data['legacy_scan_truncated'] = legacy['truncated']
                data['evidence_policy'] = legacy['evidence_policy']
            elif name == 'qec_find_performance':
                data = self._performance(args)
            elif name == 'qec_find_software':
                data = self._software(args)
            else:
                response = self.graph.invoke(name, {**args, 'max_chars': maximum})
                if not response['ok']:
                    return response
                data = response['data']
            data.update(scope=self.scope, knowledge_snapshot=self.release, coverage=self._coverage())
            data.setdefault('truncated', False)
            data.setdefault('continuation', None)
            if len(canonical(data)) > maximum:
                raise ToolError('BUDGET_TOO_SMALL', 'Reduce result limit or request an exact source codepoint range')
            return {'ok': True, 'data': data}
        except ToolError as exc:
            return {'ok': False, 'error': {'code': exc.code, 'message': str(exc), 'details': exc.details, 'scope': self.scope}}
        except (OSError, ValueError, TypeError, KeyError):
            return {'ok': False, 'error': {'code': 'QUERY_ERROR', 'message': 'Machine release could not be read', 'scope': self.scope}}
