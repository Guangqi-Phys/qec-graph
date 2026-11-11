import copy
import json
from pathlib import Path
import tempfile
import unittest

from qecgraph.core.language import require_english
from qecgraph.llm.client import LLMClient, ResponseSchemaError
from qecgraph.llm.extract import extract
from qecgraph.llm.providers.base import Completion, Message
from tests.unit.domain.test_ai_client import FakeProvider, config
from tests.unit.domain.test_ai_thoughts import original_source


class OutputLanguageTests(unittest.TestCase):
    def test_english_math_and_accented_names_are_allowed_but_cjk_is_rejected(self):
        require_english({'statement': 'René studies α ≤ β for LDPC codes.'})
        for value in ({'unresolved': ['缺少证据']}, {'paper': {'topics': [{'value': '量子纠错'}]}},
                      {'中文': 'English value'}, ['\U00020000']):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'must use English'):
                require_english(value)

    def test_client_rejects_escaped_chinese_before_caching(self):
        schema = {'type': 'object'}
        provider = FakeProvider(Completion(json.dumps({'unresolved': ['缺少证据']}), 'offline'))
        with tempfile.TemporaryDirectory() as directory:
            client = LLMClient(config(), provider=provider, cache_dir=directory)
            with self.assertRaisesRegex(ResponseSchemaError, 'must use English'):
                client.complete_json([Message('user', 'Return English JSON.')], schema)
            self.assertEqual(list(Path(directory).glob('*.json')), [])

    def test_language_failure_is_repaired_without_translating_source_evidence(self):
        quote = 'Only simulated noise was studied.'
        invalid = {'items': [{'category': 'assumption', 'statement': '只研究模拟噪声。',
                             'attribution': 'editorial_inference', 'source_quote': quote,
                             'source_refs': ['paper.tex:1']}], 'unresolved': ['限制：模拟结果']}
        valid = copy.deepcopy(invalid)
        valid['items'][0]['statement'] = 'The study is limited to simulated noise.'
        valid['unresolved'] = ['Scope: simulation results only.']
        provider = FakeProvider(Completion(json.dumps(invalid), 'offline'),
                                Completion(json.dumps(valid), 'offline'))
        result = extract(original_source(quote), LLMClient(config(max_input_chars=30000), provider=provider),
                         'extract_thoughts', projection_path='paper.tex')
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result.data, valid)
        self.assertEqual(result.data['items'][0]['source_quote'], quote)
        require_english(result.proposal)

    def test_cached_chinese_is_replaced_by_a_validated_english_response(self):
        provider = FakeProvider(Completion('{"answer":"First answer"}', 'offline'),
                                Completion('{"answer":"English replacement"}', 'offline'))
        with tempfile.TemporaryDirectory() as directory:
            client = LLMClient(config(), provider=provider, cache_dir=directory)
            messages = [Message('user', 'Return English JSON.')]
            client.complete_json(messages, {'type': 'object'})
            path, = Path(directory).glob('*.json')
            old = json.loads(path.read_text())
            old.update(data={'answer': '旧回答'}, text=json.dumps({'answer': '旧回答'}))
            path.write_text(json.dumps(old))
            result = client.complete_json(messages, {'type': 'object'})
            self.assertFalse(result.cached)
            self.assertEqual(result.data['answer'], 'English replacement')
            require_english(json.loads(path.read_text()))
        self.assertEqual(provider.calls, 2)

    def test_bundled_software_catalog_has_english_only_output(self):
        root = Path(__file__).resolve().parents[3]
        require_english(json.loads((root / 'qecgraph/catalog/software_catalog.seed.json').read_text()))
