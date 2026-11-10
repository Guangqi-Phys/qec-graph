import tempfile
import unittest
from pathlib import Path

from qecgraph.llm.client import BudgetExceeded, LLMClient, ResponseSchemaError
from qecgraph.llm.config import AIConfig, ProviderConfig
from qecgraph.llm.errors import ProviderError
from qecgraph.llm.providers.base import Completion, Message
from qecgraph.llm.redact import redact

SCHEMA = {'type': 'object', 'required': ['ok'], 'properties': {'ok': {'type': 'boolean'}},
          'additionalProperties': False}


def config(**overrides):
    values = dict(enabled=True, provider='fake', model='model', timeout_seconds=10,
                  max_retries=2, max_cost_usd=5.0, max_input_chars=10000,
                  allow_source_upload=True,
                  providers={'fake': ProviderConfig('fake', 'cli', command='fake')})
    values.update(overrides)
    return AIConfig(**values)


class FakeProvider:
    name = 'fake'
    kind = 'cli'

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class ClientTests(unittest.TestCase):
    def test_retries_retryable_provider_errors(self):
        provider = FakeProvider(ProviderError('rate limited', retryable=True),
                                Completion('{"ok": true}', 'model', {'prompt_tokens': 1}))
        delays = []
        result = LLMClient(config(), provider=provider, sleeper=delays.append).complete_json(
            [Message('user', 'hello')], SCHEMA)
        self.assertEqual(result.data, {'ok': True})
        self.assertEqual(result.attempts, 2)
        self.assertEqual(delays, [1])
        self.assertEqual(provider.calls, 2)

    def test_schema_and_budget_fail_without_accepting_output(self):
        provider = FakeProvider(Completion('{"ok": "no"}', 'model'))
        with self.assertRaises(ResponseSchemaError):
            LLMClient(config(), provider=provider).complete_json([Message('user', 'x')], SCHEMA)
        provider = FakeProvider(Completion('{"ok": true}', 'model', {'cost': 9}))
        with self.assertRaises(BudgetExceeded):
            LLMClient(config(max_cost_usd=1), provider=provider).complete_json(
                [Message('user', 'x')], SCHEMA)

    def test_validated_response_is_cached(self):
        provider = FakeProvider(Completion('{"ok": true}', 'model', {'cost': 0.1}))
        with tempfile.TemporaryDirectory() as directory:
            client = LLMClient(config(), provider=provider, cache_dir=Path(directory))
            first = client.complete_json([Message('user', 'x')], SCHEMA)
            second = client.complete_json([Message('user', 'x')], SCHEMA)
            self.assertFalse(first.cached)
            self.assertTrue(second.cached)
            self.assertEqual(second.data, {'ok': True})
            self.assertEqual(provider.calls, 1)
            self.assertEqual(len(list(Path(directory).glob('*.json'))), 1)

    def test_redaction_removes_known_and_pattern_secrets(self):
        value = redact('key sk-abc123456789 and Bearer abcdefghijkl', ['sk-other'])
        self.assertNotIn('sk-abc123456789', value)
        self.assertNotIn('abcdefghijkl', value)
        self.assertIn('<redacted>', value)
