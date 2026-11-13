"""Publish source-bound AI output as research records with explicit provenance."""
from __future__ import annotations

from ..core.graph import canonical, hash_text
from ..core.language import require_english
from ..llm.extract import validate_extraction
from ..llm.review import proposal_bindings, read_bound_proposal
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
    for binding, material in proposal_bindings(state).values():
        if binding['skill'] not in KINDS:
            continue
        proposal = read_bound_proposal(registry, binding, material)
        try:
            require_english(proposal)
        except ValueError:
            continue  # The next opted-in sync refreshes legacy non-English output.
        validate_extraction(binding['skill'], {k: proposal[k] for k in ('items', 'unresolved', 'paper') if k in proposal})
        for item in proposal['items']:
            record = _record(proposal, item, binding['proposal_sha256'])
            records[record['id']] = record
    if records:
        stage_records(registry, state, records.values())
    state['ai_research_records'] = {identifier: record['revision'] for identifier, record in records.items()}
