import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from qecgraph.llm.client import LLMClient
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


class ThoughtSkillTests(unittest.TestCase):
    def test_worked_example_survives_real_extraction_validation(self):
        # Exercise the instructions' own example so line numbers, quotations and
        # output fields cannot silently drift apart when the prompt is edited.
        skill = load_skill('extract_thoughts')
        examples = re.findall(r'```json\n(.*?)\n```', skill.body, re.DOTALL)
        self.assertEqual(len(examples), 2)
        evidence, expected = map(json.loads, examples)
        normalized = original_source(evidence['text'], evidence['projection_path'])

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
        self.assertEqual(result.proposal['provenance']['skill_version'], 2)
        self.assertEqual(result.proposal['normalization_id'], normalized.sha256)
        self.assertEqual(provider.messages[0].content, skill.system_prompt)
        self.assertEqual(json.loads(provider.messages[1].content)['text'], evidence['text'])
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
        self.assertEqual(new.proposal['provenance']['skill_version'], 2)

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
             ['paper.tex:2', 'paper.tex:4'], 'not verbatim'),
            ('Only simulated noise was studied.', ['paper.tex:2'], 'not verbatim'),
        ):
            with self.subTest(quote=quote), tempfile.TemporaryDirectory() as directory:
                item = {'category': 'conclusion', 'statement': quote, 'source_quote': quote,
                        'attribution': 'author_explicit', 'source_refs': refs}
                provider = FakeProvider(Completion(json.dumps({'items': [item], 'unresolved': []}), 'offline-model'))
                client = LLMClient(config(max_input_chars=30000), provider=provider, cache_dir=directory)
                with self.assertRaisesRegex(ExtractionError, error):
                    extract(normalized, client, 'extract_thoughts', projection_path='paper.tex')
                self.assertEqual(list(Path(directory).glob('*.json')), [])
