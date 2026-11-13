"""Publish optional semantic results after the structural transaction."""
from __future__ import annotations

from .core.transactions import WriterBusy, writer_lock
from .domain.ai_records import stage_ai_records
from .llm.review import proposal_issues
from .retrieval import stage_index


def publish_semantic(workspace, cfg, release, materials, digests, ai_results, limits, client, *, rebuild):
    state, _ = workspace.registry.read(release)
    previous = dict(ai_results)
    workspace._complete_ai(client, materials, digests, state['versions'], ai_results, limits)
    if previous == ai_results:
        return release, None
    try:
        with writer_lock(workspace.path('.qecgraph')), writer_lock(workspace.registry.root):
            if workspace.registry.read()[1] != release or workspace.config() != cfg:
                return release, 'Workspace changed during AI extraction; run sync to publish pending results'
            for material in state['materials'].values():
                identity = material.get('source_version_id'), material.get('source_snapshot_id')
                if material.get('processing_completed') and identity in ai_results:
                    material['ai_extraction'] = ai_results[identity]
            if next(proposal_issues(workspace.registry, state), None) is not None:
                raise ValueError('AI results failed publication validation')
            stage_ai_records(workspace.registry, state)
            stage_index(workspace.registry, state, cfg.get('retrieval', {}), repair=rebuild)
            return workspace.registry._publish(state), None
    except WriterBusy:
        return release, 'Another writer is active; run sync to publish pending AI results'

