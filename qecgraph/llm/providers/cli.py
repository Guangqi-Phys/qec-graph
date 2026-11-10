"""Adapter for local agent CLIs such as Claude Code.

The CLI receives the prompt on stdin, runs in an empty temporary directory, and
is never invoked through a shell. It is a convenience adapter; direct APIs are
preferred when deterministic structured output is required.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from ..errors import ProviderError
from .base import Completion, Message


class CliProvider:
    kind = 'cli'

    def __init__(self, name, *, command, args=(), env: Mapping[str, str] | None = None):
        if not command:
            raise ValueError('command is required')
        self.name = name
        self.command = command
        self.args = tuple(args)
        self.env = dict(env) if env is not None else None

    def complete(self, messages: Sequence[Message], *, model: str,
                 response_schema: Mapping[str, Any] | None = None,
                 temperature: float = 0.0, max_output_tokens: int | None = None,
                 timeout: float = 180.0) -> Completion:
        prompt = '\n\n'.join(f'[{message.role}]\n{message.content}' for message in messages)
        if response_schema is not None:
            prompt += ('\n\nReturn only one JSON value matching this schema, without Markdown fences:\n'
                       + json.dumps(response_schema, ensure_ascii=False, sort_keys=True))
        env = dict(os.environ if self.env is None else self.env)
        try:
            with tempfile.TemporaryDirectory(prefix='qecgraph-ai-') as directory:
                process = subprocess.run([self.command, *self.args], input=prompt, text=True,
                                         capture_output=True, cwd=directory, env=env,
                                         timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(f'{self.name}: CLI timed out after {timeout:g}s', retryable=True) from exc
        except OSError as exc:
            raise ProviderError(f'{self.name}: could not start CLI: {exc}', retryable=False) from exc
        if process.returncode != 0:
            detail = (process.stderr or process.stdout).strip()[-300:]
            raise ProviderError(f'{self.name}: CLI exited {process.returncode}: {detail}')
        text = process.stdout
        try:
            wrapped = json.loads(text)
        except json.JSONDecodeError:
            wrapped = None
        if isinstance(wrapped, dict):
            if wrapped.get('is_error'):
                raise ProviderError(f'{self.name}: CLI reported an error')
            result = wrapped.get('result')
            if isinstance(result, str):
                text = result
        if not text.strip():
            raise ProviderError(f'{self.name}: CLI returned no text')
        return Completion(text=text, model=model, usage={}, request_id=None,
                          finish_reason='stop')
