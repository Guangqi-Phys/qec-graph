"""Deterministic assembly of a canonical TeX entry from a normalization plan.

The model can choose *which* source segments belong in the entry document, but
the assembler copies those bytes verbatim and records a source map. It never
rewrites scientific text.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from ..core.graph import canonical, hash_text
from ..source.package import SourceTree
from .skills import load_skill


class NormalizationError(ValueError):
    """A plan cannot be assembled into a faithful normalized document."""


@dataclass(frozen=True)
class NormalizedSource:
    source_tree_hash: str
    data: bytes
    plan: dict
    segments: tuple[dict, ...]

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()

    @property
    def text(self):
        return self.data.decode('utf-8')


_DOCUMENT_CLASS = re.compile(rb'\\documentclass\s*(?:\[[^\]]*\]\s*)?\{')
_BEGIN_DOCUMENT = re.compile(rb'\\begin\s*\{document\}')
_END_DOCUMENT = re.compile(rb'\\end\s*\{document\}')
_APPENDIX = re.compile(rb'\\appendix\b')
_LABEL = re.compile(rb'\\label\s*\{([^{}]+)\}')


def _parts(raw):
    begin = _BEGIN_DOCUMENT.search(raw)
    if begin is None or _DOCUMENT_CLASS.search(raw) is None:
        raise NormalizationError('source is not a complete TeX document')
    end = _END_DOCUMENT.search(raw, begin.end())
    body_end = end.start() if end else len(raw)
    appendix = _APPENDIX.search(raw, begin.end(), body_end)
    appendix_start = appendix.start() if appendix else body_end
    return {
        'preamble': (0, begin.end()),
        'body': (begin.end(), appendix_start),
        'appendix': (appendix_start, body_end),
    }


def _span(raw, operation):
    part = operation.get('part')
    if part in {None, 'body'}:
        return _parts(raw)['body']
    if part in {'preamble', 'appendix'}:
        return _parts(raw)[part]
    raise NormalizationError(f'unsupported normalization part: {part!r}')


def inventory(tree: SourceTree):
    documents = []
    tex_files = []
    assets = []
    for name, raw in sorted(tree.files.items()):
        if not name.lower().endswith('.tex'):
            assets.append(name)
            continue
        tex_files.append(name)
        try:
            parts = _parts(raw)
        except NormalizationError:
            continue
        documents.append({'path': name, 'bytes': len(raw),
                          'has_appendix': b'\\appendix' in raw,
                          'parts': {key: {'byte_start': start, 'byte_end': end}
                                    for key, (start, end) in parts.items()}})
    payload = {'schema': 'qecgraph.normalization_inventory',
               'source_tree_hash': tree.digest, 'documents': documents,
               'tex_files': tex_files, 'assets': assets}
    payload['inventory_sha256'] = hash_text(canonical(payload))
    return payload


def single_root_plan(tree: SourceTree):
    candidates = tree.entrypoints()
    if len(candidates) != 1:
        raise NormalizationError('single-root normalization requires exactly one complete TeX root')
    path = candidates[0]
    return {'status': 'ready',
            'documents': [{'path': path, 'role': 'main', 'reason': 'unique complete TeX root'}],
            'operations': [{'op': 'use_document', 'source': path}],
            'label_renames': {}, 'unresolved': []}


def _check_plan(tree, plan):
    try:
        schema = load_skill('normalize_package').schema
        Draft202012Validator(schema).validate(plan)
    except Exception as exc:
        raise NormalizationError(f'invalid normalization plan: {exc}') from exc
    if plan['status'] != 'ready':
        raise NormalizationError('normalization plan is not ready')
    if not plan['operations']:
        raise NormalizationError('normalization plan has no operations')
    if any(operation['op'] == 'use_document' for operation in plan['operations']) and len(plan['operations']) != 1:
        raise NormalizationError('use_document cannot be combined with other operations')
    for operation in plan['operations']:
        if operation['op'] not in {'use_document', 'use_preamble', 'include_body', 'append_appendix',
                                   'append_body', 'include_asset'}:
            raise NormalizationError(f"unsupported operation: {operation['op']}")
        if operation['source'] not in tree.files:
            raise NormalizationError(f"operation references missing source: {operation['source']}")


def assemble(tree: SourceTree, plan: Mapping[str, Any]):
    plan = dict(plan)
    _check_plan(tree, plan)
    output = bytearray()
    segments = []
    labels = {}
    for operation in plan['operations']:
        path = operation['source']
        raw = tree.files[path]
        if operation['op'] == 'include_asset':
            continue
        if operation['op'] == 'use_document':
            start, end = 0, len(raw)
        elif operation['op'] == 'append_appendix' and operation.get('part') is None:
            start, end = _parts(raw)['appendix']
        elif operation['op'] == 'append_body' and operation.get('part') is None:
            start, end = _parts(raw)['body']
        elif operation['op'] == 'use_preamble':
            start, end = _parts(raw)['preamble']
        else:
            start, end = _span(raw, operation)
        chunk = raw[start:end]
        if not chunk:
            continue
        if output and not output.endswith(b'\n') and not chunk.startswith(b'\n'):
            output += b'\n'
            segments.append({'normalized': {'byte_start': len(output) - 1, 'byte_end': len(output)},
                             'origin': None, 'kind': 'generated'})
        out_start = len(output)
        output += chunk
        segments.append({'normalized': {'byte_start': out_start, 'byte_end': len(output)},
                         'origin': {'path': path, 'byte_start': start, 'byte_end': end},
                         'kind': 'original'})
        for match in _LABEL.finditer(chunk):
            label = match.group(1).decode('utf-8', 'replace')
            if label in labels and labels[label] != (path, start + match.start()):
                raise NormalizationError(f'duplicate label after normalization: {label}')
            labels[label] = (path, start + match.start())
    if not output:
        raise NormalizationError('normalization produced an empty document')
    if b'\\end{document}' not in output:
        if not output.endswith(b'\n'):
            output += b'\n'
        out_start = len(output)
        output += b'\\end{document}\n'
        segments.append({'normalized': {'byte_start': out_start, 'byte_end': len(output)},
                         'origin': None, 'kind': 'generated'})
    try:
        output.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise NormalizationError('normalized source is not valid UTF-8') from exc
    return NormalizedSource(source_tree_hash=tree.digest, data=bytes(output), plan=plan,
                            segments=tuple(segments))


@dataclass(frozen=True)
class NormalizationResult:
    source: NormalizedSource
    inventory: dict
    ai_result: object | None
    skill_version: int


def _excerpt(raw, start, end, limit=1200):
    data = raw[start:end]
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return ''
    if len(text) <= limit:
        return text
    return text[:limit] + '\n...[truncated]...\n' + text[-min(300, limit // 3):]


def normalization_evidence(tree: SourceTree, inventory_data):
    """Build a bounded, source-only evidence pack for the normalization skill."""
    documents = []
    for document in inventory_data['documents']:
        raw = tree.files[document['path']]
        parts = document['parts']
        documents.append({
            **document,
            'excerpts': {
                'preamble': _excerpt(raw, parts['preamble']['byte_start'], parts['preamble']['byte_end']),
                'body': _excerpt(raw, parts['body']['byte_start'], parts['body']['byte_end']),
                'appendix': _excerpt(raw, parts['appendix']['byte_start'], parts['appendix']['byte_end']),
            },
        })
    return {'schema': 'qecgraph.normalization_evidence',
            'source_tree_hash': tree.digest, 'documents': documents}


def normalize_package(tree: SourceTree, client, *, extra_skills_dir=None, use_cache=True):
    """Return a source-faithful normalized entry, using AI only for ambiguity."""
    from .skills import load_skill  # local import keeps the assembler dependency-light

    inventory_data = inventory(tree)
    roots = tree.entrypoints()
    if len(roots) == 1:
        plan = single_root_plan(tree)
        normalized = assemble(tree, plan)
        return NormalizationResult(normalized, inventory_data, None, 1)
    if len(roots) == 0:
        raise NormalizationError('no complete TeX root was found')
    skill = load_skill('normalize_package', extra_skills_dir)
    evidence = normalization_evidence(tree, inventory_data)
    messages = [
        {'role': 'system', 'content': skill.prompt},
        {'role': 'user', 'content': json.dumps(evidence, ensure_ascii=False, sort_keys=True)},
    ]
    from .providers.base import Message
    ai_result = client.complete_json([Message(**message) for message in messages], skill.schema,
                                     use_cache=use_cache)
    plan = ai_result.data
    normalized = assemble(tree, plan)
    return NormalizationResult(normalized, inventory_data, ai_result, skill.version)
