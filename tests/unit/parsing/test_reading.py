import hashlib
import tempfile
import unittest
from pathlib import Path

from qecgraph.core.graph import build_graph
from qecgraph.source.parser import parse_project
from qecgraph.source.reading import reading_projection


class ReadingProjectionTests(unittest.TestCase):
    def test_only_supported_markup_is_removed_and_citations_keep_offsets(self):
        citation = r'\citep[see][p.~3]{first,second}'
        source = (r'\textbf{中文 \emph{body}} ' + citation + '\r\n'
                  + r'$d=\frac{a}{b}$ \verb|\cite{literal}| \href{https://e.invalid/%20}{link}'
                  + '\n% \\cite{comment}\n' + r'\unknown{λ}')
        view, citations = reading_projection(source)
        self.assertIn('中文 body', view)
        self.assertIn(r'$d=\frac{a}{b}$', view)
        self.assertIn(r'\verb|\cite{literal}| link', view)
        self.assertIn(r'\unknown{λ}', view)
        self.assertNotIn('%20', view)
        self.assertNotIn('first', view)
        start, end, command, keys = citations[0]
        self.assertEqual(len(citations), 1)
        self.assertEqual(source[start:end], citation)
        self.assertEqual((command, keys), ('citep', ['first', 'second']))

    def test_graph_keeps_verbatim_bibliography_and_citation_relations(self):
        source = r"""\begin{document}
A \emph{paper}\cite{device}.
\begin{thebibliography}{1}
\bibitem{device} Reference title
\end{thebibliography}
Further prose.
\end{document}
""".replace('\n', '\r\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'paper.tex'
            path.write_bytes(source.encode())
            graph = build_graph(parse_project(path), 'paper', '0' * 64)
            bibliography, = [node for node in graph['nodes'] if node.get('source_role') == 'bibliography'
                              and node['kind'] != 'bib_entry']
        self.assertEqual(bibliography['reading_text'], '')
        span = bibliography['source']
        self.assertEqual(source[span['char_start']:span['char_end']], bibliography['latex'])
        self.assertEqual(span['file_sha256'], hashlib.sha256(source.encode()).hexdigest())
        prose, = [node for node in graph['nodes'] if node.get('reading_text') == 'A paper.']
        self.assertTrue(any(edge['relation'] == 'cites' and edge['source'] == prose['id'] for edge in graph['edges']))
        self.assertIn('Further prose.', [node.get('reading_text') for node in graph['nodes']])

    def test_old_snapshot_paragraph_keeps_prose_around_bibliography(self):
        from qecgraph.source.reading import source_reading_text

        raw = ('Before.\n' + r'\begin{thebibliography}{1}\bibitem{a}Hidden\end{thebibliography}'
               + '\nAfter.')
        self.assertEqual(source_reading_text({'kind': 'paragraph', 'latex': raw}), 'Before.\n\nAfter.')
