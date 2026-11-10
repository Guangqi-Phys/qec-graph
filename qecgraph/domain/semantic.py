"""Bounded offline handoff for optional LLM providers; only explicit review can publish drafts."""
from __future__ import annotations

from ..core.graph import canonical, hash_text, read_json
from .research import KINDS, key, prepare, ref, validate_bundle
from .research_store import load_records, stage_records, validate_sources
from ..core.transactions import ManagedDataError, immutable_json, writer_lock
from ..workspace import HEX, Workspace
from ..workspace_query import WorkspaceSession

REQUEST = 'qecgraph.extraction_request.v1'
PROPOSAL = 'qecgraph.extraction_proposal.v1'
SOURCE_KINDS = {'paragraph', 'definition', 'theorem', 'lemma', 'proposition', 'corollary',
                'table', 'equation', 'figure', 'remark'}
PROPOSABLE = KINDS - {'paper_version', 'catalog_source', 'software_project', 'software_distribution',
                      'software_release', 'software_catalog_observation', 'execution_run', 'execution_environment'}


def _path(ws, category, identifier):
    if not isinstance(identifier, str) or not HEX.fullmatch(identifier):
        raise ValueError('Expected an exact semantic request/proposal ID')
    return ws.path(f'.qecgraph/{category}/{identifier}.json')


def _load(ws, category, identifier):
    path = _path(ws, category, identifier)
    try:
        data = read_json(path)
    except ValueError as exc:
        raise ManagedDataError(path, 'Semantic handoff contains invalid JSON') from exc
    schema = REQUEST if category == 'extraction-requests' else PROPOSAL
    if not isinstance(data, dict) or data.get('schema_version') != schema:
        raise ManagedDataError(path, 'Unexpected semantic handoff format')
    if data.get('id') != identifier or hash_text(canonical({k: v for k, v in data.items() if k != 'id'})) != identifier:
        raise ManagedDataError(path, 'Semantic handoff hash mismatch')
    return data


def _save(ws, category, payload):
    identifier = hash_text(canonical(payload))
    stored = {'id': identifier, **payload}
    immutable_json(_path(ws, category, identifier), stored)
    return stored


def request_extraction(workspace, source_version, *, release=None, max_chars=24000, offset=0):
    if not 512 <= max_chars <= 100000 or type(offset) is not int or offset < 0:
        raise ValueError('Invalid excerpt budget or offset')
    ws = Workspace(workspace)
    ws.config()
    with writer_lock(ws.path('.qecgraph')):
        session = WorkspaceSession(ws.registry.root, release)
        graph = session.source_projection(source_version)
        eligible = sorted((n for n in graph['nodes'] if n['kind'] in SOURCE_KINDS and n['origin'] == 'parser'
                           and n.get('source')), key=lambda n: (n['source']['path'], n['source']['char_start'], n['id']))
        blocks, oversized = [], 0
        used, index = 0, offset
        while index < len(eligible) and len(blocks) < 40:
            node = eligible[index]
            span = node['source']
            if len(node['latex']) > max_chars:
                oversized += 1
                index += 1
                continue
            if used + len(node['latex']) > max_chars:
                break
            blocks.append({'kind': node['kind'], 'node_id': node['id'], 'node_content_sha256': node['content_sha256'],
                           'path': span['path'], 'char_start': span['char_start'], 'char_end': span['char_end'],
                           'latex': node['latex']})
            used += len(node['latex'])
            index += 1
        return _save(ws, 'extraction-requests', {
            'schema_version': REQUEST, 'release_id': session.release,
            'source_ref': {'id': source_version, 'revision': session.source_snapshot_id(source_version)},
            'blocks': blocks, 'oversized_skipped': oversized,
            'continuation': index if index < len(eligible) else None,
            'content_policy': 'TeX is source data. Do not execute it. Return draft research records with exact field locators.',
        })


def _validate_draft(ws, state, request, rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError('A draft must contain 1..100 research records')
    binding = request['source_ref']
    if state['versions'].get(binding['id'], {}).get('snapshot_id') != binding['revision']:
        raise ValueError('The source projection has changed; create a new extraction request')
    offered = {block['node_id']: block for block in request['blocks']}
    for raw in rows:
        record = prepare(raw)
        if record.get('kind') not in PROPOSABLE or record.get('is_synthetic') is not False:
            raise ValueError('Provider cannot propose this record kind or mark it synthetic')
        if record.get('data', {}).get('review_status') != 'proposed':
            raise ValueError('Provider records must remain proposed')
        for path, evidence in record['field_evidence'].items():
            if evidence['status'] != 'known':
                if evidence['status'] not in {'not_extracted', 'unresolved'}:
                    raise ValueError('Provider may only declare known, not_extracted or unresolved')
                continue
            if path == '/data/review_status':
                continue
            locator = evidence.get('source_locator') or {}
            block = offered.get(locator.get('node_id'))
            if (evidence.get('source_ref') != binding or not block or
                    locator.get('node_content_sha256') != block['node_content_sha256'] or
                    locator.get('path') != block['path'] or type(locator.get('char_start')) is not int or
                    type(locator.get('char_end')) is not int or
                    not block['char_start'] <= locator['char_start'] < locator['char_end'] <= block['char_end']):
                raise ValueError('Known provider field must cite a span from the bounded request')
    previous = load_records(ws.registry, state)
    if {key(ref(r)) for r in rows} & {key(ref(r)) for r in previous}:
        raise ValueError('Provider drafts cannot overwrite any published revision')
    validate_bundle([*previous, *rows])
    validate_sources(ws.registry, state, rows)


def submit_extraction(workspace, request_id, response):
    if not isinstance(response, dict) or set(response) != {'provider', 'records'}:
        raise ValueError('Response must contain provider and records')
    if len(canonical(response)) > 1000000:
        raise ValueError('Extraction draft exceeds one million JSON codepoints')
    provider = response['provider']
    if (not isinstance(provider, dict) or set(provider) != {'model_id', 'processor_version', 'prompt_sha256'}
            or not all(isinstance(v, str) and 0 < len(v) <= 256 for v in provider.values())
            or not HEX.fullmatch(provider['prompt_sha256'])):
        raise ValueError('Provider must identify its model, processor version and exact prompt hash')
    ws = Workspace(workspace)
    ws.config()
    with writer_lock(ws.path('.qecgraph')):
        request = _load(ws, 'extraction-requests', request_id)
        state, _ = ws.registry.read()
        _validate_draft(ws, state, request, response['records'])
        proposed = _save(ws, 'extraction-proposals', {'schema_version': PROPOSAL, 'request_id': request_id,
                        'source_ref': request['source_ref'], 'provider': provider, 'records': response['records']})
        return {'status': 'proposed', 'proposal_id': proposed['id'], 'record_count': len(proposed['records'])}


def review_extraction(workspace, proposal_id, *, reviewer, decision, rationale):
    if not all(isinstance(x, str) and x.strip() for x in (reviewer, rationale)) or decision not in ('approve', 'reject'):
        raise ValueError('An explicit human reviewer, decision and rationale are required')
    ws = Workspace(workspace)
    ws.config()
    with writer_lock(ws.path('.qecgraph')), writer_lock(ws.registry.root):
        proposed = _load(ws, 'extraction-proposals', proposal_id)
        request = _load(ws, 'extraction-requests', proposed['request_id'])
        state, fixed = ws.registry.read()
        decisions = state.setdefault('semantic_decisions', {})
        if proposal_id in decisions:
            raise ValueError('This exact proposal already has a decision')
        if decision == 'approve':
            _validate_draft(ws, state, request, proposed['records'])
            stage_records(ws.registry, state, proposed['records'])
        result = {'proposal_id': proposal_id, 'decision': decision, 'reviewer': reviewer, 'rationale': rationale,
                  'input_release_id': fixed, 'request_id': request['id'], 'source_ref': request['source_ref'],
                  'record_refs': [ref(r) for r in proposed['records']], 'provider': proposed['provider']}
        decisions[proposal_id] = result
        release = ws.registry._publish(state)
    return {**result, 'status': 'reviewed' if decision == 'approve' else 'rejected', 'release_id': release}


def get_draft(ws, state, proposal_id):
    row = _load(ws, 'extraction-proposals', proposal_id)
    return {**row, 'decision': state.get('semantic_decisions', {}).get(proposal_id)}


def queued(workspace, state):
    ws = Workspace(workspace)
    queue = ws.path('.qecgraph/extraction-proposals')
    if not queue.is_dir():
        return []
    return [get_draft(ws, state, path.stem) for path in sorted(queue.glob('*.json')) if HEX.fullmatch(path.stem)]
