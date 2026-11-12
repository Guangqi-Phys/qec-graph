import unittest

from qecgraph.llm.normalize import NormalizationError, assemble, inventory, single_root_plan
from qecgraph.source.package import SourceTree

MAIN = rb'''\documentclass{article}
\begin{document}
\section{Main}
\label{sec:main}
Text.
\appendix
\section{Appendix}
Appendix text.
\end{document}
'''
SUPP = rb'''\documentclass{article}
\begin{document}
\section{Supplement}
Supplement text.
\end{document}
'''


def tree(files):
    return SourceTree('tex', files)


class NormalizationTests(unittest.TestCase):
    def test_inventory_and_single_root_plan_round_trip(self):
        source = tree({'main.tex': MAIN})
        data = inventory(source)
        self.assertEqual(data['documents'][0]['path'], 'main.tex')
        plan = single_root_plan(source)
        result = assemble(source, plan)
        self.assertEqual(result.text, MAIN.decode())
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.segments[0]['origin']['path'], 'main.tex')

    def test_multi_root_plan_copies_body_and_appendix_with_mapping(self):
        source = tree({'paper.tex': MAIN, 'supplement.tex': SUPP})
        plan = {
            'status': 'ready',
            'documents': [
                {'path': 'paper.tex', 'role': 'main'},
                {'path': 'supplement.tex', 'role': 'supplement'},
            ],
            'operations': [
                {'op': 'use_preamble', 'source': 'paper.tex'},
                {'op': 'include_body', 'source': 'paper.tex'},
                {'op': 'append_appendix', 'source': 'paper.tex'},
                {'op': 'append_body', 'source': 'supplement.tex'},
            ],
            'label_renames': {},
            'unresolved': [],
        }
        result = assemble(source, plan)
        self.assertIn('Main', result.text)
        self.assertIn('Appendix', result.text)
        self.assertIn('Supplement', result.text)
        self.assertTrue(result.text.rstrip().endswith(r'\end{document}'))
        origins = {segment['origin']['path'] for segment in result.segments
                   if segment['origin'] is not None}
        self.assertEqual(origins, {'paper.tex', 'supplement.tex'})
        covered = b''.join(result.data[s['normalized']['byte_start']:s['normalized']['byte_end']]
                           for s in result.segments if s['kind'] == 'original')
        self.assertIn(b'Main', covered)

    def test_missing_source_and_duplicate_labels_are_rejected(self):
        source = tree({'paper.tex': MAIN})
        with self.assertRaisesRegex(NormalizationError, 'missing source'):
            assemble(source, {'status': 'ready', 'documents': [],
                              'operations': [{'op': 'include_body', 'source': 'missing.tex'}],
                              'label_renames': {}, 'unresolved': []})
        duplicate = MAIN.replace(b'Text.', b'Text.\n\\label{sec:main}\n')
        source = tree({'one.tex': duplicate, 'two.tex': duplicate})
        plan = {'status': 'ready', 'documents': [],
                'operations': [{'op': 'include_body', 'source': 'one.tex'},
                               {'op': 'include_body', 'source': 'two.tex'}],
                'label_renames': {}, 'unresolved': []}
        with self.assertRaisesRegex(NormalizationError, 'duplicate label'):
            assemble(source, plan)
