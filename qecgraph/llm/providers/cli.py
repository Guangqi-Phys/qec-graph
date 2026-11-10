"""Adapter for local agent CLIs such as Claude Code.

The CLI receives the prompt on stdin, runs in an empty temporary directory, and
is never invoked through a shell. It is a convenience adapter; direct APIs are
preferred when deterministic structured output is required.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from ..errors import ProviderError
from .base import Completion, Message


CLAUDE_ARGS = ('-p', '--output-format', 'json')
_CLI_ENV = ('PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SSL_CERT_FILE', 'SSL_CERT_DIR')


def is_claude(name, command):
    return name == 'claude_code' or (command is not None and Path(command).name == 'claude')


class CliProvider:
    kind = 'cli'

    def __init__(self, name, *, command, args=(), env: Mapping[str, str] | None = None,
                 claude=None, api_key=None, api_key_env=None):
        if not command:
            raise ValueError('command is required')
        self.name = name
        self.command = command
        self.args = tuple(args)
        self.env = {key: value for key, value in (os.environ if env is None else env).items() if key in _CLI_ENV}
        self.claude = is_claude(name, command) if claude is None else claude
        self.api_key = api_key
        self.api_key_env = api_key_env
        if self.claude and self.args not in ((), CLAUDE_ARGS):
            raise ValueError('Claude Code uses fixed tool-free arguments; remove custom args from the provider')

    def complete(self, messages: Sequence[Message], *, model: str,
                 response_schema: Mapping[str, Any] | None = None,
                 temperature: float = 0.0, max_output_tokens: int | None = None,
                 timeout: float = 180.0) -> Completion:
        system = '\n\n'.join(message.content for message in messages if message.role == 'system')
        if response_schema is not None:
            system += ('\n\nReturn only one JSON value matching this schema, without Markdown fences:\n'
                       + json.dumps(response_schema, ensure_ascii=False, sort_keys=True))
        env = dict(self.env)
        if self.api_key and self.api_key_env:
            env[self.api_key_env] = self.api_key
        args = self.args
        prompt = '\n\n'.join(f'[{message.role}]\n{message.content}' for message in messages if message.role != 'system')
        if self.claude:
            if not self.api_key:
                raise ProviderError(f'{self.name}: set {self.api_key_env or "ANTHROPIC_API_KEY"} for bare mode')
            prompt = '\n\n'.join(message.content for message in messages if message.role != 'system')
            args = (*CLAUDE_ARGS, '--bare', '--tools', '', '--disallowedTools', '*',
                    '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                    '--disable-slash-commands', '--no-chrome', '--no-session-persistence',
                    '--model', model, '--system-prompt', system or 'Return the requested JSON.')
        elif system:
            prompt = '[system]\n' + system + '\n\n' + prompt
        try:
            with tempfile.TemporaryDirectory(prefix='qecgraph-ai-') as directory:
                if self.claude:
                    env['CLAUDE_CONFIG_DIR'] = directory
                process = subprocess.run([self.command, *args], input=prompt, text=True, encoding='utf-8',
                                         capture_output=True, cwd=directory, env=env,
                                         timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise ProviderError(f'{self.name}: CLI timed out after {timeout:g}s', retryable=True) from None
        except OSError:
            raise ProviderError(f'{self.name}: could not start CLI', retryable=False) from None
        if process.returncode != 0:
            raise ProviderError(f'{self.name}: CLI exited {process.returncode}')
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
