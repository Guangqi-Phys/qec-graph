"""Publish optional semantic results after the structural transaction."""
from __future__ import annotations

from contextlib import nullcontext

from .core.transactions import WriterBusy, writer_lock
from .domain.ai_records import stage_ai_records
from .llm.review import proposal_issues
from .retrieval import configuration, stage_index


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
            stage_local_retrieval(workspace.registry, state, cfg, repair=rebuild)
            return workspace.registry._publish(state), None
    except WriterBusy:
        return release, 'Another writer is active; run sync to publish pending AI results'


def external_retrieval(cfg):
    settings = configuration(cfg.get('retrieval', {}))
    return settings['enabled'] and settings['provider'] != 'local'


def stage_local_retrieval(registry, state, cfg, *, repair=False):
    if not external_retrieval(cfg):
        stage_index(registry, state, cfg.get('retrieval', {}), repair=repair)


def publish_external_retrieval(workspace, cfg, release, *, rebuild, workspace_locked):
    state, _ = workspace.registry.read(release, verify=False)
    previous = state.get('retrieval_index')
    # Immutable vector objects and the candidate binding can be prepared while
    # another writer publishes. Only the binding publication needs a lock.
    stage_index(workspace.registry, state, cfg['retrieval'], repair=rebuild)
    if previous == state.get('retrieval_index'):
        return release, None
    try:
        with (nullcontext() if workspace_locked else writer_lock(workspace.path('.qecgraph'))), writer_lock(workspace.registry.root):
            if workspace.registry.read(verify=False)[1] != release or workspace.config() != cfg:
                return release, 'Workspace changed during embedding; run sync to publish the index'
            return workspace.registry._publish(state), None
    except WriterBusy:
        return release, 'Another writer is active; run sync to publish the index'
