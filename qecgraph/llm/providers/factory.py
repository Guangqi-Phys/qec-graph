"""Build a provider from validated AI configuration."""
from __future__ import annotations

from ..config import AIConfig
from ..errors import ProviderError
from .anthropic import AnthropicProvider
from .cli import CliProvider
from .openai import OpenAICompatibleProvider


def build_provider(config: AIConfig, environ=None):
    provider = config.require_ready(environ)
    if provider.kind in {'openai', 'openai_compatible'}:
        return OpenAICompatibleProvider(provider.name, base_url=provider.base_url,
                                        api_key=provider.resolved_key(environ))
    if provider.kind == 'anthropic':
        return AnthropicProvider(provider.name, base_url=provider.base_url,
                                 api_key=provider.resolved_key(environ))
    if provider.kind == 'cli':
        return CliProvider(provider.name, command=provider.command, args=provider.args)
    raise ProviderError(f'unsupported provider kind: {provider.kind}')
