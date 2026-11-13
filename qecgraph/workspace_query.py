"""Fixed workspace release reads for Python, CLI and MCP, with no human mount."""
from __future__ import annotations

import base64
import copy
from collections import Counter, deque
from datetime import datetime
from functools import cached_property
from math import isfinite
import os
from pathlib import Path
import stat

from .mcp.ai_tools import ReadOnlySession, tool_validators
from .core.errors import ToolError
from .domain.domain_query import codes
from .core.graph import canonical, hash_text, strict_json_loads
from .query import GraphTextIndex, search_node_summary
from .source.reading import source_reading_text
from .registry import Registry
from .domain.research import RELATIONS, key, validate_bundle
from .domain.research_store import load_records
from .workspace import HEX
from .core.fs import managed_path as _managed, read_regular
from .workspace_assets import asset_bytes, references
from .llm.artifacts import load_normalization, mapped_ranges


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
    def __init__(self, machine, release_id=None, *, profile='legacy', _candidate_state=None, **budgets):
        if profile not in {'legacy', 'research', 'compatible'}:
            raise ValueError('Unknown workspace tool profile')
        self.profile = profile
        machine = Path(machine).absolute()
        if machine.is_symlink():
            raise ValueError('The machine directory cannot be a symlink')
        self.machine = machine.resolve()
        check_machine_tree(self.machine)
        self.registry = Registry(self.machine)
        if _candidate_state is None:
            self.state, self.release = self.registry.read(release_id)
        else:
            self.state = copy.deepcopy(_candidate_state)
            self.release = hash_text(canonical(self.state))
        if not isinstance(self.state.get('workspace_id'), str):
            raise ValueError('A QEC workspace machine release is required')
        self.graph = ReadOnlySession(corpus=self.machine, check_live_lean=False,
                                     _fixed_registry=(self.registry, self.state, self.release), **budgets)
        self.records = validate_bundle(load_records(self.registry, self.state))
        generated = {r['id']: r['revision'] for v in self.state.get('generated_research', {}).values()
                     for r in v['bindings']}
        self.review_states = {}
        for decision in self.state.get('semantic_decisions', {}).values():
            if decision['decision'] != 'approve':
                continue
            source = decision['source_ref']
            current = self.state['versions'].get(source['id'], {}).get('snapshot_id') == source['revision']
            for binding in decision['record_refs']:
                self.review_states[key(binding)] = {'status': 'reviewed' if current else 'stale',
                                                   'proposal_id': decision['proposal_id'],
                                                   'reviewer': decision['reviewer']}
        self.visible = {identity: {**r, **({'effective_review': self.review_states[identity]} if identity in self.review_states else {})}
                        for identity, r in self.records.items() if not r['is_synthetic']
                        and (r['id'] not in generated or generated[r['id']] == r['revision'])
                        and self.review_states.get(identity, {}).get('status') != 'stale'}
        self._research_ids = {identifier for identifier, _ in self.records}
        self._visible_by_id = {}
        for (identifier, _), record in self.visible.items():
            self._visible_by_id.setdefault(identifier, []).append(record)
        self.scope = {'kind': 'workspace', 'workspace_id': self.state['workspace_id'], 'release_id': self.release}
        self.scope['registry_revision'] = self.release
        self.assets = {uri for r in self.visible.values() for uri in references(r)}
        self._source_nodes = {n['id']: n for n in self.graph.source.graph['nodes']
                              if n['origin'] == 'parser' and n.get('source')}
        self.resources = {self._resource_uri(identifier): identifier for identifier in self._source_nodes}
        self._resource_bindings = sorted(self.resources.items())
        # Keep old pinned-release URIs readable without advertising every block.
        self.resources.update({f'qec://source/{self.release}/{hash_text(identifier)}': identifier
                               for identifier in self._source_nodes})
        self._paper_resources = {f'qec://paper/{hash_text(version)}': node['id']
                                 for version, node in self.knowledge.documents.items()}
        if self.profile != 'legacy':
            self._resource_bindings = sorted(self._paper_resources.items())
        self._normalizations = {
            (material['source_version_id'], material['source_snapshot_id']): material
            for material in self.state.get('materials', {}).values() if material.get('normalization_id')
        }

    def _resource_uri(self, occurrence):
        node = self._source_nodes[occurrence]
        source = node['source']
        binding = [source.get(field) for field in
                   ('source_version_id', 'path', 'file_sha256', 'char_start', 'char_end')]
        return 'qec://source/' + hash_text(canonical([*binding, node['kind']]))

    def resource_templates(self):
        return {'resourceTemplates': [{'uriTemplate': 'qec://source/{content_binding}',
                'name': 'Registered source occurrence', 'mimeType': 'text/plain',
                'description': 'Use the content binding from a source resource_uri; only exact registered bindings resolve.'}]}

    def material_records(self):
        """Copy the registered material inventory for the fixed release."""
        return copy.deepcopy(list(self._materials.values()))

    def visible_research(self):
        """Copy eligible research revisions and their effective review states."""
        return copy.deepcopy(list(self.visible.values()))

    def projected_graph(self, *, parser_kinds):
        """Copy the selected graph projection, including relations within it."""
        graph = self.graph.source.graph
        nodes = [node for node in graph['nodes'] if node['origin'] == 'registry' or node['kind'] in parser_kinds]
        visible = {node['id'] for node in nodes}
        edges = [edge for edge in graph['edges'] if edge['source'] in visible and edge['target'] in visible]
        return copy.deepcopy((nodes, edges))

    def source_snapshot_id(self, source_version):
        """Return the current source binding within this release, if present."""
        return self.state['versions'].get(source_version, {}).get('snapshot_id')

    def source_projection(self, source_version):
        """Read the verified original graph for an exact registered source."""
        if self.source_snapshot_id(source_version) is None:
            raise ValueError('Unknown source version in this release')
        graph, _, _ = self.registry.source_graph_from_state(self.state, source_version, self.release)
        return graph

    def list_resources(self, cursor=None):
        if cursor is None:
            offset = 0
        elif isinstance(cursor, str) and len(cursor) <= 10 and cursor.isascii() and cursor.isdecimal():
            offset = int(cursor)
        else:
            raise ToolError('INVALID_ARGUMENT', 'Invalid source cursor')
        bindings = self._resource_bindings
        rows = []
        # Reserve the cursor field even on the final page, as in the response check.
        size = len(canonical({'resources': [], 'nextCursor': ''}))
        for uri, identifier in bindings[offset:offset + self.graph.max_results]:
            row = {'uri': uri, 'name': identifier, 'mimeType': 'text/plain'}
            if uri in self._paper_resources:
                version = self.knowledge.nodes[identifier]['provenance']['source_version_id']
                row.update(name=self.knowledge.papers[version]['title'], mimeType='application/json')
            size += len(canonical(row)) + (1 if rows else 0)
            cursor_size = len(str(offset + len(rows) + 1))
            if size + cursor_size > self.graph.max_chars:
                break
            rows.append(row)
        if not rows and offset < len(bindings):
            raise ToolError('BUDGET_TOO_SMALL', 'Resource descriptor exceeds the response budget')
        result = {'resources': rows}
        if offset + len(rows) < len(bindings):
            result['nextCursor'] = str(offset + len(rows))
        return result

    def read_resource(self, uri):
        if uri in self._paper_resources:
            data = self.knowledge.card(self.knowledge.nodes[self._paper_resources[uri]])
            result = {'contents': [{'uri': uri, 'mimeType': 'application/json', 'text': canonical(data),
                                   '_meta': {'release_id': self.release}}]}
            if len(canonical(result)) > self.graph.max_chars:
                raise ToolError('BUDGET_TOO_SMALL', 'Use qec_list_papers or a larger response budget')
            return result
        identifier = self.resources.get(uri)
        if identifier is None:
            raise ToolError('NOT_FOUND', 'Resource is not registered in this release')
        source = self.source_excerpt(identifier)
        resource = {'uri': uri, 'mimeType': 'text/plain', 'text': source['latex'],
                    '_meta': {'release_id': self.release, 'occurrence_id': identifier,
                              'content_sha256': source['content_sha256'], 'source': source['source'],
                              **{key: source[key] for key in ('original_ranges', 'structure_classification',
                                                              'structure_status') if key in source}}}
        result = {'contents': [resource]}
        if len(canonical(result)) > self.graph.max_chars:
            raise ToolError('BUDGET_TOO_SMALL', 'Use qec_get_source with an exact source codepoint range')
        return result

    @cached_property
    def _tool_descriptors(self):
        descriptors = self.graph.tools()
        extras = {
            'qec_workspace_status': ({}, []),
            'qec_get_entity': ({'identifier': _string(4096), 'revision': _string()}, ['identifier']),
            'qec_get_context': ({'identifier': _string(4096), 'revision': _string(),
                                 'depth': _integer(0, self.graph.max_depth),
                                 'max_nodes': _integer(1, self.graph.max_nodes),
                                 'include_candidates': {'type': 'boolean'}}, ['identifier']),
            'qec_get_asset': ({'identifier': _string(80), 'offset': _integer(),
                               'length': _integer(1, 32768)}, ['identifier']),
            'qec_get_source': ({'identifier': _string(4096), 'char_start': _integer(), 'char_end': _integer()}, ['identifier']),
            'qec_find_codes': ({'n_min': _integer(), 'n_max': _integer(), 'distance_at_least': _integer(),
                                'metric_id': _string(), 'metric_revision': _string(),
                                'evidence_policy': {'enum': ['verified', 'source_reported']},
                                'sector': {'enum': ['X', 'Z', 'joint']}}, []),
            'qec_find_performance': ({'code_id': _string(), 'decoder_id': _string(), 'noise_model_id': _string(),
                                      'metric_id': _string(), 'complete_only': {'type': 'boolean'},
                                      'coordinate_name': _string(), 'coordinate': {'type': 'number'},
                                      'selection': {'enum': ['exact', 'nearest_reported']}}, []),
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
            if descriptor['name'] == 'qecgraph_search':
                props['view'] = {'enum': ['raw', 'reading']}
            if descriptor['name'] in ('qecgraph_search', 'qec_find_codes', 'qec_find_performance', 'qec_find_software'):
                props.update(limit=_integer(1, self.graph.max_results), offset=_integer(0))
        from .knowledge import descriptors as knowledge_descriptors
        return knowledge_descriptors(self, descriptors)

    @cached_property
    def _tool_validators(self):
        return tool_validators(self.tools())

    def tools(self):
        from .knowledge import RESEARCH_TOOLS
        selected = {'research': set(RESEARCH_TOOLS), 'compatible': {'search', 'fetch'}}.get(self.profile)
        if selected is None:
            selected = {t['name'] for t in self._tool_descriptors[:13]}
        return copy.deepcopy([t for t in self._tool_descriptors if t['name'] in selected])

    @cached_property
    def knowledge(self):
        from .knowledge import KnowledgeView
        return KnowledgeView(self)

    @cached_property
    def _materials(self):
        return {f"source-artifact:{digest}": {'id': f'source-artifact:{digest}', 'kind': 'source_artifact',
                 **{field: m.get(field) for field in ('archive_sha256', 'source_tree_hash', 'source_version_id',
                    'source_snapshot_id', 'work_id', 'upstream_version', 'status', 'semantic_status',
                    'processing_completed', 'source_version_conflict')},
                 **({'structure_recovery': m['structure_recovery']} if 'structure_recovery' in m else {})}
                for digest, m in sorted(self.state.get('materials', {}).items())}

    @cached_property
    def _coverage(self):
        materials = self._materials.values()
        return {'registered': len(materials),
                'structure_complete': sum(bool(r['processing_completed']) for r in materials),
                'recovered_proposed': sum('structure_recovery' in v for v in self.state['versions'].values()),
                'semantic': 'pending',
                'code_mention_proposals': sum(x['code_parameters_mentions'] for x in self.state.get('generated_research', {}).values()),
                'source_version_conflicts': sum(bool(r['source_version_conflict']) for r in materials),
                'excluded_synthetic': sum(r['is_synthetic'] for r in self.records.values()),
                'excluded_stale_provider_reviews': sum(r['status'] == 'stale' for r in self.review_states.values())}

    def _operational(self):
        path = _managed(self.machine, 'operational/status.json')
        try:
            data = strict_json_loads(read_regular(path, 1 << 20).decode('utf-8'), source=str(path))
        except (FileNotFoundError, IsADirectoryError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(counts := data.get('counts', {}), dict):
            return None
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
                  'counts': {k: v for k, v in counts.items()
                             if k in {'registered', 'processed', 'conflicting', 'code_mention_proposals'} and type(v) is int}}
        if isinstance(human, dict) and human.get('status') in ('human_stale', 'current'):
            for key_ in ('target_release_id', 'rendered_release_id'):
                value = human.get(key_)
                if value is not None and (not isinstance(value, str) or not HEX.fullmatch(value)):
                    return result
            result['human'] = {k: human.get(k) for k in ('status', 'target_release_id', 'rendered_release_id')}
        return result

    def source_excerpt(self, identifier, start=None, end=None):
        """Read a verbatim range from one pinned source occurrence."""
        node = self._source_nodes.get(identifier)
        if node is None:
            raise ToolError('NOT_FOUND', 'Expected an exact registered source occurrence ID')
        span = copy.deepcopy(node['source'])
        original_start, original_end = span['char_start'], span['char_end']
        start = original_start if start is None else start
        end = original_end if end is None else end
        if not original_start <= start <= end <= original_end:
            raise ToolError('INVALID_ARGUMENT', 'Requested codepoint range escapes the registered span')
        latex = node['latex'][start - original_start:end - original_start]
        if (start, end) != (original_start, original_end):
            span.update(char_start=start, char_end=end,
                        line_start=span['line_start'] + node['latex'].count('\n', 0, start-original_start),
                        line_end=span['line_start'] + node['latex'].count('\n', 0, max(start-original_start, end-original_start-1)))
        result = {'id': identifier, 'resource_uri': self._resource_uri(identifier), 'source': span,
                  'content_sha256': hash_text(latex), 'latex': latex}
        if 'structure_classification' in node:
            result['structure_classification'] = node['structure_classification']
            result['structure_status'] = 'proposed'
        material = self._normalizations.get((span['source_version_id'], span['snapshot_id']))
        if material and span['path'] == 'main.tex':
            span.pop('archive_uri', None)
            span['source_kind'] = 'normalized_unbound'
            if material.get('normalization_manifest_sha256'):
                normalized, manifest = load_normalization(self.machine, material)
                if span['file_sha256'] != normalized.sha256 or normalized.text[start:end] != latex:
                    raise ValueError('Normalized source does not match the registered occurrence')
                span['source_kind'] = 'normalized'
                result['original_ranges'] = mapped_ranges(normalized.text, manifest['source_map'], start, end)
        return result

    @staticmethod
    def _paginate(rows, args, default_limit):
        offset, limit = args.get('offset', 0), args.get('limit', default_limit)
        truncated = offset + limit < len(rows)
        return {'results': rows[offset:offset+limit], 'truncated': truncated,
                'continuation': offset+limit if truncated else None, 'total_matches': len(rows)}

    @staticmethod
    def _fit_page(data, offset, maximum):
        rows = data['results']
        low, high = 0, len(rows) - 1
        page = {**data, 'truncated': True}
        while low < high:
            count = (low + high + 1) // 2
            page.update(results=rows[:count], continuation=offset + count)
            if len(canonical(page)) <= maximum:
                low = count
            else:
                high = count - 1
        if not low:
            raise ToolError('BUDGET_TOO_SMALL', 'Increase max_chars to fit a complete result row',
                            {'required_chars': len(canonical({**page, 'results': rows[:1]})),
                             'suggestions': [{'detail': 'concise', 'limit': 1}]})
        return {**page, 'results': rows[:low], 'continuation': offset + low}

    def _research(self, identifier, revision):
        if revision is not None:
            return self.visible.get((identifier, revision))
        rows = self._visible_by_id.get(identifier, ())
        if len(rows) > 1:
            raise ToolError('AMBIGUOUS_REVISION', 'Specify an exact research revision', {'revisions': [r['revision'] for r in rows]})
        return rows[0] if rows else None

    @cached_property
    def _search_nodes(self):
        return GraphTextIndex(self.graph.source.graph['nodes'], serialize_data=canonical)

    @cached_property
    def _search_records(self):
        return [(row, canonical(row).casefold()) for row in (*self._materials.values(), *self.visible.values())]

    @cached_property
    def _reading_nodes(self):
        return [(node, text, text.casefold()) for node in sorted(self._source_nodes.values(), key=lambda n: n['id'])
                if (text := source_reading_text(node))]

    @cached_property
    def _reading_by_source(self):
        groups = {}
        for node, text, _ in self._reading_nodes:
            source = node['source']
            key_ = source['source_version_id'], source['snapshot_id']
            groups.setdefault(key_, []).append((node, text))
        return groups

    def reading_blocks(self, source_version, snapshot_id):
        """Return reading blocks for one exact registered source projection."""
        entries = self._reading_by_source.get((source_version, snapshot_id), ())
        return [(text, copy.deepcopy(node['source'])) for node, text in
                sorted(entries, key=lambda pair: (pair[0]['data'].get('order', 0), pair[0]['id']))]

    def _search(self, args):
        needle, kind = args['query'].casefold(), args.get('kind')
        if args.get('view') == 'reading':
            rows = []
            for node, text, indexed in self._reading_nodes:
                if (not kind or kind == node['kind']) and needle in indexed:
                    row = search_node_summary(node)
                    row.update(reading_excerpt=text[:320], reading_excerpt_truncated=len(text) > 320)
                    rows.append(row)
            return {**self._paginate(rows, args, min(20, self.graph.max_results)), 'view': 'reading'}
        # Page the combined space; legacy corpus search caps each call at 200.
        # Search the already validated fixed projection so there is no SQL or file input.
        rows = [search_node_summary(node) for node in self._search_nodes.matching(args['query'], kind)]
        for row, text in self._search_records:
            if (not kind or kind == row['kind']) and needle in text:
                rows.append({k: row[k] for k in ('id', 'kind', 'revision', 'status', 'source_version_id',
                                               'archive_sha256', 'field_evidence', 'effective_review') if k in row})
        return self._paginate(rows, args, min(20, self.graph.max_results))

    def _research_context(self, record, depth, max_nodes):
        pending = deque([(record, 0)])
        queued = {(record['id'], record['revision'])}
        seen, rows, edges, unresolved = set(), [], [], []
        truncated = False
        while pending:
            if len(rows) >= max_nodes:
                truncated = True
                break
            row, distance = pending.popleft()
            seen.add((row['id'], row['revision']))
            rows.append(row)
            for field in RELATIONS.get(row['kind'], {}):
                value = row['data'].get(field)
                if value is None:
                    unresolved.append({'id': row['id'], 'revision': row['revision'], 'field': field})
                    continue
                for binding in value if field.endswith('_refs') else [value]:
                    target_identity = key(binding)
                    target = self.visible.get(target_identity)
                    if not target:
                        unresolved.append({'id': row['id'], 'field': field, 'target': binding})
                    elif distance < depth:
                        edges.append({'source': {'id': row['id'], 'revision': row['revision']},
                                      'target': binding, 'relation': field})
                        if target_identity not in queued:
                            queued.add(target_identity)
                            pending.append((target, distance + 1))
                    elif target_identity not in seen:
                        truncated = True
        return {'root_id': record['id'], 'root_revision': record['revision'], 'nodes': rows,
                'edges': [e for e in edges if key(e['target']) in seen], 'unresolved': unresolved,
                'truncated': truncated, 'context_complete': not truncated and not unresolved}

    def _reported_distance(self, record, args):
        code = {'id': record['id'], 'revision': record['revision']}
        metric = {'id': args['metric_id'], 'revision': args['metric_revision']}
        if key(metric) not in self.visible:
            return []
        matching = []
        for binding in record['data'].get('distance_estimate_refs') or []:
            claim = self.visible.get(key(binding))
            if not claim:
                continue
            data = claim['data']
            subject = data.get('subject_ref')
            if subject not in (record['data'].get('check_matrix_refs') or []):
                continue
            matrix = self.visible.get(key(subject))
            if not matrix or matrix['data'].get('code_ref') != code:
                continue
            evidence = claim['field_evidence'].get('/data/lower_bound', {})
            locator = evidence.get('source_locator') or {}
            bound = data['lower_bound']
            if (data.get('metric_ref') != metric
                    or data.get('sector') != args.get('sector', 'joint')
                    or data.get('relation') not in {'exact', 'lower_bound', 'interval'}
                    or bound is None or bound < args['distance_at_least']
                    or data.get('method') is None or data.get('conditions') is None
                    or evidence.get('status') != 'known' or not locator
                    or self.source_snapshot_id(locator['source_version_id']) != locator['snapshot_id']):
                continue
            matching.append(claim)
        return matching

    def _performance(self, args):
        rows = []
        if ('coordinate' in args) != ('coordinate_name' in args) or ('selection' in args and 'coordinate' not in args):
            raise ToolError('INVALID_ARGUMENT', 'Coordinate selection needs both name and value')
        selection = args.get('selection', 'exact')
        requested = args.get('coordinate')
        if isinstance(requested, float) and not isfinite(requested):
            raise ToolError('INVALID_ARGUMENT', 'Coordinate must be a finite number')
        axis = args.get('coordinate_name')
        nearest = {}
        for record in self.visible.values():
            if record['kind'] != 'performance_data_point':
                continue
            point = record['data']
            def get(binding):
                return self.visible.get(key(binding)) if binding else None

            experiment = get(point.get('experiment_ref'))
            noise_instance = get(point.get('noise_model_instance_ref'))
            metric = get(point.get('metric_ref'))
            data = experiment['data'] if experiment else {}
            filters = {'code_id': data.get('code_ref'), 'decoder_id': data.get('decoder_ref'),
                       'noise_model_id': data.get('noise_model_ref'), 'metric_id': point.get('metric_ref')}
            if any(field in args and (binding or {}).get('id') != args[field] for field, binding in filters.items()):
                continue
            bindings = {'code': get(data.get('code_ref')), 'check_matrix': get(data.get('check_matrix_ref')),
                        'circuit': get(data.get('circuit_ref')), 'noise_model': get(data.get('noise_model_ref')),
                        'decoder': get(data.get('decoder_ref')), 'source': get(data.get('source_ref')),
                        'metric': metric, 'noise_model_instance': noise_instance, 'experiment': experiment}
            if args.get('circuit_id') and (data.get('circuit_ref') or {}).get('id') != args['circuit_id']:
                continue
            if args.get('source_version_id') and (data.get('source_ref') or {}).get('id') != args['source_version_id']:
                continue
            from .knowledge_context import current_field, comparison_group
            noise = bindings['noise_model']
            if any(field in args and (not noise or not current_field(self, noise, field) or
                                      (noise['data'].get(field) or {}).get('consideration') != args[field])
                   for field in ('idle', 'loss')):
                continue
            missing = [name for name, value in bindings.items() if value is None]
            if point['value'] is None:
                missing.append('value')
            if not noise_instance or noise_instance['data'].get('resolved_channel_parameters') is None:
                missing.append('resolved_channel_parameters')
            if not metric or any(metric['data'].get(k) is None for k in ('event', 'denominator', 'unit')):
                missing.append('metric')
            if args.get('complete_only') and missing:
                continue
            row = {'point': record, 'context': bindings, 'unresolved': missing,
                   'comparison_status': 'incomplete' if missing else 'conditions_bound',
                   'comparison_group': comparison_group(bindings, missing),
                   'verification_status': 'not_verified_by_query'}
            if axis is None:
                rows.append(row)
                continue
            coordinate = ((noise_instance or {}).get('data', {}).get('reported_coordinates') or {}).get(axis)
            if type(coordinate) not in {int, float}:
                continue
            row['selection'] = {'policy': selection, 'coordinate_name': axis, 'requested': requested,
                                'reported': coordinate, 'is_interpolated': False}
            if selection == 'exact' and coordinate == requested:
                rows.append(row)
            elif selection == 'nearest_reported' and point.get('performance_curve_ref') and get(point['performance_curve_ref']):
                curve = key(point['performance_curve_ref'])
                delta = abs(coordinate - requested)
                best = nearest.get(curve)
                if best is None or delta < best[0]:
                    nearest[curve] = (delta, [row])
                elif delta == best[0]:
                    best[1].append(row)
        if nearest:
            rows = [row for _, group in sorted(nearest.items()) for row in group[1]]
        result = self._paginate(rows, args, min(20, self.graph.max_results))
        result['comparison_policy'] = 'Exact revision bindings; no cross-experiment ranking or interpolation'
        return result

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
        page = result['results']
        related = {(row['id'], row['revision']): [] for row in page}
        if related:
            for record in self.visible.values():
                if record['kind'] not in {'software_usage', 'software_catalog_observation'}:
                    continue
                binding = record['data'].get('project_ref')
                if binding and (matches := related.get(key(binding))) is not None:
                    matches.append({field: record[field] for field in ('id', 'revision', 'kind')})
        result['results'] = [{**row, 'related_usage_or_observations': related[(row['id'], row['revision'])]}
                             for row in page]
        result['catalogue_scope'] = 'Non-exhaustive; catalogue entries do not establish use or a release version'
        return result

    def _present_discovery(self, data, requested_name, detail):
        results = data['results']
        if not isinstance(results, list):
            raise TypeError('Discovery results must be a list')
        if detail == 'concise':
            data['results'] = self.knowledge.compact_rows(results)
            if requested_name == 'qec_search':
                for field in ('retrieval', 'fallback', 'absence'):
                    data.pop(field, None)
            data['handle_scope'] = 'Handles are valid only in this pinned release; detail=full returns full provenance.'
        else:
            for row in results:
                row['handle'] = self.knowledge.handles.get(row['id'])

    def invoke(self, name, arguments):
        try:
            validator = self._tool_validators.get(name) if isinstance(name, str) else None
            if validator is None:
                raise ToolError('UNKNOWN_TOOL', 'Unknown read-only workspace tool')
            error = next(validator.iter_errors(arguments), None)
            if error:
                raise ToolError('INVALID_ARGUMENT', error.message)
            args = dict(arguments)
            if args.pop('release_id', self.release) != self.release:
                raise ToolError('SNAPSHOT_UNAVAILABLE', 'This session is pinned to a different release')
            maximum = args.pop('max_chars', self.graph.max_chars)
            if name in {'search', 'fetch'}:
                data = self.knowledge.compatible(name, args)
                if len(canonical(data)) > maximum:
                    raise ToolError('BUDGET_TOO_SMALL', 'Complete evidence exceeds session budget; use research profile ranges')
                return {'ok': True, 'data': copy.deepcopy(data)}
            requested_name = name
            detail = args.pop('detail', 'concise')
            for field in ('identifier', 'code_id', 'decoder_id', 'noise_model_id', 'metric_id', 'circuit_id'):
                if field in args:
                    args[field] = self.knowledge.expand_handle(args[field])
            from .knowledge import ALIASES
            name = ALIASES.get(name, name)
            metadata = {'scope': self.scope, 'knowledge_snapshot': self.release}
            if self.profile == 'legacy' or requested_name in {'qec_status', 'qec_workspace_status'} or detail == 'full':
                metadata['coverage'] = self._coverage
            graph_metadata = {**metadata, 'continuation': None}
            source_query = args.pop('source_query', None)
            if name == 'qec_trace':
                from .knowledge_context import bounded_trace
                data = bounded_trace(self, args, maximum, metadata)
            elif name == 'qec_get_context' and args.get('purpose'):
                from .knowledge_context import context
                data = context(self, args, maximum, metadata)
            elif name == 'qec_list_papers':
                data = self.knowledge.list_papers(args)
            elif name == 'qec_fetch':
                data = self.knowledge.fetch(args)
            elif name == 'qec_search':
                data = self.knowledge.search(args)
            elif name == 'qecgraph_search':
                if not args['query'].strip():
                    raise ToolError('INVALID_ARGUMENT', 'Search query must not be blank')
                data = self._search(args)
            elif name == 'qec_workspace_status':
                data = {'operational_status': self._operational()}
                if requested_name == 'qec_status':
                    data['knowledge_coverage'] = self.knowledge.coverage()
                    from .llm.review import read_decisions
                    decisions = read_decisions(self.registry, self.state)
                    data['ai_review_decisions'] = {'registered': len(decisions),
                        'effective_status': dict(Counter(row['effective_status'] for row in decisions)),
                        'identity_assurance': 'Local self-assertions; no authenticated human identity'}
            elif name == 'qec_get_asset':
                uri = args['identifier']
                if uri not in self.assets:
                    raise ToolError('NOT_FOUND', 'Expected an asset ID bound to an eligible record in this release')
                raw = asset_bytes(self.registry, uri)
                offset, length = args.get('offset', 0), args.get('length', 8192)
                if offset > len(raw):
                    raise ToolError('INVALID_ARGUMENT', 'Asset offset exceeds its byte length')
                end = min(offset + length, len(raw))
                data = {'asset_id': uri, 'sha256': uri.rsplit(':', 1)[1], 'size_bytes': len(raw),
                        'byte_start': offset, 'byte_end': end,
                        'encoding': 'base64', 'content': base64.b64encode(raw[offset:end]).decode('ascii'),
                        'truncated': end < len(raw), 'continuation': end if end < len(raw) else None}
            elif name == 'qec_get_source':
                data = self.source_excerpt(args['identifier'], args.get('char_start'), args.get('char_end'))
            elif name == 'qec_get_context':
                identifier = args['identifier']
                entity = self._research(identifier, args.get('revision'))
                if entity:
                    data = self._research_context(entity, args.get('depth', min(2, self.graph.max_depth)),
                                                  args.get('max_nodes', self.graph.max_nodes))
                elif args.get('revision') or identifier in self._research_ids:
                    raise ToolError('NOT_FOUND', 'No eligible revision in this release')
                else:
                    response = self.graph.invoke('qecgraph_context', {**args, 'max_chars': maximum},
                                                 output_metadata=graph_metadata)
                    if not response['ok']:
                        return response
                    data = response['data']
            elif name == 'qec_get_entity':
                identifier = args['identifier']
                revision = args.get('revision')
                entity = self._materials.get(identifier) if revision is None else None
                entity = entity or self._research(identifier, revision)
                if entity:
                    data = {'entity': entity}
                elif revision is not None or identifier in self._research_ids:
                    raise ToolError('NOT_FOUND', 'No eligible revision in this release')
                else:
                    response = self.graph.invoke('qecgraph_show', {'identifier': identifier, 'max_chars': maximum},
                                                 output_metadata=graph_metadata)
                    if not response['ok']:
                        return response
                    data = response['data']
            elif name == 'qec_find_codes':
                extended = {k: args.pop(k) for k in ('k_min', 'k_max', 'classification', 'check_weight_max',
                                                     'check_weight_sector', 'check_weight_scope') if k in args}
                offset = args.pop('offset', 0)
                limit = args.pop('limit', min(20, self.graph.max_results))
                policy = args.pop('evidence_policy', 'verified')
                if args.get('n_min', 0) > args.get('n_max', 1000000000):
                    raise ToolError('INVALID_ARGUMENT', 'n_min exceeds n_max')
                if 'distance_at_least' in args and 'metric_id' not in args:
                    raise ToolError('INVALID_ARGUMENT', 'A distance hard condition needs an exact metric_id')
                if 'metric_revision' in args and 'distance_at_least' not in args:
                    raise ToolError('INVALID_ARGUMENT', 'metric_revision requires a distance hard condition')
                if policy == 'source_reported':
                    if 'distance_at_least' in args and 'metric_revision' not in args:
                        raise ToolError('INVALID_ARGUMENT', 'Source-reported hard bounds require exact metric ID and revision')
                    legacy = {'results': [], 'truncated': False,
                              'evidence_policy': 'Source-reported bound with a current source locator, metric and check matrix'}
                else:
                    legacy = codes(self.machine, registry_revision=self.release, check_live_lean=False,
                                   limit=None, evidence_policy='verified', **args)
                rows = legacy['results']
                for record in self.visible.values():
                    if record['kind'] != 'quantum_code':
                        continue
                    n = record['data'].get('n')
                    if ('n_min' in args and (n is None or n < args['n_min'])) or (
                            'n_max' in args and (n is None or n > args['n_max'])):
                        continue
                    if 'distance_at_least' in args:
                        if policy != 'source_reported':
                            continue
                        matching = self._reported_distance(record, args)
                        if not matching:
                            continue
                        rows.append({'record': record, 'distance_estimates': matching})
                    else:
                        rows.append(record)
                if extended:
                    from .knowledge_context import filter_codes
                    rows = filter_codes(self, rows, extended)
                data = self._paginate(rows, {'offset': offset, 'limit': limit}, limit)
                data['legacy_scan_truncated'] = legacy['truncated']
                data['evidence_policy'] = policy
            elif name == 'qec_find_performance':
                if args.get('source_version_id'):
                    self.knowledge.version(args['source_version_id'])
                data = self._performance(args)
            elif name == 'qec_find_software':
                data = self._software(args)
            else:
                response = self.graph.invoke(name, {**args, 'max_chars': maximum}, output_metadata=graph_metadata)
                if not response['ok']:
                    return response
                data = response['data']
            if requested_name in {'qec_query_codes', 'qec_query_performance'}:
                data['query_semantics'] = 'enumeration of explicit records in this fixed release'
                data['source_fallback'] = {'tool': 'qec_search', 'reason': 'Unextracted materials may contain additional candidates'}
                if source_query:
                    data['source_candidates'] = self.knowledge.search({'query': source_query, 'limit': min(5, self.graph.max_results)})
                data['field_coverage'] = self.knowledge.coverage()['field_states']
            if requested_name in {'qec_search', 'qec_list_papers'}:
                self._present_discovery(data, requested_name, detail)
            data.update(metadata)
            data.setdefault('truncated', False)
            data.setdefault('continuation', None)
            if len(canonical(data)) > maximum:
                if 'total_matches' in data and data.get('results'):
                    data = self._fit_page(data, arguments.get('offset', 0), maximum)
                else:
                    raise ToolError('BUDGET_TOO_SMALL', 'Request a smaller source range or a navigation view',
                                    {'required_chars': len(canonical(data)), 'session_max_chars': self.graph.max_chars,
                                     'suggestions': [{'view': 'outline'}, {'depth': 0, 'max_nodes': 1}]})
            return {'ok': True, 'data': copy.deepcopy(data)}
        except ToolError as exc:
            return {'ok': False, 'error': {'code': exc.code, 'message': str(exc), 'details': exc.details,
                                          'scope': self.scope.copy()}}
        except (TypeError, KeyError) as exc:
            import logging
            from .core.errors import log_internal_failure
            reference = log_internal_failure(logging.getLogger(__name__), 'workspace query', exc)
            return copy.deepcopy({'ok': False, 'error': {'code': 'INTERNAL_ERROR',
                'message': 'Internal query failure; inspect the diagnostic reference', 'reference': reference, 'scope': self.scope}})
        except (OSError, ValueError):
            return {'ok': False, 'error': {'code': 'QUERY_ERROR', 'message': 'Machine release could not be read',
                                          'scope': self.scope.copy()}}
