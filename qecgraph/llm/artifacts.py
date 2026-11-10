"""Write private, auditable normalization artifacts under a workspace."""
from __future__ import annotations

import json
from pathlib import Path

from ..core.graph import hash_text
from ..core.transactions import atomic_bytes, atomic_json
from .normalize import NormalizationResult


def write_normalization(root, result: NormalizationResult, *, run_id=None):
    root = Path(root)
    source_hash = result.source.source_tree_hash
    if not source_hash or any(ch not in '0123456789abcdef' for ch in source_hash) or len(source_hash) != 64:
        raise ValueError('normalization source hash must be a 64-character lowercase hex digest')
    if run_id is None:
        run_id = (result.ai_result.run_id if result.ai_result is not None
                  else hash_text(json.dumps(result.source.plan, sort_keys=True)))
    target = root / 'derived' / 'normalizations' / source_hash / run_id
    target.mkdir(parents=True, exist_ok=True)
    atomic_bytes(target / 'main.tex', result.source.data)
    atomic_json(target / 'plan.json', result.source.plan)
    manifest = {
        'schema': 'qecgraph.normalization',
        'source_tree_hash': source_hash,
        'run_id': run_id,
        'normalized_sha256': result.source.sha256,
        'plan_sha256': hash_text(json.dumps(result.source.plan, sort_keys=True)),
        'skill_version': result.skill_version,
        'fallback_reason': result.fallback_reason,
        'segments': list(result.source.segments),
        'ai': None if result.ai_result is None else {
            'model': result.ai_result.model,
            'usage': result.ai_result.usage,
            'request_id': result.ai_result.request_id,
            'prompt_sha256': result.ai_result.prompt_sha256,
            'cached': result.ai_result.cached,
        },
    }
    atomic_json(target / 'manifest.json', manifest)
    return target, manifest
