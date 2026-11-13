import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from qecgraph.llm.client import BudgetExceeded, LLMClient, ResponseSchemaError
from qecgraph.llm.extract import ExtractionError, extract
from qecgraph.llm.normalize import NormalizedSource, entrypoint_plan
from qecgraph.llm.providers.base import Completion
from qecgraph.llm.skills import load_skill
from tests.unit.domain.test_ai_client import FakeProvider, config


def original_source(text, path='paper.tex'):
    raw = text.encode('utf-8')
    return NormalizedSource('b' * 64, raw, entrypoint_plan(path), ({
        'normalized': {'byte_start': 0, 'byte_end': len(raw)},
        'origin': {'path': path, 'byte_start': 0, 'byte_end': len(raw)},
        'kind': 'original',
    },))


def invalid_provider(data):
    return FakeProvider(*(Completion(json.dumps(data), 'offline-model') for _ in range(2)))


class ThoughtSkillTests(unittest.TestCase):
    def test_one_correction_request_preserves_evidence_validation_and_provenance(self):
        text = 'Short source sentence.\n'
        item = {'category': 'problem', 'statement': 'A short explanation of the problem.', 'attribution': 'editorial_inference',
                'source_quote': 'Invented quote.', 'source_refs': ['paper.tex:1']}
        invalid = {'items': [item], 'unresolved': []}
        valid = copy.deepcopy(invalid)
        valid['items'][0]['source_quote'] = 'Short source sentence.'
        provider = FakeProvider(Completion(json.dumps(invalid), 'offline-model', request_id='failed-request'),
                                Completion(json.dumps(valid), 'offline-model', request_id='corrected-request'))
        with tempfile.TemporaryDirectory() as directory:
            client = LLMClient(config(max_input_chars=30000), provider=provider, cache_dir=directory)
            result = extract(original_source(text), client, 'extract_thoughts', projection_path='paper.tex')
            self.assertEqual(len(list(Path(directory).glob('*.json'))), 1)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result.data, valid)
        self.assertEqual(result.proposal['provenance']['request_id'], 'corrected-request')
        rejected, = result.proposal['provenance']['validation_retries']
        self.assertEqual(rejected['request_id'], 'failed-request')
        self.assertNotIn('text', rejected)
        self.assertNotEqual(rejected['prompt_sha256'], result.ai_result.prompt_sha256)

    def test_correction_does_not_bypass_full_request_budget(self):
        quote = 'Q' * 10000
        data = {'items': [{'category': 'problem', 'statement': 'A short answer.', 'source_quote': quote,
                           'attribution': 'editorial_inference', 'source_refs': ['paper.tex:1']}], 'unresolved': []}
        provider = FakeProvider(Completion(json.dumps(data), 'offline-model'))
        client = LLMClient(config(max_input_chars=30000), provider=provider)
        with self.assertRaises(BudgetExceeded):
            extract(original_source(quote), client, 'extract_thoughts', projection_path='paper.tex')
        self.assertEqual(provider.calls, 1)

    def test_numbered_multifile_evidence_preserves_unicode_and_short_quotes(self):
        main = original_source('Title\r\n\\input{body}\r\n', 'paper.tex')
        body = original_source('条件 é😀\r\nOnly simulated noise was studied.\r\n', 'body.tex')
        quote = 'Only simulated noise was studied.'
        response = {'items': [{'category': 'assumption', 'statement': 'Only simulated noise is considered.',
                               'attribution': 'editorial_inference', 'source_quote': quote,
                               'source_refs': ['body.tex:2']}], 'unresolved': []}

        class Provider(FakeProvider):
            def complete(self, messages, **kwargs):
                self.evidence = messages[1].content
                return super().complete(messages, **kwargs)

        provider = Provider(Completion(json.dumps(response), 'offline-model'))
        result = extract(main, LLMClient(config(max_input_chars=30000), provider=provider),
                         'extract_thoughts', projection_path='paper.tex', additional_sources={'body.tex': body})
        self.assertIn('1 | 条件 é😀\r\n2 | Only simulated noise was studied.\r\n', provider.evidence)
        self.assertEqual(result.proposal['evidence_sources'][1], {'path': 'body.tex', 'sha256': body.sha256})
        self.assertEqual(result.data, response)
        for refs, quoted, error in ((['paper.tex:2'], quote, 'not verbatim'),
                                     (['missing.tex:2'], quote, 'supplied projection'),
                                     (['body.tex:1-2'], '条件 é😀 Only simulated noise was studied.', 'must use English')):
            with self.subTest(refs=refs, quote=quoted):
                invalid = copy.deepcopy(response)
                invalid['items'][0].update(source_refs=refs, source_quote=quoted)
                client = LLMClient(config(max_input_chars=30000), provider=invalid_provider(invalid))
                with self.assertRaisesRegex(ExtractionError, error):
                    extract(main, client, 'extract_thoughts', projection_path='paper.tex',
                            additional_sources={'body.tex': body})

    def test_new_extraction_rejects_long_quotes_but_old_proposals_remain_readable(self):
        from qecgraph.llm.extract import validate_extraction
        quote = 'A' * 481
        data = {'items': [{'category': 'problem', 'statement': quote, 'source_quote': quote,
                           'attribution': 'author_explicit', 'source_refs': ['paper.tex:1']}], 'unresolved': []}
        self.assertEqual(validate_extraction('extract_thoughts', data), data)
        client = LLMClient(config(max_input_chars=30000), provider=invalid_provider(data))
        with self.assertRaisesRegex(ResponseSchemaError, 'maxLength'):
            extract(original_source(quote), client, 'extract_thoughts', projection_path='paper.tex')

        item = {**data['items'][0], 'statement': 'A', 'source_quote': 'A'}
        many = {'items': [item] * 19, 'unresolved': []}
        self.assertEqual(validate_extraction('extract_thoughts', many), many)
        client = LLMClient(config(max_input_chars=30000), provider=invalid_provider(many))
        with self.assertRaisesRegex(ResponseSchemaError, 'maxItems'):
            extract(original_source('A'), client, 'extract_thoughts', projection_path='paper.tex')

    def test_worked_example_survives_real_extraction_validation(self):
        # Exercise the instructions' own example so line numbers, quotations and
        # output fields cannot silently drift apart when the prompt is edited.
        skill = load_skill('extract_thoughts')
        examples = re.findall(r'```json\n(.*?)\n```', skill.body, re.DOTALL)
        self.assertEqual(len(examples), 2)
        evidence, expected = map(json.loads, examples)
        source_text = ''.join(row[1] for row in evidence['sources'][0]['lines'])
        normalized = original_source(source_text, evidence['projection_path'])

        class Provider(FakeProvider):
            def complete(self, messages, **kwargs):
                self.messages = messages
                return super().complete(messages, **kwargs)

        provider = Provider(Completion(json.dumps(expected), 'offline-model'))
        client = LLMClient(config(max_input_chars=30000), provider=provider)
        result = extract(normalized, client, 'extract_thoughts',
                         projection_path=evidence['projection_path'])
        self.assertEqual(result.data, expected)
        self.assertEqual(result.proposal['review_status'], 'proposed')
        self.assertEqual(result.proposal['provenance']['skill_version'], 7)
        self.assertEqual(result.proposal['normalization_id'], normalized.sha256)
        self.assertEqual(provider.messages[-1].content, 'Extraction task:\n' + skill.system_prompt)
        for number, line in evidence['sources'][0]['lines']:
            self.assertIn(f'{number} | ' + line, provider.messages[1].content)
        self.assertEqual({item['attribution'] for item in result.data['items']},
                         {'author_explicit', 'editorial_inference'})
        conclusion = next(item for item in result.data['items'] if item['category'] == 'conclusion')
        self.assertIn('idle errors excluded,\n', conclusion['statement'])
        self.assertIn('simulated range', conclusion['statement'])

    def test_changed_skill_uses_new_cache_entry_and_preserves_old_provenance(self):
        current = load_skill('extract_thoughts')
        response = {'items': [], 'unresolved': ['open_question: not extracted in this fixture']}
        provider = FakeProvider(*(Completion(json.dumps(response), 'offline-model') for _ in range(2)))
        normalized = original_source('Only simulated noise was studied.\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_pack = root / 'skills/extract_thoughts'
            old_pack.mkdir(parents=True)
            (old_pack / 'SKILL.md').write_text(
                '---\nname: extract_thoughts\ndescription: Previous fixture instructions.\n'
                'version: 1\n---\nReturn JSON with items and unresolved.\n', encoding='utf-8')
            (old_pack / 'prompt.md').write_text('Use the supplied source only.', encoding='utf-8')
            (old_pack / 'output.schema.json').write_text(json.dumps(current.schema), encoding='utf-8')
            client = LLMClient(config(max_input_chars=30000), provider=provider, cache_dir=root / 'cache')
            old = extract(normalized, client, 'extract_thoughts', extra_skills_dir=old_pack.parent)
            preserved = copy.deepcopy(old.proposal)
            new = extract(normalized, client, 'extract_thoughts')
            repeated = extract(normalized, client, 'extract_thoughts')
            self.assertEqual(len(list((root / 'cache').glob('*.json'))), 2)
        self.assertEqual(provider.calls, 2)
        self.assertFalse(new.ai_result.cached)
        self.assertTrue(repeated.ai_result.cached)
        self.assertNotEqual(old.ai_result.prompt_sha256, new.ai_result.prompt_sha256)
        self.assertEqual(old.proposal, preserved)
        self.assertEqual(old.proposal['provenance']['skill_version'], 1)
        self.assertEqual(new.proposal['provenance']['skill_version'], 7)

    def test_generated_and_stitched_quotes_are_rejected_before_caching(self):
        # Non-ASCII source bytes and an injected wrapper exercise the distinction
        # between original evidence, normalization text and inclusive line refs.
        original = '研究目标：降低开销。\nOnly simulated noise was studied.\nNo distance lower bound is claimed.\n'
        prefix = '\\begin{document}\n'.encode()
        normalized = original_source(original)
        raw = prefix + normalized.data
        normalized = NormalizedSource(normalized.source_tree_hash, raw, normalized.plan, (
            {'normalized': {'byte_start': 0, 'byte_end': len(prefix)}, 'origin': None, 'kind': 'injected'},
            {'normalized': {'byte_start': len(prefix), 'byte_end': len(raw)},
             'origin': {'path': 'paper.tex', 'byte_start': 0, 'byte_end': len(normalized.data)},
             'kind': 'original'},
        ))
        for quote, refs, error in (
            ('\\begin{document}', ['paper.tex:1'], 'no original text'),
            ('研究目标：降低开销。\nNo distance lower bound is claimed.',
             ['paper.tex:2', 'paper.tex:4'], 'must use English'),
            ('Only simulated noise was studied.', ['paper.tex:2'], 'not verbatim'),
        ):
            with self.subTest(quote=quote), tempfile.TemporaryDirectory() as directory:
                item = {'category': 'conclusion', 'statement': quote, 'source_quote': quote,
                        'attribution': 'author_explicit', 'source_refs': refs}
                provider = invalid_provider({'items': [item], 'unresolved': []})
                client = LLMClient(config(max_input_chars=30000), provider=provider, cache_dir=directory)
                with self.assertRaisesRegex(ExtractionError, error):
                    extract(normalized, client, 'extract_thoughts', projection_path='paper.tex')
                self.assertEqual(list(Path(directory).glob('*.json')), [])

    def test_quoted_paper_metadata_is_preserved_and_validated_without_thought_items(self):
        source = ('Surface codes under erasure\nAda Lovelace\n2025-06-15\n'
                  'https://example.org/paper\nWe study surface codes under erasure.\n')
        def evidence(value, line, quote=None):
            return {'value': value, 'source_quote': quote or value, 'source_refs': [f'paper.tex:{line}']}
        paper = {'title': evidence('Surface codes under erasure', 1),
                 'authors': [evidence('Ada Lovelace', 2)],
                 'published_date': evidence('2025-06-15', 3),
                 'link': evidence('https://example.org/paper', 4),
                 'topics': [evidence('surface codes', 5, 'We study surface codes under erasure.')]}
        response = {'items': [], 'unresolved': [], 'paper': paper}
        provider = FakeProvider(Completion(json.dumps(response), 'offline-model'))
        client = LLMClient(config(max_input_chars=30000), provider=provider)
        result = extract(original_source(source), client, 'extract_thoughts', projection_path='paper.tex')
        self.assertEqual(result.proposal['paper'], paper)
        self.assertEqual(result.proposal['review_status'], 'proposed')
        for field, replacement, error in (
            ('title', evidence('Invented title', 1), 'not verbatim'),
            ('authors', [evidence('Ada Lovelace', 4)], 'not verbatim'),
            ('published_date', evidence('2025-02-30', 3, '2025-06-15'), 'date is invalid'),
            ('published_date', evidence('2025/06', 3), 'date must be'),
            ('link', evidence('file:///private', 4), 'public HTTP'),
            ('link', evidence('https://example.org/invented', 4, 'https://example.org/paper'), 'quoted public'),
            ('topics', [evidence('erasure', 1, 'Invented quotation')], 'not verbatim'),
        ):
            with self.subTest(field=field, replacement=replacement), tempfile.TemporaryDirectory() as directory:
                invalid = copy.deepcopy(response)
                invalid['paper'][field] = replacement
                client = LLMClient(config(max_input_chars=30000), cache_dir=directory,
                                   provider=invalid_provider(invalid))
                with self.assertRaisesRegex(ExtractionError, error):
                    extract(original_source(source), client, 'extract_thoughts', projection_path='paper.tex')
                self.assertEqual(list(Path(directory).glob('*.json')), [])
