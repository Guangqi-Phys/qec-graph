"""OpenAI-compatible chat-completions adapter.

This covers the OpenAI API and OpenRouter. The adapter deliberately has no
retry loop: the shared client owns retries, budgeting and validation.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from ..errors import ProviderError
from .base import Completion, HttpResult, Message, Transport
from .http import UrllibTransport


class OpenAICompatibleProvider:
    kind = 'openai_compatible'

    def __init__(self, name, *, base_url, api_key, transport: Transport | None = None,
                 extra_headers: Mapping[str, str] | None = None):
        if not base_url:
            raise ValueError('base_url is required')
        if not api_key:
            raise ValueError('api_key is required')
        self.name = name
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.transport = transport or UrllibTransport()
        self.extra_headers = dict(extra_headers or {})

    @property
    def endpoint(self):
        return self.base_url + '/chat/completions'

    def _payload(self, messages, *, model, response_schema, temperature, max_output_tokens):
        payload: dict[str, Any] = {
            'model': model,
            'messages': [{'role': message.role, 'content': message.content} for message in messages],
            'temperature': temperature,
        }
        if max_output_tokens is not None:
            payload['max_tokens'] = max_output_tokens
        if response_schema is not None:
            payload['response_format'] = {
                'type': 'json_schema',
                'json_schema': {'name': 'qecgraph_result', 'strict': True, 'schema': response_schema},
            }
        return payload

    def complete(self, messages: Sequence[Message], *, model: str,
                 response_schema: Mapping[str, Any] | None = None,
                 temperature: float = 0.0, max_output_tokens: int | None = None,
                 timeout: float = 180.0) -> Completion:
        payload = self._payload(messages, model=model, response_schema=response_schema,
                                temperature=temperature, max_output_tokens=max_output_tokens)
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            **self.extra_headers,
        }
        try:
            result = self.transport.request('POST', self.endpoint, headers=headers,
                                            body=json.dumps(payload).encode('utf-8'), timeout=timeout)
        except ConnectionError:
            raise ProviderError(f'{self.name}: transport failed', retryable=True) from None
        self._raise_for_status(result)
        try:
            data = json.loads(result.body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderError(f'{self.name}: provider returned invalid JSON') from None
        choices = data.get('choices')
        if not isinstance(choices, list) or not choices:
            raise ProviderError(f'{self.name}: provider returned no choices')
        message = choices[0].get('message') if isinstance(choices[0], dict) else None
        content = message.get('content') if isinstance(message, dict) else None
        if isinstance(content, list):
            content = ''.join(part.get('text', '') for part in content if isinstance(part, dict))
        if not isinstance(content, str):
            raise ProviderError(f'{self.name}: provider returned no text content')
        usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
        request_id = result.headers.get('x-request-id') or data.get('id')
        finish_reason = choices[0].get('finish_reason') if isinstance(choices[0], dict) else None
        return Completion(text=content, model=data.get('model') or model, usage=usage,
                          request_id=request_id, finish_reason=finish_reason)

    def _raise_for_status(self, result: HttpResult):
        if 200 <= result.status < 300:
            return
        retryable = result.status in {408, 409, 429} or result.status >= 500
        raise ProviderError(f'{self.name}: HTTP {result.status}', status=result.status, retryable=retryable)
