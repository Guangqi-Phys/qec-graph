import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.llm.client import LLMResult
from qecgraph.workspace import Workspace
from tests.unit.parsing.test_source_package import TEX, tar_bytes


def answer(data):
    return LLMResult(data, json.dumps(data), 'fake', {}, None, 1, False, 'test-run', 'f' * 64)


class AIWorkspaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = Workspace(self.root)
        self.workspace.prepare()
        self.config = self.root / 'qecgraph.toml'
        self.configure('provider = "openrouter"', 'provider = "claude_code"')
        self.configure('model = ""', 'model = "fake"')

    def configure(self, old, new):
        self.config.write_text(self.config.read_text().replace(old, new))

    def test_independent_documents_stay_archived_and_unconsumed(self):
        package = self.root / 'inputs/papers.tar'
        package.write_bytes(tar_bytes({'a.tex': TEX, 'b.tex': TEX.replace(b'Hello', b'Independent paper')}))
        with patch('qecgraph.llm.client.LLMClient.complete_json', return_value=answer({
            'status': 'needs_review', 'documents': [], 'operations': [], 'unresolved': ['independent manuscripts'],
        })):
            result = self.workspace.sync()
        self.assertEqual(result['status'], 'partial_batch')
        self.assertEqual(result['inputs'][0]['status'], 'needs_entrypoint')
        self.assertFalse(result['inputs'][0]['input_consumed'])
        self.assertTrue(package.exists())
        state, _ = self.workspace.registry.read()
        self.assertEqual(state['versions'], {})
