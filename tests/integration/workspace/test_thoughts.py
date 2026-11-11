import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.core.graph import read_json
from qecgraph.domain.research import make_record
from qecgraph.domain.research_store import publish_records
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
        self.assertEqual(result.proposal['provenance']['skill_version'], 1)
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
            pages = list((root / 'human/generated/thoughts').glob('research-thought--*.md'))
            self.assertEqual(len(pages), 1)
            self.assertIn('Author quotation', pages[0].read_text())
            self.assertIn('author_explicit', pages[0].read_text())

    def test_workspace_opt_in_writes_thought_proposals_without_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ws = Workspace(root)
            ws.prepare()
            config = root / 'qecgraph.toml'
            config.write_text(config.read_text().replace('model = ""', 'model = "fake"').replace(
                'extract_proposals = false', 'extract_proposals = true'))
            (root / 'inputs/paper.tex').write_text('\\documentclass{article}\n\\begin{document}\nA question remains.\n\\end{document}\n')
            item = {'category': 'open_question', 'statement': 'A question remains.', 'source_quote': 'A question remains.',
                    'attribution': 'author_explicit', 'source_refs': ['main.tex:3']}
            def answer(messages, schema, **kwargs):
                return result_with({'items': [item] if 'research thought extractor' in messages[0].content else [], 'unresolved': []})
            with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-fixture'}), patch(
                    'qecgraph.llm.client.LLMClient.complete_json', side_effect=answer):
                result = ws.sync()
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
            self.assertEqual(fetched['proposal']['data']['source_quote'], 'A question remains.')
            self.assertEqual(fetched['evidence_status'], 'proposed')
