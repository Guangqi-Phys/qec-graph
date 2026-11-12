import unittest

from qecgraph.source.extraction import _tuple_kind, notation_matches


class NotationTests(unittest.TestCase):
    def test_normalization_maps_back_to_original_unicode_range(self):
        for notation in ('[[144,12,12]]', r'\llbracket 144,\,12,~12 \rrbracket',
                         r'[\![144,\;12,12]\!]'):
            text = 'é: quantum code ' + notation + ' ends here.'
            matches = list(notation_matches(text))
            self.assertEqual(len(matches), 1)
            match = matches[0]
            self.assertEqual(text[match.start():match.end()], notation)
            self.assertEqual(match[0], notation)
            self.assertEqual([v.strip() for v in match[match.lastgroup].split(',')], ['144', '12', '12'])
            self.assertEqual(_tuple_kind({'latex': text, 'kind': 'paragraph'}, match, 3),
                             ('quantum', 'quantum_logical_count'))
