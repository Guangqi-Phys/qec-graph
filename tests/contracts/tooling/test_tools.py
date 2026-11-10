import os
import subprocess
import sys
import unittest
from pathlib import Path


from tests.support import ROOT
TOOLS = sorted(path for path in (ROOT / 'tools').glob('*.py'))


class RepositoryToolTests(unittest.TestCase):
    def test_all_repository_tools_expose_help(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        for tool in TOOLS:
            with self.subTest(tool=tool.name):
                result = subprocess.run(
                    [sys.executable, str(tool), '--help'], cwd=ROOT, env=env,
                    text=True, capture_output=True, timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                self.assertIn('usage', result.stdout.lower())


if __name__ == '__main__':
    unittest.main()
