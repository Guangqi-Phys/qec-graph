"""Write private, auditable normalization artifacts under a workspace."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..core.graph import canonical, hash_text, read_json
from ..core.transactions import atomic_bytes, immutable_json
from ..core.fs import managed_path, regular_managed_path
from .normalize import NormalizationResult, NormalizedSource


def write_normalization(root, result: NormalizationResult, tree, *, run_id=None):
    root = Path(root)
    source_hash = result.source.source_tree_hash
    if not source_hash or any(ch not in '0123456789abcdef' for ch in source_hash) or len(source_hash) != 64:
        raise ValueError('normalization source hash must be a 64-character lowercase hex digest')
    if run_id is None:
        run_id = (result.ai_result.run_id if result.ai_result is not None
                  else hash_text(json.dumps(result.source.plan, sort_keys=True)))
    if tree.digest != source_hash:
        raise ValueError('Normalization source tree identity mismatch')
    source_map = _source_map(result.source.data, result.source.segments, tree)
    target = _normalization_path(root, {'source_tree_hash': source_hash, 'normalization_id': run_id})
    target.mkdir(parents=True, exist_ok=True)
    normalized_path = target / 'main.tex'
    if normalized_path.exists():
        if normalized_path.read_bytes() != result.source.data:
            raise ValueError('Normalization run already binds different TeX bytes')
    else:
        atomic_bytes(normalized_path, result.source.data)
    immutable_json(target / 'plan.json', result.source.plan)
    manifest = {
        'schema': 'qecgraph.normalization',
        'source_tree_hash': source_hash,
        'run_id': run_id,
        'normalized_sha256': result.source.sha256,
        'plan_sha256': hash_text(json.dumps(result.source.plan, sort_keys=True)),
        'skill_version': result.skill_version,
        'segments': list(result.source.segments),
        'source_map': source_map,
        'ai': None if result.ai_result is None else {
            'model': result.ai_result.model,
            'usage': result.ai_result.usage,
            'request_id': result.ai_result.request_id,
            'prompt_sha256': result.ai_result.prompt_sha256,
            'cached': result.ai_result.cached,
        },
    }
    immutable_json(target / 'manifest.json', manifest)
    return target, manifest


def _source_map(data, segments, tree):
    """Bind ordered UTF-8 segments to coordinates in the archived source tree."""
    offset = char = 0
    result = []
    digests = {item['path']: item['sha256'] for item in tree.manifest}
    for segment in segments:
        start, end = (segment['normalized'][key] for key in ('byte_start', 'byte_end'))
        if start != offset or not start < end <= len(data):
            raise ValueError('Invalid normalization segment coverage')
        chunk = data[start:end]
        text = chunk.decode('utf-8')
        origin = segment['origin']
        span = None
        if origin is not None:
            path, a, b = (origin[key] for key in ('path', 'byte_start', 'byte_end'))
            raw = tree.files[path]
            if not 0 <= a < b <= len(raw) or raw[a:b] != chunk:
                raise ValueError('Normalization segment differs from the archived source bytes')
            prefix = raw[:a].decode('utf-8')
            span = {'path': path, 'char_start': len(prefix), 'line_start': prefix.count('\n') + 1,
                    'file_sha256': digests[path]}
        result.append({'char_start': char, 'char_end': char + len(text), 'origin': span})
        offset = end
        char += len(text)
    if offset != len(data):
        raise ValueError('Normalization source map does not cover the projection')
    return result


def normalization_binding(target, manifest):
    return {'normalization_id': target.name, 'normalization_sha256': manifest['normalized_sha256'],
            'normalization_manifest_sha256': hash_text(canonical(manifest))}


def _normalization_path(root, material):
    tree_hash, run_id = (material.get(field) for field in ('source_tree_hash', 'normalization_id'))
    if not isinstance(tree_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', tree_hash):
        raise ValueError('Invalid normalization source tree hash')
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id):
        raise ValueError('Invalid normalization run ID')
    return managed_path(Path(root), f'derived/normalizations/{tree_hash}/{run_id}')


def load_normalization(root, material, *, tree=None):
    """Verify a normalization pinned by a release, optionally against original bytes."""
    target = _normalization_path(root, material)
    manifest = read_json(regular_managed_path(target, 'manifest.json'))
    if (not isinstance(manifest, dict) or manifest.get('schema') != 'qecgraph.normalization'
            or manifest.get('source_tree_hash') != material['source_tree_hash']
            or manifest.get('run_id') != material['normalization_id']
            or normalization_binding(target, manifest) != {field: material.get(field) for field in (
                'normalization_id', 'normalization_sha256', 'normalization_manifest_sha256')}):
        raise ValueError('Normalization manifest does not match the published binding')
    data = (regular_managed_path(target, 'main.tex')).read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest['normalized_sha256']:
        raise ValueError('Normalized TeX does not match the published hash')
    plan = read_json(regular_managed_path(target, 'plan.json'))
    if hash_text(json.dumps(plan, sort_keys=True)) != manifest['plan_sha256']:
        raise ValueError('Normalization plan does not match the published hash')
    if tree is not None and (tree.digest != manifest['source_tree_hash']
                             or _source_map(data, manifest['segments'], tree) != manifest['source_map']):
        raise ValueError('Normalization source map does not match the archive')
    return NormalizedSource(manifest['source_tree_hash'], data, plan, tuple(manifest['segments'])), manifest


def mapped_ranges(text, source_map, start, end):
    """Clip a normalized codepoint range to the original archived slices."""
    ranges = []
    for segment in source_map:
        a, b = max(start, segment['char_start']), min(end, segment['char_end'])
        if a >= b:
            continue
        origin = segment['origin']
        span = None
        if origin is not None:
            base = segment['char_start']
            span = {**origin, 'char_start': origin['char_start'] + a - base,
                    'char_end': origin['char_start'] + b - base,
                    'line_start': origin['line_start'] + text.count('\n', base, a),
                    'line_end': origin['line_start'] + text.count('\n', base, b - 1)}
        ranges.append({'projection_char_start': a, 'projection_char_end': b, 'source': span})
    return ranges
