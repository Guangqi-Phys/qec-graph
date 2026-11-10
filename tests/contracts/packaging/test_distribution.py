import importlib.util
import unittest


from tests.support import ROOT
spec = importlib.util.spec_from_file_location(
    'qec_check_distribution', ROOT / 'tools' / 'check_distribution.py')
check_distribution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_distribution)


class DistributionMetadataTests(unittest.TestCase):
    def test_utf8_readme_round_trips_through_email_metadata(self):
        readme = '# QEC Graph\n\nA → B — provenance.\n'
        raw = (
            b'Version: 0.4.0rc1\n'
            b'License-Expression: MIT\n'
            b'License-File: LICENSE\n'
            b'Content-Type: text/markdown; charset=utf-8\n'
            b'Content-Transfer-Encoding: 8bit\n\n' + readme.encode('utf-8')
        )
        check_distribution._check_metadata(raw, '0.4.0rc1', readme)


if __name__ == '__main__':
    unittest.main()
