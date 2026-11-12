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
    def test_batch_request_limit_is_shared_across_threads_and_retries(self):
        from concurrent.futures import ThreadPoolExecutor
        provider = FakeProvider(*(Completion('{"ok": true}', 'model') for _ in range(2)))
        client = LLMClient(config(max_batch_requests=2), provider=provider)
        def run(_):
            try:
                return client.complete_json([Message('user', 'x')], SCHEMA).data
            except BudgetExceeded:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(result is not None for result in pool.map(run, range(4))), 2)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(client.batch_usage()['unpriced_responses'], 2)
        provider = FakeProvider(ProviderError('retry', retryable=True))
        client = LLMClient(config(max_batch_requests=1), provider=provider, sleeper=lambda _: None)
        with self.assertRaises(BudgetExceeded):
            client.complete_json([Message('user', 'x')], SCHEMA)
        self.assertEqual(provider.calls, 1)

    def test_reported_batch_cost_accumulates_across_tasks(self):
        provider = FakeProvider(*(Completion('{"ok": true}', 'model', {'cost': .6}) for _ in range(2)))
        client = LLMClient(config(max_batch_cost_usd=1), provider=provider)
        client.complete_json([Message('user', 'one')], SCHEMA)
        with self.assertRaises(BudgetExceeded):
            client.complete_json([Message('user', 'two')], SCHEMA)
        self.assertEqual(client.batch_usage()['reported_cost_usd'], 1.2)
        with self.assertRaises(BudgetExceeded):
            client.complete_json([Message('user', 'three')], SCHEMA)
        self.assertEqual(provider.calls, 2)

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

    def test_cache_rechecks_schema_and_preserves_actual_model(self):
        import json

        first_response = Completion('{"ok": true}', 'served-1', {'completion_tokens': 2}, 'request-1')
        next_response = Completion('{"ok": false}', 'served-2', {'completion_tokens': 3}, 'request-2')
        provider = FakeProvider(first_response, next_response)
        messages = [Message('user', 'x')]
        with tempfile.TemporaryDirectory() as directory:
            client = LLMClient(config(), provider=provider, cache_dir=directory)
            first = client.complete_json(messages, SCHEMA)
            second = client.complete_json(messages, SCHEMA)
            self.assertTrue(second.cached)
            self.assertEqual((second.model, second.usage, second.request_id),
                             (first.model, first.usage, first.request_id))
            path, = Path(directory).glob('*.json')
            value = json.loads(path.read_text())
            value['data']['ok'] = 'invalid'
            value['text'] = json.dumps(value['data'])
            path.write_text(json.dumps(value))
            repaired = client.complete_json(messages, SCHEMA)
        self.assertEqual(provider.calls, 2)
        self.assertFalse(repaired.cached)
        self.assertEqual(repaired.data, {'ok': False})
        self.assertEqual(repaired.model, 'served-2')

    def test_cache_isolated_by_provider_endpoint(self):
        messages = [Message('user', 'x')]
        with tempfile.TemporaryDirectory() as directory:
            for endpoint, response in (('https://old.example/v1', True), ('https://new.example/v1', False)):
                with self.subTest(endpoint=endpoint):
                    selected = ProviderConfig('fake', 'openai_compatible', base_url=endpoint)
                    text = '{"ok": true}' if response else '{"ok": false}'
                    provider = FakeProvider(Completion(text, 'served'))
                    client = LLMClient(config(providers={'fake': selected}), provider=provider, cache_dir=directory)
                    result = client.complete_json(messages, SCHEMA)
                    self.assertFalse(result.cached)
                    self.assertEqual(result.data['ok'], response)
                    self.assertEqual(provider.calls, 1)

    def test_semantically_invalid_output_is_not_cached(self):
        provider = FakeProvider(Completion('{"ok": false}', 'm'), Completion('{"ok": true}', 'm'))
        messages = [Message('user', 'x')]

        def validate(data):
            if not data['ok']:
                raise ValueError('invalid evidence')

        with tempfile.TemporaryDirectory() as directory:
            client = LLMClient(config(), provider=provider, cache_dir=directory)
            with self.assertRaisesRegex(ValueError, 'invalid evidence'):
                client.complete_json(messages, SCHEMA, validate=validate)
            self.assertEqual(list(Path(directory).glob('*.json')), [])
            self.assertTrue(client.complete_json(messages, SCHEMA, validate=validate).data['ok'])
