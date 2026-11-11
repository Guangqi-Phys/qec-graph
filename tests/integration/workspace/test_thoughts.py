import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.core.graph import read_json
from qecgraph.domain.research import make_record
from qecgraph.domain.research_store import publish_records
from qecgraph.llm.config import DEFAULT_MODEL
from qecgraph.llm.extract import extract, ExtractionError
from qecgraph.llm.skills import load_skill
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from tests.unit.domain import test_ai_extract
from tests.unit.domain.test_ai_extract import result_with


class ThoughtTests(unittest.TestCase):
    def test_fake_provider_quotes_attribution_and_proposal_only(self):
        normalized = test_ai_extract.ExtractionRunnerTests().normalized()
        item = {'category': 'conclusion', 'statement': 'Theorem text.', 'source_quote': 'Theorem text.',
                'attribution': 'author_explicit', 'source_refs': ['main.tex:3']}

        class Client:
            def complete_json(self, messages, schema, **kwargs):
                self.messages = messages
                return result_with({'items': [item], 'unresolved': ['motivation not extracted']})

        result = extract(normalized, Client(), 'extract_thoughts')
        self.assertEqual(result.proposal['review_status'], 'proposed')
        self.assertEqual(result.proposal['provenance']['skill_version'], 4)
        for change in ({'source_quote': 'invented', 'statement': 'invented'},
                       {'attribution': 'verified'}, {'source_refs': ['private.md:1']},
                       {'statement': 'A paraphrase'}, {'category': 'hidden_reasoning'}):
            with self.subTest(change=change):
                original = copy.deepcopy(item)
                item.update(change)
                with self.assertRaises(ExtractionError):
                    extract(normalized, Client(), 'extract_thoughts')
                item.clear()
                item.update(original)
        item.update(attribution='editorial_inference', statement='An interpretation')
        self.assertEqual(extract(normalized, Client(), 'extract_thoughts').proposal['review_status'], 'proposed')
        self.assertEqual(len(load_skill('extract_thoughts').schema['properties']['items']['items']['properties']['category']['enum']), 9)

    def test_record_evidence_relations_search_and_rendering(self):
        from qecgraph.render.human import build_human
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'inputs').mkdir()
            (root / 'inputs/paper.tex').write_text('\\documentclass{article}\n\\begin{document}\nAn open question remains.\n\\end{document}\n')
            ws = Workspace(root)
            ws.init()
            session = WorkspaceSession(ws.registry.root)
            node = next(n for n in session._source_nodes.values() if 'An open question' in n['latex'])
            source = {'id': node['source']['source_version_id'], 'revision': node['source']['snapshot_id']}
            quote = node['latex']
            locator = {**node['source'], 'node_id': node['original_node_id'], 'node_content_sha256': node['content_sha256']}
            # Locators have a closed schema; graph-only coordinates are not record fields.
            locator = {k: locator[k] for k in ('source_version_id', 'snapshot_id', 'path', 'node_id',
                                               'node_content_sha256', 'char_start', 'char_end')}
            evidence = {'status': 'known', 'source_ref': source, 'source_locator': locator, 'method': 'manual_source_quote'}
            data = {'category': 'open_question', 'statement': quote, 'source_quote': quote,
                    'attribution': 'author_explicit', 'source_ref': source, 'related_refs': None}
            record = make_record('research_thought', 'thought:question', '1', data, source=source,
                                 method='manual_source_quote', evidence={
                                     '/data/statement': evidence, '/data/source_quote': evidence})
            before = ws.registry.read()[1]
            forged = copy.deepcopy(record)
            forged['data']['statement'] = forged['data']['source_quote'] = 'Fabricated quote'
            with self.assertRaisesRegex(ValueError, 'quotation differs'):
                publish_records(ws.registry, [forged])
            self.assertEqual(ws.registry.read()[1], before)
            publish_records(ws.registry, [record])
            session = WorkspaceSession(ws.registry.root, profile='research')
            result = session.invoke('qec_search', {'query': 'open question', 'kind': 'research_thought'})
            self.assertEqual(result['data']['results'][0]['id'], 'thought:question')
            fetched = session.invoke('qec_fetch', {'identifier': 'thought:question'})['data']['entity']
            self.assertEqual(fetched['field_evidence']['/data/related_refs']['status'], 'not_extracted')
            build_human(root)
            pages = list((root / 'human').rglob('*_thoughts.md'))
            self.assertEqual(len(pages), 1)
            self.assertIn('原文依据', pages[0].read_text())
            self.assertIn('author\\_explicit', pages[0].read_text())

    def test_workspace_defaults_write_thought_proposals_without_promotion(self):
        from qecgraph.render.human import build_human
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ws = Workspace(root)
            ws.prepare()
            config = root / 'qecgraph.toml'
            config.write_text(config.read_text().replace(f'model = "{DEFAULT_MODEL}"', 'model = "fake"'))
            (root / 'inputs/paper.tex').write_text('\\documentclass{article}\n\\begin{document}\nA question remains.\n\\end{document}\n')
            item = {'category': 'open_question', 'statement': 'A question remains.', 'source_quote': 'A question remains.',
                    'attribution': 'author_explicit', 'source_refs': ['main.tex:3']}
            def answer(messages, schema, **kwargs):
                return result_with({'items': [item] if 'research thought extractor' in messages[0].content else [], 'unresolved': []})
            with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-fixture'}), patch(
                    'qecgraph.llm.client.LLMClient.complete_json', side_effect=answer) as extraction:
                result = ws.sync()
                self.assertEqual(extraction.call_count, 4)
            self.assertEqual(result['status'], 'published', result)
            proposal = next((root / 'machine/ai/proposals').rglob('extract_thoughts-*.json'))
            self.assertEqual(read_json(proposal)['review_status'], 'proposed')
            self.assertFalse(any(r['kind'] == 'research_thought' for r in WorkspaceSession(root / 'machine').records.values()))
            session = WorkspaceSession(root / 'machine', profile='research')
            args = {'query': 'question', 'kind': 'research_thought_proposal'}
            self.assertEqual(session.invoke('qec_search', args)['data']['results'], [])
            found = session.invoke('qec_search', {**args, 'include_proposals': True})['data']['results']
            self.assertEqual(len(found), 1)
            fetched = session.invoke('qec_fetch', {'identifier': found[0]['id']})['data']
            self.assertEqual(fetched['proposal']['data'], item)
            self.assertEqual(fetched['proposal']['data']['source_quote'], 'A question remains.')
            self.assertEqual(fetched['evidence_status'], 'proposed')
            with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-fixture'}), patch(
                    'qecgraph.llm.client.LLMClient.complete_json',
                    side_effect=AssertionError('Human rendering must not extract again')) as extraction:
                rendered = build_human(root)
                self.assertEqual(build_human(root), rendered)
                extraction.assert_not_called()
            self.assertEqual(rendered['status'], 'current', rendered)
            page, = (root / 'human').rglob('*_thoughts.md')
            text = page.read_text()
            self.assertIn('AI 摘录（作者原文） · proposed', text)
            self.assertIn('```latex\nA question remains.\n```', text)
            self.assertIn('main\\.tex:3', text)
            self.assertEqual(text.count('尚无可用回答'), 8)
            self.assertFalse(any(r['kind'] == 'research_thought' for r in WorkspaceSession(root / 'machine').records.values()))

    def test_ai_paper_metadata_drives_obsidian_note_and_tampering_keeps_old_note(self):
        from qecgraph.render.human import build_human
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ws = Workspace(root)
            ws.prepare()
            source = ('\\documentclass{article}\n\\begin{document}\n'
                      'Surface codes: erasure study\n张三\nJune 2025\nhttps://example.org/paper\n'
                      'We study erasure decoding for surface codes.\n\\end{document}\n')
            (root / 'inputs/paper.tex').write_text(source, encoding='utf-8')
            def evidence(value, line, quote=None):
                return {'value': value, 'source_quote': quote or value, 'source_refs': [f'main.tex:{line}']}
            paper = {'title': evidence('Surface codes: erasure study', 3), 'authors': [evidence('张三', 4)],
                     'published_date': evidence('2025-06', 5, 'June 2025'),
                     'link': evidence('https://example.org/paper', 6),
                     'topics': [evidence('surface codes', 7, 'We study erasure decoding for surface codes.'),
                                evidence('擦除译码', 7, 'We study erasure decoding for surface codes.')]}
            item = {'category': 'problem', 'statement': '研究 surface code 中的擦除译码。',
                    'source_quote': 'We study erasure decoding for surface codes.',
                    'attribution': 'editorial_inference', 'source_refs': ['main.tex:7']}
            def answer(messages, schema, **kwargs):
                result = {'items': [], 'unresolved': []}
                if 'research thought extractor' in messages[0].content:
                    result.update(items=[item], paper=paper)
                return result_with(result)
            with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-fixture'}), patch(
                    'qecgraph.llm.client.LLMClient.complete_json', side_effect=answer):
                result = ws.sync()
            self.assertEqual(result['status'], 'published', result)
            rendered = build_human(root)
            self.assertEqual(rendered['status'], 'current', rendered)
            page, = (root / 'human').rglob('*_thoughts.md')
            self.assertEqual(page.relative_to(root / 'human').as_posix(), '2025/06/张三_Surface_codes_thoughts.md')
            before = page.read_bytes()
            self.assertTrue(before.decode().startswith('---\ntags:\n  - "surface-codes"\n  - "擦除译码"\n'
                            'link: "https://example.org/paper"\ntitle: "Surface codes: erasure study"\n'
                            'author:\n  - "张三"\n---\n'))
            self.assertIn('AI 回答 · proposed', before.decode())
            self.assertIn('研究 surface code 中的擦除译码', before.decode())
            proposal = next((root / 'machine/ai/proposals').rglob('extract_thoughts-*.json'))
            data = read_json(proposal)
            data['paper']['authors'][0]['value'] = 'Forged Author'
            proposal.write_text(json.dumps(data))
            self.assertEqual(build_human(root)['status'], 'human_stale')
            self.assertEqual(page.read_bytes(), before)
