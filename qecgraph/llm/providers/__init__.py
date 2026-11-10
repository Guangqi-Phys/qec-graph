"""Provider adapters for the optional AI layer."""
from .base import Completion, HttpResult, Message, Provider, Transport
from .anthropic import AnthropicProvider
from .cli import CliProvider
from .factory import build_provider
from .http import UrllibTransport
from .openai import OpenAICompatibleProvider

__all__ = ['Completion', 'HttpResult', 'Message', 'Provider', 'Transport',
           'UrllibTransport', 'OpenAICompatibleProvider', 'AnthropicProvider',
           'CliProvider', 'build_provider']
