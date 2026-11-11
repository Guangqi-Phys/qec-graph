import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.llm.client import LLMResult
from qecgraph.llm.config import DEFAULT_MODEL
from qecgraph.workspace import Workspace
from tests.unit.parsing.test_source_package import tar_bytes

TEX = b'\\documentclass{article}\n\\begin{document}\n% unique\n\\section{Main}\nText.\n\\end{document}\n'


class PrefetchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.enterContext(patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'offline-test-key'}))
        self.root = Path(temp.name)
        self.ws = Workspace(self.root)
        self.ws.prepare()
        config = self.root / 'qecgraph.toml'
        text = config.read_text(encoding='utf-8')
        text = text.replace('provider = "openrouter"', 'provider = "claude_code"')
        text = text.replace(f'model = "{DEFAULT_MODEL}"', 'model = "prefetch-test"')
        text = text.replace('max_parallel_packages = 1', 'max_parallel_packages = 2')
        config.write_text(text, encoding='utf-8')

    def test_sync_extracts_multiple_registered_packages_concurrently(self):
        for marker in ('alpha', 'beta'):
            (self.root / 'inputs' / (marker + '.tar')).write_bytes(
                tar_bytes({'main.tex': TEX.replace(b'unique', marker.encode())}))
            (self.root / 'inputs' / (marker + '.tar')).parent.mkdir(exist_ok=True)
        active = 0
        maximum = 0
        lock = threading.Lock()

        def complete(messages, schema, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return LLMResult(data={'items': [], 'unresolved': []}, text='{}', model='m',
                             usage={}, request_id='r', attempts=1, cached=False,
                             run_id='run', prompt_sha256='p' * 64)

        with patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=complete):
            result = self.ws.sync()
        self.assertEqual(result['status'], 'published')
        self.assertGreaterEqual(maximum, 2)
