import json
import unittest

from qecgraph.llm.errors import ProviderError
from qecgraph.llm.providers.base import HttpResult, Message
from qecgraph.llm.providers.openai import OpenAICompatibleProvider


class FakeTransport:
    def __init__(self, status=200, body=None, headers=None, error=None):
        self.status = status
        self.body = body if body is not None else b'{}'
        self.headers = headers or {}
        self.error = error
        self.requests = []

    def request(self, method, url, *, headers, body, timeout):
        self.requests.append((method, url, headers, json.loads(body), timeout))
        if self.error:
            raise self.error
        return HttpResult(self.status, self.headers, self.body)


def response(text='{"ok": true}', model='test-model'):
    return json.dumps({'id': 'req-1', 'model': model, 'choices': [{'message': {'content': text},
                                                                   'finish_reason': 'stop'}],
                       'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}).encode()


class OpenAIProviderTests(unittest.TestCase):
    def provider(self, transport):
        return OpenAICompatibleProvider('openrouter', base_url='https://example.test/v1',
                                       api_key='secret', transport=transport)

    def test_posts_messages_and_structured_output_schema(self):
        transport = FakeTransport(body=response())
        completion = self.provider(transport).complete(
            [Message('system', 'system'), Message('user', 'paper text')], model='model-x',
            response_schema={'type': 'object', 'properties': {'ok': {'type': 'boolean'}}},
            max_output_tokens=100, timeout=9)
        self.assertEqual(completion.text, '{"ok": true}')
        self.assertEqual(completion.request_id, 'req-1')
        method, url, headers, payload, timeout = transport.requests[0]
        self.assertEqual((method, url, timeout), ('POST', 'https://example.test/v1/chat/completions', 9))
        self.assertEqual(headers['Authorization'], 'Bearer secret')
        self.assertEqual(payload['model'], 'model-x')
        self.assertEqual(payload['messages'][1]['content'], 'paper text')
        self.assertEqual(payload['response_format']['type'], 'json_schema')

    def test_http_and_transport_errors_are_typed(self):
        transport = FakeTransport(status=429, body=b'{"error": {"message": "slow down"}}')
        with self.assertRaises(ProviderError) as caught:
            self.provider(transport).complete([Message('user', 'x')], model='m')
        self.assertTrue(caught.exception.retryable)
        self.assertIn('slow down', str(caught.exception))

        transport = FakeTransport(error=ConnectionError('offline'))
        with self.assertRaises(ProviderError) as caught:
            self.provider(transport).complete([Message('user', 'x')], model='m')
        self.assertTrue(caught.exception.retryable)

    def test_invalid_json_and_empty_choices_are_rejected(self):
        with self.assertRaises(ProviderError):
            self.provider(FakeTransport(body=b'not json')).complete([Message('user', 'x')], model='m')
        with self.assertRaises(ProviderError):
            self.provider(FakeTransport(body=b'{"choices": []}')).complete([Message('user', 'x')], model='m')
