from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qecgraph.source.parser import parse_project


class ParserTests(unittest.TestCase):
    def test_bibitems_preserve_source_and_duplicate_keys_stay_ambiguous(self):
        from qecgraph.core.graph import build_graph
        text = r'''\documentclass{article}
\begin{document}
Citations \cite{one,duplicate}.
\begin{thebibliography}{9}
\bibitem[Author 2020]{one} Author. A {nested} title. 2020.
\bibitem{duplicate} First conflicting citation.
\bibitem{duplicate} Second conflicting citation.
\end{thebibliography}
\end{document}'''
        parsed = self.parse(text)
        entries = [b for b in parsed['blocks'] if b['kind'] == 'bib_entry']
        self.assertEqual(len(entries), 3)
        for entry in entries:
            span = entry['source']
            self.assertEqual(entry['latex'], text[span['char_start']:span['char_end']])
        graph = build_graph(parsed, 'bib-test', 'fixture')
        nodes = {n['id']: n for n in graph['nodes']}
        cited = [nodes[e['target']] for e in graph['edges'] if e['relation'] == 'cites']
        self.assertTrue(any(n['kind'] == 'bib_entry' and n['title'] == 'one' for n in cited))
        ambiguous = next(n for n in cited if n['kind'] == 'citation_key')
        self.assertEqual(ambiguous['data']['metadata_status'], 'ambiguous')
        self.assertEqual(len(ambiguous['data']['candidate_ids']), 2)

    def test_non_utf8_source_reports_encoding_without_changing_bytes(self):
        from qecgraph.source.package import PackageError, SourceTree
        raw = b'\\documentclass{article}\\begin{document}caf\xe9\\end{document}'
        tree = SourceTree('zip', {'main.tex': raw})
        with self.assertRaises(PackageError) as error:
            tree.entrypoints()
        self.assertEqual(error.exception.status, 'unsupported_encoding')
        self.entry.write_bytes(raw)
        parsed = parse_project(self.entry)
        self.assertIn('unsupported_source_encoding', [d['code'] for d in parsed['diagnostics']])
        self.assertEqual(self.entry.read_bytes(), raw)

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.entry = self.root / 'main.tex'

    def parse(self, source):
        self.entry.write_bytes(source.encode('utf-8'))
        return parse_project(self.entry)

    def test_physics_environments_keep_typed_verbatim_spans(self):
        text = r"""\documentclass{article}
\newtheorem{axi}{Assumption}
\newtheorem{mystery}{Unusual Heading}
\begin{document}
\begin{abstract}Our summary.\end{abstract}
\begin{axi}Independent errors.\end{axi}
\begin{notation}Let H denote a matrix.\end{notation}
\begin{algorithm}\caption{Decode}Run BP.\end{algorithm}
\begin{claim}A conclusion.\end{claim}
\begin{mystery}Another statement.\end{mystery}
\end{document}"""
        parsed = self.parse(text)
        blocks = {b['kind']: b for b in parsed['blocks']}
        for kind in ('abstract', 'assumption', 'notation', 'algorithm', 'claim', 'statement_other'):
            block = blocks[kind]
            span = block['source']
            self.assertEqual(block['latex'], text[span['char_start']:span['char_end']])
        self.assertEqual(blocks['algorithm']['title_tex'], 'Decode')
        self.assertEqual(blocks['statement_other']['heading'], 'Unusual Heading')

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
        self.assertNotIn('lean_declaration', kinds.values())
        self.assertTrue(any(kinds[source] == 'remark' and relation == 'references' and kinds[target] == 'lemma'
                            for source, relation, target in relations))
        codes = {diagnostic['code'] for diagnostic in graph['diagnostics']}
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
