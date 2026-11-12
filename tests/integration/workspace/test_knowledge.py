import json
from pathlib import Path
import tempfile
import unittest

from qecgraph.core.graph import canonical
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from qecgraph.mcp.server import MCPServer
from tests.integration.mcp.test_mcp import initialization, request


TEXT = r'''\documentclass{article}
\newcommand{\rare}{preamble-only-marker}
\begin{document}
\section{Introduction}
Motivation α: protecting memories.
\subsection{Method}
\begin{definition}A protected state.\end{definition}
\begin{lemma}\label{lem:memory}The memory survives.\end{lemma}
\section{Discussion}
An open problem remains.
\end{document}
'''


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'inputs').mkdir()
        (self.root / 'inputs/paper.tex').write_text(TEXT)
        self.ws = Workspace(self.root)
        self.ws.init()
        state, _ = self.ws.registry.read()
        self.version = next(iter(state['versions']))
        material = next(iter(state['materials'].values()))
        with (self.root / 'qecgraph.toml').open('a') as f:
            f.write('\n[sources."' + material['source_tree_hash'] + '"]\nwork_id = "' + material['work_id'] +
                    '"\ncanonical_url = "https://example.org/paper/v1"\n')
        self.ws.rebuild()
        self.session = WorkspaceSession(self.ws.registry.root, profile='research')
        self.version = next(iter(self.session.state['versions']))

    def invoke(self, tool, args):
        response = self.session.invoke(tool, args)
        self.assertTrue(response['ok'], response)
        return response['data']

    def test_source_metadata_is_shared_with_machine_queries(self):
        from qecgraph.source.metadata import literal_metadata
        text = r"""\title{Quantum Memories}
\author{Ada Smith}
\begin{abstract}A protected memory.\end{abstract}"""
        metadata = literal_metadata(text)
        self.assertEqual(metadata['title'], 'Quantum Memories')
        self.assertEqual(metadata['authors'], ['Ada Smith'])
        papers = self.session.knowledge.papers
        self.assertEqual(papers[self.version]['link'], 'https://example.org/paper/v1')
        self.assertEqual(papers[self.version]['field_evidence']['link']['status'], 'user_confirmed')

    def test_whole_file_section_outline_and_raw_fallback(self):
        page = self.invoke('qec_fetch', {'identifier': self.version, 'view': 'outline'})
        intro = next(r for r in page['results'] if r['title'] == 'Introduction')
        method = next(r for r in page['results'] if r['title'] == 'Method')
        self.assertEqual(method['parent_id'], intro['id'])
        section = self.invoke('qec_fetch', {'identifier': intro['id']})
        self.assertIn('The memory survives.', section['text'])
        self.assertNotIn('An open problem', section['text'])
        self.assertEqual(TEXT[slice(*section['unit_range'])], section['text'])
        whole = self.invoke('qec_fetch', {'identifier': self.version})
        self.assertEqual(whole['files'][0]['text'], TEXT)
        # Text outside parser blocks remains discoverable.
        hits = self.invoke('qec_search', {'query': 'preamble-only-marker'})
        self.assertTrue(any(r['kind'] == 'source_file' for r in hits['results']))
        self.assertEqual(self.invoke('qec_fetch', {'identifier': intro['id'], 'view': 'reading'})['view'], 'reading')

    def test_versions_ranges_budgets_and_private_notes(self):
        outline = self.invoke('qec_fetch', {'identifier': self.version, 'view': 'outline', 'limit': 2})
        rest = self.invoke('qec_fetch', {'identifier': self.version, 'view': 'outline', 'offset': 2})
        self.assertFalse({r['id'] for r in outline['results']} & {r['id'] for r in rest['results']})
        self.assertTrue(outline['truncated'])
        file = next(n for n in self.session.knowledge.nodes.values() if n['kind'] == 'source_file')
        small = self.invoke('qec_fetch', {'identifier': file['id'], 'char_start': 10, 'char_end': 30})
        self.assertEqual(small['text'], TEXT[10:30])
        self.assertFalse(small['complete_unit'])
        self.assertEqual(self.session.invoke('qec_fetch', {'identifier': file['id'], 'char_end': 99999})['error']['code'], 'INVALID_ARGUMENT')
        self.assertEqual(self.session.invoke('qec_fetch', {'identifier': self.version, 'max_chars': 256})['error']['code'], 'BUDGET_TOO_SMALL')
        self.assertEqual(self.session.invoke('qec_fetch', {'identifier': self.version, 'source_version_id': 'v2'})['error']['code'], 'SOURCE_VERSION_UNAVAILABLE')
        notes = self.root / 'human/notes'
        notes.mkdir(parents=True, exist_ok=True)
        (notes / 'private.md').write_text('PRIVATE-SECRET')
        self.assertEqual(self.invoke('qec_search', {'query': 'PRIVATE-SECRET'})['results'], [])
        previous = self.session.release
        (self.root / 'inputs/new.tex').write_text(TEXT.replace('memory survives', 'novel observation'))
        self.ws.sync()
        self.assertEqual(self.invoke('qec_search', {'query': 'novel observation'})['results'], [])
        self.assertEqual(self.session.release, previous)

    def test_generic_profile_returns_exact_mcp_shape_and_complete_evidence(self):
        compatible = WorkspaceSession(self.ws.registry.root, profile='compatible')
        self.assertEqual({t['name'] for t in compatible.tools()}, {'search', 'fetch'})
        self.assertEqual(len(WorkspaceSession(self.ws.registry.root).tools()), 13)
        self.assertEqual(len(self.session.tools()), 7)
        server = MCPServer(compatible)
        server.handle(initialization())
        server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        response = server.handle(request(2, 'tools/call', {'name': 'search', 'arguments': {'query': 'memory survives'}}))
        result = response['result']
        payload = result['structuredContent']
        self.assertEqual(json.loads(result['content'][0]['text']), payload)
        self.assertEqual(set(payload), {'results'})
        hit = payload['results'][0]
        self.assertEqual(hit['url'], 'https://example.org/paper/v1')
        fetched = compatible.invoke('fetch', {'id': hit['id']})
        self.assertTrue(fetched['ok'], fetched)
        self.assertIn('memory survives', fetched['data']['text'])
        self.assertEqual(set(fetched['data']), {'id', 'title', 'url', 'text', 'metadata'})
        constrained = WorkspaceSession(self.ws.registry.root, profile='compatible', max_chars=256)
        self.assertEqual(constrained.invoke('fetch', {'id': hit['id']})['error']['code'], 'BUDGET_TOO_SMALL')

    def test_tampered_source_bytes_are_not_served(self):
        file = next(n for n in self.session.knowledge.nodes.values() if n['kind'] == 'source_file')
        version = self.session.state['versions'][self.version]
        path = self.session.machine / version['snapshot_path'] / 'sources' / file['data']['path']
        path.write_text(TEXT + 'corruption')
        self.assertFalse(self.session.invoke('qec_fetch', {'identifier': file['id']})['ok'])

    def test_coverage_reports_fields_and_metadata_only_inputs(self):
        (self.root / 'inputs/broken').write_bytes(b'PK\x03\x04bad')
        self.ws.sync()
        session = WorkspaceSession(self.ws.registry.root, profile='research')
        data = session.invoke('qec_status', {})['data']
        self.assertTrue(data['knowledge_coverage']['metadata_only_materials'])
        self.assertIn(self.version, data['knowledge_coverage']['full_text_versions'])
        self.assertNotIn('human/notes', canonical(data))
