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

    def test_arxiv_number_is_searchable_without_changing_source_identity(self):
        from qecgraph.source.metadata import arxiv_identity

        names = ['2601.01234v2.tar.gz', '2601.01234v2.zip']
        self.assertEqual(arxiv_identity(None, names),
                         ('2601.01234v2', 'archive_filename', ['2601.01234v2']))
        self.assertEqual(arxiv_identity(None, [*names, '2512.12345.zip'])[:2], (None, None))
        self.assertEqual(arxiv_identity('https://arxiv.org/abs/quant-ph/9901001', names)[:2],
                         ('quant-ph/9901001', 'registered_url'))

        (self.root / 'inputs/2601.01234v2.tex').write_text(TEXT + '% A second paper\n')
        self.ws.sync()
        self.session = WorkspaceSession(self.ws.registry.root, profile='research')
        [paper] = self.invoke('qec_list_papers', {'query': '2601.01234v2'})['results']
        self.assertEqual(paper['arxiv_id'], '2601.01234v2')
        self.assertEqual(paper['arxiv_id_source'], 'archive_filename')
        self.assertNotEqual(paper['source_version_id'] if 'source_version_id' in paper else paper['id'],
                            paper['arxiv_id'])
        card = self.invoke('qec_fetch', {'identifier': paper['id'], 'view': 'card'})
        self.assertEqual(card['arxiv_id'], paper['arxiv_id'])
        self.assertIsNone(card['link'])

    def test_human_bytes_do_not_depend_on_unrelated_release_identity(self):
        from qecgraph.render.thoughts import QUESTIONS, render_pages
        original = render_pages(self.session)
        self.session.release = 'a' * 64
        self.assertEqual(original, render_pages(self.session))
        self.assertEqual(QUESTIONS[2][1], ('approach',))
        self.assertEqual(QUESTIONS[5][1], ('conclusion',))

    def test_internal_errors_are_diagnosable_without_exception_or_source_content(self):
        from unittest.mock import patch
        with patch.object(self.session.knowledge, 'search', side_effect=KeyError('secret-key-canary')):
            with self.assertLogs('qecgraph.workspace_query', level='ERROR') as logs:
                response = self.session.invoke('qec_search', {'query': 'secret-source-canary'})
        self.assertEqual(response['error']['code'], 'INTERNAL_ERROR')
        self.assertIn('KeyError', str(logs.output))
        self.assertNotIn('canary', str(logs.output) + canonical(response))
        with patch.object(self.ws, '_run_impl', side_effect=TypeError('secret-error-canary')):
            with self.assertRaises(TypeError):
                self.ws.sync()
        events = [json.loads(line) for path in (self.root / '.qecgraph/logs').glob('*.jsonl')
                  for line in path.read_text().splitlines()]
        failed = [event for event in events if event['status'] == 'failed']
        self.assertEqual(failed[-1]['error']['type'], 'TypeError')
        self.assertNotIn('canary', canonical(events))

    def test_fragment_context_carries_literal_macros_without_expansion(self):
        text = TEXT.replace('The memory survives.', r'The memory uses \rare.')
        text = text.replace(r'\begin{document}', r'% \newcommand{\fake}{do not collect}' + '\n' + r'\begin{document}')
        (self.root / 'inputs/macros.tex').write_text(text)
        self.ws.sync()
        session = WorkspaceSession(self.ws.registry.root, profile='research')
        node = next(n for n in session._source_nodes.values() if n['kind'] == 'lemma' and r'\rare' in n['latex'])
        data = session.invoke('qec_fetch', {'identifier': node['id']})['data']
        macro, = data['fragment_context']['macro_definitions']
        self.assertEqual(macro['name'], 'rare')
        source = macro['source']
        self.assertEqual(text[source['char_start']:source['char_end']], macro['latex'])
        self.assertIn(r'\rare', data['text'])
        self.assertNotIn('preamble-only-marker', data['text'])

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
        hits = self.invoke('qec_search', {'detail': 'full', 'query': 'preamble-only-marker', 'kind': 'source_file'})
        self.assertTrue(any(r['kind'] == 'source_file' for r in hits['results']))
        self.assertEqual(self.invoke('qec_fetch', {'identifier': intro['id'], 'view': 'reading'})['view'], 'reading')

    def test_default_search_returns_passages_with_exact_snippet_coordinates(self):
        rows = self.invoke('qec_search', {'detail': 'full', 'query': 'memory survives'})['results']
        self.assertTrue(rows)
        self.assertFalse(any(r['kind'] in {'source_file', 'document', 'section'} for r in rows))
        for row in rows:
            if source := row.get('excerpt_source'):
                self.assertEqual(TEXT[source['char_start']:source['char_end']], row['excerpt'])
                self.assertTrue(row['section_path'])

    def test_search_can_aggregate_source_matches_at_the_authored_section(self):
        result = self.invoke('qec_search', {'query': 'memory', 'unit': 'section', 'detail': 'full',
                                            'source_version_id': self.version, 'mode': 'keyword'})
        rows = result['results']
        method = next(row for row in rows if row['title'] == 'Method')
        self.assertEqual(method['kind'], 'section')
        self.assertEqual(method['section_path'], ['Introduction', 'Method'])
        match = self.invoke('qec_fetch', {'identifier': method['matched_occurrence_id']})
        self.assertIn('The memory survives.', match['text'])
        self.assertEqual(len({row['id'] for row in rows}), len(rows))

    def test_paper_title_does_not_make_unrelated_short_passages_match(self):
        (self.root / 'inputs/rank.tex').write_text(r'''\documentclass{article}
\title{Decoder study}
\begin{document}
Unrelated banana.

Decoder memory succeeds.
\end{document}''')
        self.ws.sync()
        session = WorkspaceSession(self.ws.registry.root, profile='research')
        version = next(v for v, paper in session.knowledge.papers.items() if paper['title'] == 'Decoder study')
        result = session.invoke('qec_search', {'query': 'decoder', 'source_version_id': version, 'detail': 'full'})
        self.assertTrue(result['ok'], result)
        rows = result['data']['results']
        self.assertEqual(len(rows), 1)
        self.assertIn('Decoder memory succeeds.', rows[0]['excerpt'])

    def test_paper_list_card_and_outline_are_navigation_views(self):
        papers = self.invoke('qec_list_papers', {})['results']
        self.assertEqual(len(papers), 1)
        card = self.invoke('qec_fetch', {'identifier': papers[0]['id'], 'view': 'card'})
        self.assertEqual(card['view'], 'card')
        self.assertLess(len(canonical(card)), 4000)
        outline = self.invoke('qec_fetch', {'identifier': self.version, 'view': 'outline'})['results']
        self.assertEqual([r['title'] for r in outline], ['Introduction', 'Method', 'Discussion'])
        self.assertTrue(all(r['kind'] == 'section' for r in outline))
        blocks = self.invoke('qec_fetch', {'identifier': self.version, 'view': 'outline', 'depth': 'blocks'})['results']
        self.assertIn('lemma', [r['kind'] for r in blocks])

    def test_paper_graph_has_paginated_sections_and_results(self):
        arguments = {'identifier': self.version, 'view': 'graph', 'limit': 3}
        first = self.invoke('qec_fetch', arguments)
        self.assertEqual(first['view'], 'graph')
        self.assertTrue(first['truncated'])
        self.assertEqual(first['continuation'], 3)
        page = first
        rows = list(first['results'])
        while page['truncated']:
            page = self.invoke('qec_fetch', {**arguments, 'offset': page['continuation']})
            rows.extend(page['results'])
        lemma = next(row for row in rows if row['type'] == 'node' and row['kind'] == 'lemma')
        method = next(row for row in rows if row['type'] == 'node' and row['title'] == 'Method')
        self.assertEqual(lemma['parent_id'], method['id'])
        self.assertEqual(self.invoke('qec_fetch', {'identifier': lemma['id']})['text'],
                         TEXT[lemma['source']['char_start']:lemma['source']['char_end']])
        self.assertEqual(first['total_matches'], len(rows))

    def test_resources_list_papers_and_source_bindings_survive_other_releases(self):
        listing = self.session.list_resources()['resources']
        self.assertEqual(len(listing), 1)
        self.assertTrue(listing[0]['uri'].startswith('qec://paper/'))
        self.assertTrue(self.session.resource_templates()['resourceTemplates'])
        root = next(n for n in self.session._source_nodes.values() if n['kind'] == 'lemma')
        uri = self.session._resource_uri(root['id'])
        from qecgraph.core.graph import hash_text
        from qecgraph.core.errors import ToolError
        legacy_uri = f'qec://source/{self.session.release}/{hash_text(root["id"])}'
        with self.assertRaises(ToolError):
            self.session.read_resource(legacy_uri)
        before = self.session.read_resource(uri)['contents'][0]['text']
        (self.root / 'inputs/second.tex').write_text(TEXT.replace('memory survives', 'another result'))
        self.ws.sync()
        next_session = WorkspaceSession(self.ws.registry.root, profile='research')
        self.assertNotEqual(self.session.release, next_session.release)
        self.assertEqual(before, next_session.read_resource(uri)['contents'][0]['text'])
        self.assertEqual(len(next_session.list_resources()['resources']), 2)

    def test_concise_search_handles_round_trip_and_full_detail_retains_identity(self):
        data = self.invoke('qec_search', {'query': 'memory', 'limit': 5})
        row = data['results'][0]
        self.assertTrue(row['id'].startswith('@'))
        fetched = self.invoke('qec_fetch', {'identifier': row['id']})
        self.assertTrue(fetched['id'] in self.session.knowledge.nodes)
        self.assertNotIn('coverage', data)
        full = self.invoke('qec_search', {'query': 'memory', 'limit': 5, 'detail': 'full'})
        self.assertEqual(full['results'][0]['handle'], row['id'])
        self.assertLessEqual(len(canonical(data)), 2500)

    def test_tool_descriptions_are_distinct_and_all_parameters_explained(self):
        tools = self.session._tool_descriptors
        descriptions = [t['description'] for t in tools]
        self.assertEqual(len(descriptions), len(set(descriptions)))
        for tool in tools:
            for name, schema in tool['inputSchema']['properties'].items():
                self.assertTrue(schema.get('description'), (tool['name'], name))

    def test_trace_budget_degrades_and_root_errors_are_actionable(self):
        root = next(n for n in self.session.knowledge.nodes.values() if n['kind'] == 'section')
        data = self.invoke('qec_trace', {'identifier': root['id'], 'max_chars': 3000})
        self.assertTrue(data['truncated'])
        self.assertEqual(data['nodes'][0]['latex'], root['latex'])
        self.assertLessEqual(len(canonical(data)), 3000)
        error = self.session.invoke('qec_trace', {'identifier': root['id'], 'max_chars': 256})['error']
        self.assertGreater(error['details']['required_chars'], 256)
        self.assertTrue(error['details']['suggestions'])

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
        self.assertEqual(self.invoke('qec_search', {'detail': 'full', 'query': 'PRIVATE-SECRET'})['results'], [])
        previous = self.session.release
        (self.root / 'inputs/new.tex').write_text(TEXT.replace('memory survives', 'novel observation'))
        self.ws.sync()
        self.assertEqual(self.invoke('qec_search', {'detail': 'full', 'query': 'novel observation'})['results'], [])
        self.assertEqual(self.session.release, previous)

    def test_generic_profile_returns_exact_mcp_shape_and_complete_evidence(self):
        from qecgraph.cli.parser import _build_parser
        from qecgraph.cli.commands.query import _ai_session
        args = _build_parser()[0].parse_args(['mcp', 'config', '--machine', str(self.ws.registry.root)])
        self.assertEqual(len(_ai_session(args).tools()), 8)
        args.profile = 'legacy'
        with self.assertRaises(ValueError):
            _ai_session(args)
        compatible = WorkspaceSession(self.ws.registry.root, profile='compatible')
        self.assertEqual({t['name'] for t in compatible.tools()}, {'search', 'fetch'})
        self.assertEqual(len(WorkspaceSession(self.ws.registry.root).tools()), 13)
        self.assertEqual(len(self.session.tools()), 8)
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
