"""Configuration and secret resolution for optional AI providers."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib
from typing import Mapping

CONFIG_NAME = 'qecgraph.toml'
PROVIDER_KINDS = frozenset({'openai', 'anthropic', 'openai_compatible', 'cli'})
DEFAULT_PROVIDERS = {
    'openai': {
        'kind': 'openai',
        'base_url': 'https://api.openai.com/v1',
        'api_key_env': 'OPENAI_API_KEY',
    },
    'anthropic': {
        'kind': 'anthropic',
        'base_url': 'https://api.anthropic.com',
        'api_key_env': 'ANTHROPIC_API_KEY',
    },
    'openrouter': {
        'kind': 'openai_compatible',
        'base_url': 'https://openrouter.ai/api/v1',
        'api_key_env': 'OPENROUTER_API_KEY',
    },
    'claude_code': {
        'kind': 'cli',
        'command': 'claude',
        'args': ['-p', '--output-format', 'json'],
    },
}


class AIConfigError(ValueError):
    """AI configuration is missing or invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    kind: str
    base_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()

    def resolved_key(self, environ: Mapping[str, str] | None = None) -> str | None:
        environ = os.environ if environ is None else environ
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return environ.get(self.api_key_env) or None
        return None


@dataclass(frozen=True)
class AIConfig:
    enabled: bool
    provider: str
    model: str
    timeout_seconds: float
    max_retries: int
    max_cost_usd: float
    max_input_chars: int
    allow_source_upload: bool
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    @property
    def selected(self) -> ProviderConfig:
        try:
            return self.providers[self.provider]
        except KeyError as exc:
            raise AIConfigError(f"[ai].provider must name one of: {', '.join(sorted(self.providers))}") from exc

    def require_ready(self, environ: Mapping[str, str] | None = None) -> ProviderConfig:
        if not self.enabled:
            raise AIConfigError('[ai].enabled is false')
        if not self.model.strip():
            raise AIConfigError('[ai].model is empty; set the provider model ID')
        provider = self.selected
        if provider.kind == 'cli':
            if not provider.command:
                raise AIConfigError(f'[ai.providers.{self.provider}].command is empty')
        elif not provider.resolved_key(environ):
            hint = provider.api_key_env or 'api_key'
            raise AIConfigError(f'missing API key for provider {self.provider!r}; set {hint}')
        return provider


def _provider_table(name, raw):
    if not isinstance(raw, dict):
        raise AIConfigError(f'[ai.providers.{name}] must be a table')
    defaults = DEFAULT_PROVIDERS.get(name, {})
    value = {**defaults, **raw}
    kind = value.get('kind')
    if kind not in PROVIDER_KINDS:
        raise AIConfigError(f'[ai.providers.{name}].kind must be one of: {", ".join(sorted(PROVIDER_KINDS))}')
    for key in ('base_url', 'api_key', 'api_key_env', 'command'):
        if key in value and not isinstance(value[key], str):
            raise AIConfigError(f'[ai.providers.{name}].{key} must be a string')
    args = value.get('args', [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise AIConfigError(f'[ai.providers.{name}].args must be an array of strings')
    if kind != 'cli' and not value.get('base_url'):
        raise AIConfigError(f'[ai.providers.{name}].base_url is required')
    if kind == 'cli' and not value.get('command'):
        raise AIConfigError(f'[ai.providers.{name}].command is required')
    return ProviderConfig(name=name, kind=kind, base_url=value.get('base_url'),
                          api_key=value.get('api_key') or None,
                          api_key_env=value.get('api_key_env') or None,
                          command=value.get('command'), args=tuple(args))


def load_ai_config(root, environ: Mapping[str, str] | None = None) -> AIConfig:
    path = Path(root) / CONFIG_NAME
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise AIConfigError(f'{CONFIG_NAME} was not found; run qec-graph init first') from exc
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise AIConfigError(f'could not read [ai] configuration: {exc}') from exc
    raw = data.get('ai')
    if not isinstance(raw, dict):
        raise AIConfigError('[ai] is missing; add an [ai] table to qecgraph.toml')
    providers_raw = raw.get('providers') or {}
    if not isinstance(providers_raw, dict) or not providers_raw:
        raise AIConfigError('[ai.providers] is missing')
    providers = {name: _provider_table(name, value) for name, value in providers_raw.items()}
    enabled = raw.get('enabled', True)
    model = raw.get('model', '')
    if not isinstance(enabled, bool):
        raise AIConfigError('[ai].enabled must be a boolean')
    if not isinstance(model, str):
        raise AIConfigError('[ai].model must be a string')
    provider = raw.get('provider')
    if not isinstance(provider, str) or not provider:
        raise AIConfigError('[ai].provider must be a nonempty string')
    numbers = {
        'timeout_seconds': (raw.get('timeout_seconds', 180), (int, float), 1),
        'max_retries': (raw.get('max_retries', 2), int, 0),
        'max_cost_usd': (raw.get('max_cost_usd', 5.0), (int, float), 0),
        'max_input_chars': (raw.get('max_input_chars', 200000), int, 1000),
    }
    parsed = {}
    for name, (value, types, minimum) in numbers.items():
        if isinstance(value, bool) or not isinstance(value, types) or value < minimum:
            raise AIConfigError(f'[ai].{name} has an invalid value')
        parsed[name] = value
    allow = raw.get('allow_source_upload', True)
    if not isinstance(allow, bool):
        raise AIConfigError('[ai].allow_source_upload must be a boolean')
    return AIConfig(enabled=enabled, provider=provider, model=model,
                    timeout_seconds=float(parsed['timeout_seconds']),
                    max_retries=parsed['max_retries'], max_cost_usd=float(parsed['max_cost_usd']),
                    max_input_chars=parsed['max_input_chars'], allow_source_upload=allow,
                    providers=providers)


def render_config_template(workspace_id):
    """Return the initial TOML, including provider examples and safe defaults."""
    return f'''format = "qecgraph.workspace"
workspace_id = "{workspace_id}"

# AI is optional. Fill in the provider model and API key before running sync.
[ai]
enabled = true
provider = "openrouter"
model = ""
timeout_seconds = 180
max_retries = 2
max_cost_usd = 5.0
max_input_chars = 200000
allow_source_upload = true

[ai.providers.openai]
kind = "openai"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
api_key = ""

[ai.providers.anthropic]
kind = "anthropic"
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"
api_key = ""

[ai.providers.openrouter]
kind = "openai_compatible"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
api_key = ""

[ai.providers.claude_code]
kind = "cli"
command = "claude"
args = ["-p", "--output-format", "json"]
'''
