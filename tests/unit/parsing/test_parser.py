from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qecgraph.parser import parse_project


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

    def test_unclosed_conditional_records_the_structural_limit(self):
        parsed = self.parse(r'\begin{document}\iftrue Text \end{document}')
        self.assertIn('structural_scan_incomplete', {d['code'] for d in parsed['diagnostics']})
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
