import unittest

from qecgraph.core.search import LexicalIndex, terms


class LexicalTests(unittest.TestCase):
    def test_natural_queries_rank_all_terms_before_partial(self):
        index = LexicalIndex({'a': 'Circuit-level\nnoise threshold using BP+OSD decoding.',
                              'b': 'Noise noise noise.', 'c': 'Unrelated content.'})
        for query in ('circuit-level noise threshold', 'BP OSD decoder',
                      'What is the circuit level noise threshold?'):
            ranked, matches = index.rank(query, {'a', 'b', 'c'})
            self.assertEqual(ranked[0], 'a')
            self.assertEqual(matches['a'], 'all_terms')
        self.assertEqual(index.rank('noise', {'c'})[0], [])

    def test_qec_brackets_and_whitespace_share_terms(self):
        self.assertEqual(terms('[[144,12,12]]'), terms(r'\llbracket 144,\,12,12 \rrbracket'))
