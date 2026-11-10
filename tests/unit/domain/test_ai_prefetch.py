import hashlib
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.llm.client import LLMResult
from qecgraph.source.package import Limits
from qecgraph.workspace import Workspace
from tests.unit.parsing.test_source_package import tar_bytes

TEX = b'\\documentclass{article}\n\\begin{document}\n% unique\n\\section{Main}\nText.\n\\end{document}\n'


class PrefetchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ws = Workspace(self.root)
        self.ws.prepare()
        config = self.root / 'qecgraph.toml'
        text = config.read_text(encoding='utf-8')
        text = text.replace('provider = "openrouter"', 'provider = "claude_code"')
        text = text.replace('model = ""', 'model = "prefetch-test"')
        text = text.replace('max_parallel_packages = 1', 'max_parallel_packages = 2')
        config.write_text(text, encoding='utf-8')

    def package(self, marker):
        raw = tar_bytes({'main.tex': TEX.replace(b'unique', marker.encode())})
        digest = hashlib.sha256(raw).hexdigest()
        path = self.root / 'archive/blobs/sha256' / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return digest

    def test_sync_invokes_parallel_prefetch_for_multiple_new_packages(self):
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

    def test_prefetch_runs_ai_extraction_for_multiple_packages_concurrently(self):
        digests = [self.package('one'), self.package('two')]
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
            result = self.ws._ai_prefetch(digests, Limits())
        self.assertEqual(result['packages'], 2)
        self.assertGreaterEqual(maximum, 2)
        self.assertTrue((self.root / 'machine/derived/normalizations').is_dir())
