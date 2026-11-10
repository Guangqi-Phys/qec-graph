"""Program-side validation and provenance for AI extraction proposals."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import LLMResult

from .errors import LLMError


class ExtractionError(LLMError):
    """An AI extraction result is structurally or semantically unusable."""


@dataclass(frozen=True)
class ExtractionResult:
    skill: str
    data: dict
    proposal: dict
    ai_result: LLMResult


def _strings(value, field):
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise ExtractionError(f'{field} must be a nonempty array of strings')


def _confidence(value, field):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
        raise ExtractionError(f'{field} must be between 0 and 1')


def _validate_theorems(data):
    seen = set()
    for item in data['items']:
        label = item.get('label', '').strip()
        if not label:
            raise ExtractionError('theorem label must not be empty')
        if label in seen:
            raise ExtractionError(f'duplicate theorem label: {label}')
        seen.add(label)
        if not item.get('statement', '').strip():
            raise ExtractionError(f'theorem {label} has an empty statement')
        _strings(item.get('source_refs'), f'theorem {label} source_refs')
        for index, hypothesis in enumerate(item.get('hypotheses', [])):
            if not hypothesis.get('text', '').strip():
                raise ExtractionError(f'theorem {label} hypothesis {index} is empty')
            _confidence(hypothesis.get('confidence'), f'theorem {label} hypothesis confidence')
            if hypothesis.get('kind') == 'explicit' and not hypothesis.get('source_refs'):
                raise ExtractionError(f'theorem {label} explicit hypothesis {index} lacks source_refs')
        if item.get('confidence') is not None:
            _confidence(item['confidence'], f'theorem {label} confidence')


def _validate_assumptions(data):
    for item in data['items']:
        if not item.get('claim', '').strip() or not item.get('text', '').strip():
            raise ExtractionError('assumption claim and text are required')
        _confidence(item.get('confidence'), 'assumption confidence')
        if item.get('kind') == 'explicit':
            if not item.get('source_refs'):
                raise ExtractionError('explicit assumption source_refs must not be empty')
            _strings(item.get('source_refs'), 'explicit assumption source_refs')


def _validate_data(data):
    for item in data['items']:
        if not item.get('metric', '').strip():
            raise ExtractionError('data metric is required')
        value = item.get('value')
        if isinstance(value, bool) or not isinstance(value, (int, float, str)) or value == '':
            raise ExtractionError('data value must be a number or nonempty string')
        _strings(item.get('source_refs'), 'data source_refs')
        if item.get('conditions') is not None and not isinstance(item['conditions'], dict):
            raise ExtractionError('data conditions must be an object')


def validate_extraction(skill, data):
    if not isinstance(data, dict):
        raise ExtractionError('extraction result must be an object')
    if not isinstance(data.get('items'), list) or not isinstance(data.get('unresolved'), list):
        raise ExtractionError('extraction result must contain items and unresolved arrays')
    if skill == 'extract_theorems':
        _validate_theorems(data)
    elif skill == 'extract_assumptions':
        _validate_assumptions(data)
    elif skill == 'extract_data':
        _validate_data(data)
    else:
        raise ExtractionError(f'unsupported extraction skill: {skill}')
    return data


def make_proposal(skill, data, *, source_tree_hash, ai_result, normalization_id=None):
    data = validate_extraction(skill, copy.deepcopy(data))
    if not isinstance(source_tree_hash, str) or len(source_tree_hash) != 64:
        raise ExtractionError('source_tree_hash must be a 64-character digest')
    proposal = {
        'schema': 'qecgraph.ai.proposal',
        'skill': skill,
        'source_tree_hash': source_tree_hash,
        'normalization_id': normalization_id,
        'review_status': 'proposed',
        'items': data['items'],
        'unresolved': data['unresolved'],
        'provenance': {
            'run_id': ai_result.run_id,
            'model': ai_result.model,
            'usage': ai_result.usage,
            'prompt_sha256': ai_result.prompt_sha256,
            'request_id': ai_result.request_id,
            'cached': ai_result.cached,
        },
    }
    return proposal


_EXTRACTION_SKILLS = {'extract_theorems', 'extract_assumptions', 'extract_data'}


_LINE_REF = re.compile(r'(.+):([1-9][0-9]{0,8})(?:-([1-9][0-9]{0,8}))?')


def validate_source_refs(normalized, projection_path, skill, data):
    """Resolve model citations within supplied evidence and check verbatim claims."""
    if not data['items']:
        return
    text = normalized.text
    line_offsets = [0, *(match.end() for match in re.finditer(r'\n', text)), len(text)]
    originals = []
    offset = 0
    for segment in normalized.segments:
        span = segment['normalized']
        end = offset + len(normalized.data[span['byte_start']:span['byte_end']].decode('utf-8'))
        if segment['origin'] is not None:
            originals.append((offset, end))
        offset = end

    def check(row, verbatim=None):
        excerpts = []
        for reference in row.get('source_refs', []):
            match = _LINE_REF.fullmatch(reference) if isinstance(reference, str) else None
            if not match or match[1] != projection_path:
                raise ExtractionError('AI source reference must name the supplied projection and line range')
            first, last = int(match[2]), int(match[3] or match[2])
            if not first <= last < len(line_offsets):
                raise ExtractionError('AI source reference line range is out of bounds')
            start, end = line_offsets[first - 1], line_offsets[last]
            chunks = [text[max(start, a):min(end, b)] for a, b in originals if start < b and a < end]
            if not any(chunk.strip() for chunk in chunks):
                raise ExtractionError('AI source reference contains no original text')
            excerpts.extend(chunks)
        if verbatim and not any(verbatim in excerpt for excerpt in excerpts):
            raise ExtractionError('AI statement or explicit assumption is not verbatim in its cited source')

    for item in data['items']:
        verbatim = item['statement'] if skill == 'extract_theorems' else (
            item['text'] if skill == 'extract_assumptions' and item.get('kind') == 'explicit' else None)
        check(item, verbatim)
        for hypothesis in item.get('hypotheses', []):
            check(hypothesis, hypothesis['text'] if hypothesis['kind'] == 'explicit' else None)


def extract(normalized, client, skill_name, *, projection_path='main.tex', extra_skills_dir=None, use_cache=True):
    """Ask one extraction skill for a proposal over a normalized source."""
    from .normalize import NormalizedSource
    from .skills import load_skill
    from .providers.base import Message

    if not isinstance(normalized, NormalizedSource):
        raise ExtractionError('normalized source is required')
    if skill_name not in _EXTRACTION_SKILLS:
        raise ExtractionError(f'unsupported extraction skill: {skill_name}')
    skill = load_skill(skill_name, extra_skills_dir)
    evidence = {
        'schema': 'qecgraph.extraction_evidence',
        'source_tree_hash': normalized.source_tree_hash,
        'normalized_sha256': normalized.sha256,
        'projection_path': projection_path,
        'text': normalized.text,
        'segments': list(normalized.segments),
    }
    content = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    checked = None

    def validate(data):
        nonlocal checked
        validate_extraction(skill_name, data)
        validate_source_refs(normalized, projection_path, skill_name, data)
        checked = data

    ai_result = client.complete_json(
        [Message('system', skill.system_prompt), Message('user', content)], skill.schema,
        use_cache=use_cache, validate=validate)
    if checked is not ai_result.data:
        validate(ai_result.data)
    proposal = make_proposal(skill_name, ai_result.data,
                             source_tree_hash=normalized.source_tree_hash,
                             ai_result=ai_result, normalization_id=normalized.sha256)
    proposal['projection_path'] = projection_path
    proposal['provenance']['skill_version'] = skill.version
    return ExtractionResult(skill=skill_name, data=ai_result.data, proposal=proposal,
                            ai_result=ai_result)
