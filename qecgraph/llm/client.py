"""Shared retry, budget, schema-validation and cache layer for AI calls."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Mapping, Sequence
import uuid

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .cache import ResponseCache, cache_key
from .config import AIConfig
from .errors import LLMError, ProviderError
from .providers.base import Completion, Message, Provider
from .providers.factory import build_provider
from .redact import redact


class BudgetExceeded(LLMError):
    """A configured limit was reached."""


class ResponseSchemaError(LLMError):
    """The model returned text that is not valid for the requested schema."""


@dataclass(frozen=True)
class LLMResult:
    data: Any
    text: str
    model: str
    usage: dict[str, Any]
    request_id: str | None
    attempts: int
    cached: bool
    run_id: str
    prompt_sha256: str


def _parse_json(text):
    value = text.strip()
    if value.startswith('```'):
        lines = value.splitlines()
        if len(lines) >= 3 and lines[0].startswith('```') and lines[-1].strip() == '```':
            value = '\n'.join(lines[1:-1]).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ResponseSchemaError(f'model returned invalid JSON: {exc.msg}') from exc


def _usage_cost(usage):
    for key in ('cost', 'cost_usd', 'total_cost'):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return 0.0


class LLMClient:
    def __init__(self, config: AIConfig, *, provider: Provider | None = None,
                 cache_dir: str | Path | None = None, sleeper=None):
        self.config = config
        self.provider = provider or build_provider(config)
        self.cache = ResponseCache(cache_dir) if cache_dir else None
        self.sleeper = sleeper or time.sleep
        self.secrets = tuple(key for item in config.providers.values() if (key := item.resolved_key()))
        provider_key = getattr(self.provider, 'api_key', None)
        if isinstance(provider_key, str) and provider_key and provider_key not in self.secrets:
            self.secrets += (provider_key,)

    def complete_json(self, messages: Sequence[Message], schema: Mapping[str, Any], *,
                      model: str | None = None, temperature: float = 0.0,
                      max_output_tokens: int | None = None, use_cache: bool = True) -> LLMResult:
        if not self.config.allow_source_upload:
            raise LLMError('source upload is disabled by [ai].allow_source_upload')
        selected_model = model or self.config.model
        if not selected_model.strip():
            raise LLMError('AI model is empty')
        if sum(len(message.content) for message in messages) > self.config.max_input_chars:
            raise BudgetExceeded('AI request exceeds [ai].max_input_chars')
        Draft202012Validator.check_schema(schema)
        message_payload = [{'role': message.role, 'content': message.content} for message in messages]
        key = cache_key(provider=self.config.provider, model=selected_model,
                        messages=message_payload, schema=schema, temperature=temperature,
                        max_output_tokens=max_output_tokens)
        prompt_hash = hashlib.sha256(json.dumps(message_payload, ensure_ascii=False,
                                                sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        run_id = uuid.uuid4().hex
        if use_cache and self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None and isinstance(cached.get('data'), (dict, list)):
                return LLMResult(data=cached['data'], text=cached.get('text', ''), model=selected_model,
                                 usage=cached.get('usage', {}), request_id=cached.get('request_id'),
                                 attempts=0, cached=True, run_id=run_id, prompt_sha256=prompt_hash)
        last_error = None
        spent = 0.0
        for attempt in range(1, self.config.max_retries + 2):
            try:
                completion: Completion = self.provider.complete(
                    messages, model=selected_model, response_schema=schema,
                    temperature=temperature, max_output_tokens=max_output_tokens,
                    timeout=self.config.timeout_seconds)
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt > self.config.max_retries:
                    raise ProviderError(redact(str(exc), self.secrets), status=exc.status,
                                        retryable=exc.retryable, code=exc.code) from None
                self.sleeper(min(2 ** (attempt - 1), 8))
                continue
            except (LLMError, OSError) as exc:
                raise LLMError(redact(str(exc), self.secrets)) from None
            spent += _usage_cost(completion.usage)
            if spent > self.config.max_cost_usd:
                raise BudgetExceeded(f'AI cost limit exceeded: {spent:.4f} USD')
            try:
                data = _parse_json(completion.text)
                Draft202012Validator(schema).validate(data)
            except ResponseSchemaError:
                raise
            except ValidationError as exc:
                raise ResponseSchemaError(f'model response does not match schema ({exc.validator})') from None
            result = {'data': data, 'text': completion.text, 'model': completion.model,
                      'usage': completion.usage, 'request_id': completion.request_id}
            if use_cache and self.cache is not None:
                self.cache.put(key, result)
            return LLMResult(data=data, text=completion.text, model=completion.model,
                             usage=completion.usage, request_id=completion.request_id,
                             attempts=attempt, cached=False, run_id=run_id, prompt_sha256=prompt_hash)
        raise ProviderError(redact(str(last_error), self.secrets)) from last_error
