import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from qecgraph.source.bibliography import citation_identifiers
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession


class BibliographyTests(unittest.TestCase):
    def test_literal_fields_and_trusted_identifier_hosts(self):
        self.assertEqual(citation_identifiers(
            '@article(x, title={arXiv:1111.11111}, doi="10.1234/A(B)", '
            'eprint={2512.12345v2}, archivePrefix={arXiv})'),
            ['arxiv:2512.12345v2', 'doi:10.1234/a(b)'])
        self.assertEqual(citation_identifiers(
            '@article{x, url={https://example.org/arxiv.org/abs/2512.12345}, '
            'eprint={2512.12345}, eprinttype={other}}'), [])

    def test_published_edge_requires_a_citation_and_a_unique_registered_identity(self):
        tex = r'''\documentclass{article}
\begin{document}
Previous work \cite{target,duplicate,missing}.
\bibliography{references}
\end{document}'''
        bib = ('@misc{target, title={An earlier result}, eprint={2512.12345v2}}\r\n'
               '@misc{unused, eprint={2512.12345v2}}\r\n'
               '@misc{duplicate, eprint={2512.12345v2}}\r\n'
               '@misc{duplicate, title={A second entry}}\r\n')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inbox = root / 'inputs'
            inbox.mkdir()
            with tarfile.open(inbox / 'citing.tar.gz', 'w:gz') as archive:
                for name, content in [('main.tex', tex), ('references.bib', bib)]:
                    data = content.encode()
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            (inbox / 'target.tex').write_text(r'\documentclass{article}\begin{document}An earlier result.\end{document}')
            workspace = Workspace(root)
            workspace.init()
            state, _ = workspace.registry.read()
            target = next(m for m in state['materials'].values() if 'target.tex' in m.get('original_names', []))
            with (root / 'qecgraph.toml').open('a') as config:
                config.write(f'\n[sources."{target["source_tree_hash"]}"]\nwork_id = "{target["work_id"]}"\n'
                             'canonical_url = "https://arxiv.org/abs/2512.12345v2"\n')
            workspace.rebuild()
            session = WorkspaceSession(workspace.registry.root, profile='research')
            graph = session.graph.source.graph
            link, = [edge for edge in graph['edges'] if edge['relation'] == 'cites_paper']
            self.assertEqual(link['evidence']['identifiers'], ['arxiv:2512.12345v2'])
            source = link['evidence']['source']
            self.assertEqual(source['path'], 'references.bib')
            result = session.invoke('qec_fetch', {'identifier': link['source']})
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['data']['text'], bib[source['char_start']:source['char_end']])
            ambiguous = next(node for node in graph['nodes'] if node['title'] == 'duplicate'
                             and node['kind'] == 'citation_key')
            self.assertEqual(ambiguous['data']['metadata_status'], 'ambiguous')
            self.assertEqual(len(ambiguous['data']['candidate_ids']), 2)
