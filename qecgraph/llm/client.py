"""Shared retry, budget, schema-validation and cache layer for AI calls."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time
from threading import Lock
from typing import Any, Callable, Mapping, Sequence
import uuid

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from ..core.graph import canonical, strict_json_loads
from ..core.language import require_english
from ..core.progress import outcome, phase, task
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
        return strict_json_loads(value)
    except ValueError:
        raise ResponseSchemaError('model returned invalid JSON') from None


def _usage_cost(usage):
    for key in ('cost', 'cost_usd', 'total_cost'):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            return float(value)
    return 0.0


def _usage_summary(usage):
    """Only display actual, numeric provider counters, never response content."""
    parts = []
    for label, keys in (('input', ('input_tokens', 'prompt_tokens')), ('output', ('output_tokens', 'completion_tokens'))):
        value = next((usage[key] for key in keys if key in usage), None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            parts.append(f'{value:,} {label} tokens')
    return ' | '.join(parts)


class LLMClient:
    def __init__(self, config: AIConfig, *, provider: Provider | None = None,
                 cache_dir: str | Path | None = None, sleeper=None):
        self.config = config
        self.provider = provider or build_provider(config)
        self.cache = ResponseCache(cache_dir) if cache_dir else None
        self.sleeper = sleeper or time.sleep
        self._batch_lock = Lock()
        self._batch_requests = 0
        self._batch_cost = 0.0
        self._unpriced_responses = 0
        self.secrets = tuple(key for item in config.providers.values() if (key := item.resolved_key()))
        provider_key = getattr(self.provider, 'api_key', None)
        if isinstance(provider_key, str) and provider_key and provider_key not in self.secrets:
            self.secrets += (provider_key,)

    def _provider_identity(self):
        configured = self.config.providers.get(self.config.provider)
        return {'name': self.config.provider, 'kind': getattr(self.provider, 'kind', configured and configured.kind),
                'endpoint': getattr(self.provider, 'endpoint', None) or (configured and configured.base_url),
                'command': configured and configured.command, 'args': configured and configured.args}

    def batch_usage(self):
        with self._batch_lock:
            return {'attempted_requests': self._batch_requests, 'reported_cost_usd': self._batch_cost,
                    'unpriced_responses': self._unpriced_responses,
                    'cost_scope': 'Provider-reported only; in-flight requests and missing prices prevent a hard dollar cap'}

    @task('Preparing AI request', kind='ai')
    def complete_json(self, messages: Sequence[Message], schema: Mapping[str, Any], *,
                      model: str | None = None, temperature: float = 0.0,
                      max_output_tokens: int | None = None, use_cache: bool = True,
                      validate: Callable[[Any], None] | None = None) -> LLMResult:
        if not self.config.allow_source_upload:
            raise LLMError('source upload is disabled by [ai].allow_source_upload')
        selected_model = model or self.config.model
        if not selected_model.strip():
            raise LLMError('AI model is empty')
        if sum(len(message.content) for message in messages) > self.config.max_input_chars:
            raise BudgetExceeded('AI request exceeds [ai].max_input_chars')
        Draft202012Validator.check_schema(schema)
        schema_validator = Draft202012Validator(schema)

        def validated(text):
            data = _parse_json(text)
            try:
                schema_validator.validate(data)
            except ValidationError as exc:
                location = json.dumps(list(exc.absolute_path), ensure_ascii=False)
                raise ResponseSchemaError(f'model response does not match schema ({exc.validator} at {location})') from None
            if validate is not None:
                validate(data)
            try:
                require_english(data)
            except ValueError as exc:
                raise ResponseSchemaError(str(exc)) from None
            return data

        message_payload = [{'role': message.role, 'content': message.content} for message in messages]
        key = cache_key(provider=self._provider_identity(), model=selected_model,
                        messages=message_payload, schema=schema, temperature=temperature,
                        max_output_tokens=max_output_tokens)
        prompt_hash = hashlib.sha256(json.dumps(message_payload, ensure_ascii=False,
                                                sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        run_id = uuid.uuid4().hex
        if use_cache and self.cache is not None:
            phase('Checking cached AI response')
            cached = self.cache.get(key)
            if (cached is not None and isinstance(cached.get('text'), str)
                    and isinstance(cached.get('model'), str) and cached['model']
                    and isinstance(cached.get('usage'), dict)
                    and (cached.get('request_id') is None or isinstance(cached['request_id'], str))):
                try:
                    data = validated(cached['text'])
                    if canonical(data) != canonical(cached['data']):
                        raise ResponseSchemaError('cached JSON differs from the response text')
                except (ValueError, KeyError, LLMError):
                    pass
                else:
                    phase('Reusing validated AI response', detail='Cache hit; no provider request')
                    outcome('reused')
                    return LLMResult(data=data, text=cached['text'], model=cached['model'],
                                     usage=cached['usage'], request_id=cached.get('request_id'),
                                     attempts=0, cached=True, run_id=run_id, prompt_sha256=prompt_hash)
        last_error = None
        spent = 0.0
        for attempt in range(1, self.config.max_retries + 2):
            with self._batch_lock:
                if self._batch_requests >= self.config.max_batch_requests:
                    raise BudgetExceeded('AI batch request limit reached; remaining work can be retried in a later sync')
                if self._batch_cost >= self.config.max_batch_cost_usd:
                    raise BudgetExceeded('AI batch reported-cost limit reached')
                self._batch_requests += 1
            try:
                phase('Waiting for AI provider', detail=redact(
                    f'attempt {attempt}/{self.config.max_retries + 1} | timeout {self.config.timeout_seconds:g}s'
                    f' | {self.config.provider} / {selected_model}', self.secrets))
                completion: Completion = self.provider.complete(
                    messages, model=selected_model, response_schema=schema,
                    temperature=temperature, max_output_tokens=max_output_tokens,
                    timeout=self.config.timeout_seconds)
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt > self.config.max_retries:
                    outcome('failed', detail=redact(str(exc), self.secrets))
                    raise ProviderError(redact(str(exc), self.secrets), status=exc.status,
                                        retryable=exc.retryable, code=exc.code) from None
                delay = min(2 ** (attempt - 1), 8)
                phase('Waiting to retry AI request', detail=f'retry in {delay}s | next attempt {attempt + 1}'
                      + (f' | HTTP {exc.status}' if exc.status else ''))
                self.sleeper(delay)
                continue
            except (LLMError, OSError) as exc:
                outcome('failed', detail=redact(str(exc), self.secrets))
                raise LLMError(redact(str(exc), self.secrets)) from None
            phase('AI response received', detail=_usage_summary(completion.usage))
            spent += _usage_cost(completion.usage)
            with self._batch_lock:
                self._batch_cost += _usage_cost(completion.usage)
                if not any(key in completion.usage for key in ('cost', 'cost_usd', 'total_cost')):
                    self._unpriced_responses += 1
                if self._batch_cost > self.config.max_batch_cost_usd:
                    raise BudgetExceeded('AI batch reported-cost limit exceeded')
            if spent > self.config.max_cost_usd:
                raise BudgetExceeded(f'AI cost limit exceeded: {spent:.4f} USD')
            phase('Validating AI response and source evidence')
            try:
                data = validated(completion.text)
            except LLMError as exc:
                exc.rejected_response = {
                    'text': redact(completion.text, self.secrets), 'model': completion.model,
                    'usage': completion.usage, 'request_id': completion.request_id,
                    'prompt_sha256': prompt_hash, 'error': redact(str(exc), self.secrets),
                }
                raise
            result = {'data': data, 'text': completion.text, 'model': completion.model,
                      'usage': completion.usage, 'request_id': completion.request_id}
            if use_cache and self.cache is not None:
                phase('Saving validated AI response to cache')
                self.cache.put(key, result)
            phase('AI response validated', detail='Response checks passed; result remains proposed')
            return LLMResult(data=data, text=completion.text, model=completion.model,
                             usage=completion.usage, request_id=completion.request_id,
                             attempts=attempt, cached=False, run_id=run_id, prompt_sha256=prompt_hash)
        raise ProviderError(redact(str(last_error), self.secrets)) from last_error
