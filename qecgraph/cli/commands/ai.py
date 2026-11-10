"""CLI handlers for optional AI provider configuration."""
from __future__ import annotations

import os
import stat

from ...llm.client import LLMClient
from ...llm.config import AIConfigError, load_ai_config
from ...llm.providers.base import Message
from ...llm.providers.cli import is_claude
from ...workspace import CONFIG, locate
from ..render import emit_report


SCHEMA = {'type': 'object', 'required': ['ok'],
          'properties': {'ok': {'type': 'boolean'}}, 'additionalProperties': False}
MESSAGES = [Message('system', 'This is a connectivity probe. Return only the requested JSON.'),
            Message('user', 'Return {"ok": true}.')]


def _config(args):
    root = locate(args.workspace, default=os.environ.get('QECGRAPH_WORKSPACE'))
    return root, load_ai_config(root)


def _redacted_provider(name, provider):
    key_source = 'inline' if provider.api_key else ('environment' if provider.api_key_env else 'none')
    return {'name': name, 'kind': provider.kind, 'base_url': provider.base_url,
            'api_key_source': key_source, 'api_key_env': provider.api_key_env,
            'command': provider.command, 'args': list(provider.args)}


def config(args):
    root, ai = _config(args)
    payload = {'status': 'ok', 'workspace': str(root),
               'config': str(root / CONFIG), 'enabled': ai.enabled,
               'provider': ai.provider, 'model': ai.model,
               'allow_source_upload': ai.allow_source_upload,
               'providers': [_redacted_provider(name, provider)
                             for name, provider in sorted(ai.providers.items())]}
    return emit_report(payload, exit_code=0)


def status(args):
    root, ai = _config(args)
    selected = ai.selected
    config_path = root / CONFIG
    needs_key = selected.kind != 'cli' or is_claude(selected.name, selected.command)
    mode = stat.S_IMODE(config_path.stat().st_mode) if config_path.is_file() else None
    payload = {'status': 'ok', 'workspace': str(root), 'enabled': ai.enabled,
               'provider': ai.provider, 'model': ai.model,
               'kind': selected.kind, 'config_mode': None if mode is None else oct(mode),
               'config_private': mode is not None and mode & 0o077 == 0,
               'configured': bool(selected.resolved_key()) if needs_key
               else bool(selected.command),
               'allow_source_upload': ai.allow_source_upload}
    if needs_key:
        payload['api_key_source'] = ('inline' if selected.api_key
                                     else 'environment' if selected.api_key_env else 'none')
    return emit_report(payload, exit_code=0)


def test(args):
    root, ai = _config(args)
    if not ai.model.strip():
        raise AIConfigError('[ai].model is empty; set the provider model ID')
    client = LLMClient(ai)
    result = client.complete_json(MESSAGES, SCHEMA, use_cache=False)
    return emit_report({'status': 'ok', 'workspace': str(root), 'provider': ai.provider,
                        'model': result.model, 'request_id': result.request_id,
                        'cached': result.cached}, exit_code=0)


def proposals(args):
    root = locate(args.workspace, default=os.environ.get('QECGRAPH_WORKSPACE'))
    from ...llm.review import proposals as list_proposals

    items = list_proposals(root)
    return emit_report({'status': 'ok', 'workspace': str(root), 'count': len(items),
                        'proposals': items}, exit_code=0)


def decide(args):
    from ...llm.review import decide as review_decide
    result = review_decide(args.workspace, args.proposal, actor={'id': args.actor_id, 'kind': args.actor_kind},
                           decision=args.decision, rationale=args.rationale,
                           checked_scopes=args.checked_scope)
    return emit_report(result, exit_code=0)


def decisions(args):
    from ...llm.review import decisions as list_decisions
    root = locate(args.workspace, default=os.environ.get('QECGRAPH_WORKSPACE'))
    values = list_decisions(root)
    return emit_report({'status': 'ok', 'workspace': str(root), 'count': len(values),
                        'decisions': values}, exit_code=0)
