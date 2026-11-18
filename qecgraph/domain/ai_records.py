"""Publish source-bound AI output as research records with explicit provenance."""
from __future__ import annotations

from ..core.graph import canonical, hash_text
from ..llm.review import current_proposals
from .research import make_record
from .research_store import stage_records


KINDS = {
    'extract_theorems': 'theorem',
    'extract_assumptions': 'assumption',
    'extract_data': 'data',
    'extract_thoughts': 'thought',
}


def _record(proposal, item, digest):
    source = {'id': proposal['source_version_id'], 'revision': proposal['snapshot_id']}
    skill = proposal['skill']
    provenance = proposal['provenance']
    data = {
        'source_ref': source,
        'extraction_kind': KINDS[skill],
        'extracted': item,
        'source_refs': item.get('source_refs') or [],
        'provenance': {'artifact_sha256': digest, 'skill': skill, 'model': provenance['model'],
                       'skill_version': provenance.get('skill_version'), 'prompt_sha256': provenance['prompt_sha256']},
    }
    identifier = 'ai-extraction:' + hash_text(canonical([source['id'], skill, item]))
    revision = hash_text(canonical(data))
    record = make_record('ai_extraction', identifier, revision, data, source=source, method='ai_extracted',
                         origin='ai_extracted')
    return record


def stage_ai_records(registry, state):
    """Project the current English extraction artifacts into canonical records."""
    records = {}
    for binding, proposal in current_proposals(registry, state, skills=KINDS):
        for item in proposal['items']:
            record = _record(proposal, item, binding['proposal_sha256'])
            records[record['id']] = record
    if records:
        stage_records(registry, state, records.values())
    if records or 'ai_research_records' in state:
        state['ai_research_records'] = {identifier: record['revision'] for identifier, record in records.items()}
