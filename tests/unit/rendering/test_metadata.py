import unittest

from qecgraph.render.thoughts import _arxiv_months, _surname


class ThoughtMetadataTests(unittest.TestCase):
    def test_arxiv_names_with_versions_extensions_and_identifier_boundaries(self):
        for name, expected in (
            ('arXiv-2611.12971v2.tar.gz', {'2026-11'}),
            ('2611.12971', {'2026-11'}),
            ('arxiv_2611.12971v1 (1).gz', {'2026-11'}),
            ('0704.0001v1.tar', {'2007-04'}),
            ('1412.0001.tar.gz', {'2014-12'}),
            ('1501.00001.zip', {'2015-01'}),
            ('2613.12971.tar.gz', set()),
            ('2600.12971.tar.gz', set()),
            ('12611.12971.tar.gz', set()),
            ('2611.129710.tar.gz', set()),
            ('2611.1297.tar.gz', set()),
            ('0703.0001.tar.gz', set()),
            ('2611.12971v0.tar.gz', set()),
            ('notes2026-11.tex', set()),
        ):
            with self.subTest(name=name):
                self.assertEqual(_arxiv_months([name]), expected)

    def test_surname_retains_family_particles_hyphens_and_explicit_order(self):
        for name, expected in (
            ('Abbas B. Ziad', 'Ziad'), ('Diego Ruiz', 'Ruiz'), ('Ming Wang', 'Wang'),
            ('Ada Lovelace', 'Lovelace'), ('John Smith Jr.', 'Smith'),
            ('Barbara Terhal', 'Terhal'), ('Peter van Loock', 'van Loock'),
            ('Juan de la Cruz', 'de la Cruz'), ('Anne Smith-Jones', 'Smith-Jones'),
            ('de la Cruz, Juan', 'de la Cruz'), ('Lovelace, Ada', 'Lovelace'),
            ('SingleName', 'SingleName'), ('', ''),
        ):
            with self.subTest(name=name):
                self.assertEqual(_surname(name), expected)
