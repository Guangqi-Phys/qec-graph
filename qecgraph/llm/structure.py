"""Ask for a bounded structure plan, then verify it locally."""
from __future__ import annotations

from ..core.graph import canonical
from ..source.structure import STRUCTURE_SCHEMA, STRUCTURE_SKILL, STRUCTURE_VERSION, parsed_structure, validate_plan
from .client import BudgetExceeded
from .providers.base import Message
from .skills import load_skill


def recover_structure(evidence, client):
    skill = load_skill(STRUCTURE_SKILL)
    if skill.version != STRUCTURE_VERSION:
        raise ValueError('Unsupported structure recovery skill version')
    body_chars = evidence.offsets[evidence.last_line] - evidence.offsets[evidence.first_line - 1]
    if body_chars > client.config.max_input_chars:
        raise BudgetExceeded('The literal source body exceeds [ai].max_input_chars')
    messages = [Message('system', skill.system_prompt), Message('user', canonical(evidence.request()))]

    def validate(plan):
        validate_plan(evidence, plan)

    result = client.complete_json(messages, skill.schema, validate=validate, max_output_tokens=8192)
    return parsed_structure(evidence, {
        'schema': STRUCTURE_SCHEMA, 'entry': evidence.entry, 'source_sha256': evidence.sha256,
        'skill': skill.name, 'skill_version': skill.version, 'model': result.model,
        'prompt_sha256': result.prompt_sha256, 'plan': result.data,
    })
