from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qecgraph.source.parser import parse_project


class ParserTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.entry = self.root / 'main.tex'

    def parse(self, source):
        self.entry.write_bytes(source.encode('utf-8'))
        return parse_project(self.entry)

    def test_opaque_declarations_and_literals_do_not_create_labels_or_references(self):
        parsed = self.parse(r"""
\newcommand{\ghost}[1]{\begin{lemma}\label{lem:ghost}#1\end{lemma}}
\begin{document}
\verb|\label{verb:ghost}| \lstinline[language=TeX]|\ref{ref:ghost}|
\begin{lemma}\label{lem:real}Visible \ref{lem:other}.\end{lemma}
\end{document}
""".lstrip())
        self.assertFalse([d for d in parsed['diagnostics'] if d['severity'] == 'error'])
        self.assertEqual([label for b in parsed['blocks'] for label in b['labels']], ['lem:real'])
        self.assertEqual([r['targets'] for b in parsed['blocks'] for r in b['references']], [['lem:other']])

    def test_percent_encoded_link_targets_preserve_bibliography_and_link_text(self):
        body = r"""\documentclass{article}
\usepackage{hyperref}
\begin{document}
\begin{thebibliography}{1}
\providecommand \href [0]{\@href}%
\providecommand \url [0]{\@url}%
\bibitem{device}
\href[page=1]{"https://example.invalid/é#:~:text=Virtex%C2%AE%20Plus"}{Device documentation}
\url{https://example.invalid/one%20two}
\nolinkurl{https://example.invalid/three%20four}
\end{thebibliography}
\begin{lemma}
\href{https://example.invalid/%20\ref{ghost}}{\label{lem:real}See \ref{lem:real}.}
% \label{comment:ghost}
\end{lemma}
\end{document}
"""
        source = body.replace('\n', '\r\n')
        parsed = self.parse(source)
        self.assertFalse([d for d in parsed['diagnostics'] if d['severity'] == 'error'])
        lemma, = [block for block in parsed['blocks'] if block['kind'] == 'lemma']
        self.assertEqual(lemma['labels'], ['lem:real'])
        self.assertEqual([ref['targets'] for ref in lemma['references']], [['lem:real']])
        span = lemma['source']
        self.assertEqual((span['line_start'], span['line_end']), (12, 15))
        self.assertEqual(lemma['latex'], source[span['char_start']:span['char_end']])

    def test_nested_inactive_branch_preserves_coordinates_of_the_live_branch(self):
        statement = r'\begin{lemma}\label{lem:visible}λ\end{lemma}'
        source = '\r\n'.join((
            r'\begin{document}',
            r'\iffalse\iftrue\input{absent}\fi',
            r'\else' + statement + r'\fi',
            r'\end{document}',
            '',
        ))
        parsed = self.parse(source)
        block, = parsed['blocks']
        span = block['source']
        self.assertEqual(block['labels'], ['lem:visible'])
        self.assertEqual(block['latex'], statement)
        self.assertEqual(source[span['char_start']:span['char_end']], statement)
        self.assertEqual((span['line_start'], span['line_end']), (3, 3))
        self.assertEqual(parsed['includes'], [])
        self.assertEqual({d['code'] for d in parsed['diagnostics']}, {'conditional_branch_selected'})

    def test_def_marks_a_macro_defined_for_a_decidable_ifdefined_branch(self):
        parsed = self.parse(r"""\documentclass{article}
\def\combined{}
\begin{document}
\ifdefined\combined
\section{Main}
\else
\section{Standalone}
\fi
\end{document}
""")
        titles = [block['title_tex'] for block in parsed['blocks'] if block['kind'] == 'section']
        self.assertEqual(titles, ['Main'])

    def test_metadata_outside_mathematics_is_downgraded_not_fatal(self):
        from qecgraph.core.graph import build_graph
        from qecgraph.validators import validate_graph_types

        parsed = self.parse(r"""\documentclass{article}
\begin{document}
\begin{remark}
A remark with \lean{Foo.bar} and a use \uses{lem:x}.
\end{remark}
\begin{lemma}\label{lem:x} A lemma.\end{lemma}
\end{document}
""")
        graph = build_graph(parsed, 'demo', '0' * 64)
        validate_graph_types(graph)
        kinds = {node['id']: node['kind'] for node in graph['nodes']}
        relations = {(edge['source'], edge['relation'], edge['target']) for edge in graph['edges']}
        self.assertTrue(any(kinds[source] == 'lean_declaration' and relation == 'describes' and kinds[target] == 'remark'
                            for source, relation, target in relations))
        self.assertTrue(any(kinds[source] == 'remark' and relation == 'references' and kinds[target] == 'lemma'
                            for source, relation, target in relations))
        codes = {diagnostic['code'] for diagnostic in graph['diagnostics']}
        self.assertIn('lean_metadata_outside_mathematics', codes)
        self.assertIn('uses_outside_mathematics', codes)

    def test_unclosed_conditional_records_the_structural_limit(self):
        parsed = self.parse(r'\begin{document}\iftrue Text \end{document}')
        incomplete = [d for d in parsed['diagnostics'] if d['code'] == 'structural_scan_incomplete']
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0]['severity'], 'error')
        self.assertIn('conditionals_not_evaluated', {d['code'] for d in parsed['diagnostics']})

    def test_bare_input_after_a_comment_keeps_the_source_span(self):
        (self.root / 'appendix.tex').write_text(r'\section{Appendix}\label{sec:appendix}', encoding='utf-8')
        invocation = '\\input% filename on next line\n appendix.tex'
        parsed = self.parse(invocation + '\n')
        include, = parsed['includes']
        self.assertEqual((include['from'], include['to']), ('main.tex', 'appendix.tex'))
        self.assertEqual(include['source']['char_end'], len(invocation))
        self.assertEqual(include['source']['line_end'], 2)
        self.assertEqual(parsed['blocks'][0]['labels'], ['sec:appendix'])
