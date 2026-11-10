"""Anthropic Messages API adapter."""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from ..errors import ProviderError
from .base import Completion, Message, Transport
from .http import UrllibTransport


class AnthropicProvider:
    kind = 'anthropic'

    def __init__(self, name, *, base_url, api_key, transport: Transport | None = None,
                 version: str = '2023-06-01'):
        if not base_url:
            raise ValueError('base_url is required')
        if not api_key:
            raise ValueError('api_key is required')
        self.name = name
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.transport = transport or UrllibTransport()
        self.version = version

    @property
    def endpoint(self):
        return self.base_url + '/v1/messages' if not self.base_url.endswith('/v1') else self.base_url + '/messages'

    def complete(self, messages: Sequence[Message], *, model: str,
                 response_schema: Mapping[str, Any] | None = None,
                 temperature: float = 0.0, max_output_tokens: int | None = None,
                 timeout: float = 180.0) -> Completion:
        system = '\n\n'.join(message.content for message in messages if message.role == 'system')
        if response_schema is not None:
            schema = json.dumps(response_schema, ensure_ascii=False, sort_keys=True)
            instruction = ('Return only one JSON value that validates against this JSON Schema. '
                           'Do not wrap it in Markdown or add commentary:\n' + schema)
            system = (system + '\n\n' if system else '') + instruction
        dialogue = [{'role': message.role, 'content': message.content}
                    for message in messages if message.role in {'user', 'assistant'}]
        if not dialogue:
            raise ProviderError(f'{self.name}: at least one user message is required')
        payload = {'model': model, 'max_tokens': max_output_tokens or 4096,
                   'temperature': temperature, 'messages': dialogue}
        if system:
            payload['system'] = system
        headers = {'x-api-key': self.api_key, 'anthropic-version': self.version,
                   'Content-Type': 'application/json', 'Accept': 'application/json'}
        try:
            result = self.transport.request('POST', self.endpoint, headers=headers,
                                            body=json.dumps(payload).encode('utf-8'), timeout=timeout)
        except ConnectionError:
            raise ProviderError(f'{self.name}: transport failed', retryable=True) from None
        if not 200 <= result.status < 300:
            retryable = result.status in {408, 409, 429} or result.status >= 500
            raise ProviderError(f'{self.name}: HTTP {result.status}',
                                status=result.status, retryable=retryable)
        try:
            data = json.loads(result.body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderError(f'{self.name}: provider returned invalid JSON') from None
        blocks = data.get('content')
        text = ''.join(block.get('text', '') for block in blocks
                       if isinstance(block, dict) and block.get('type') == 'text') if isinstance(blocks, list) else ''
        if not text:
            raise ProviderError(f'{self.name}: provider returned no text content')
        usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
        return Completion(text=text, model=data.get('model') or model, usage=usage,
                          request_id=result.headers.get('request-id') or data.get('id'),
                          finish_reason=data.get('stop_reason'))
