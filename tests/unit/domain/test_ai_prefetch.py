import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.llm.client import LLMResult
from qecgraph.core.progress import phase, reporting, task
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
        from tests.support import enable_fixture_ai
        enable_fixture_ai(self.root)
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
        barrier = threading.Barrier(2)

        def complete(messages, schema, **kwargs):
            nonlocal active, maximum
            phase('Offline provider probe')
            barrier.wait(timeout=5)
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return LLMResult(data={'items': [], 'unresolved': []}, text='{}', model='m',
                             usage={}, request_id='r', attempts=1, cached=False,
                             run_id='run', prompt_sha256='p' * 64)

        events = []
        with reporting(events.append), task('Sync workspace'), patch(
                'qecgraph.llm.client.LLMClient.complete_json', side_effect=complete):
            result = self.ws.sync()
        self.assertEqual(result['status'], 'published')
        self.assertGreaterEqual(maximum, 2)
        self.assertTrue({'alpha.tar', 'beta.tar'} <= {event.label for event in events})
        self.assertEqual(sum(event.label == 'Offline provider probe' and event.state == 'running'
                             for event in events), 8)
        batch = [event for event in events if event.unit == 'AI tasks' and event.state == 'running']
        self.assertEqual([(event.completed, event.total) for event in batch], [(n, 8) for n in range(9)])
        # The screenshot's 3/8 state must occur before either whole paper is done.
        third = next(index for index, event in enumerate(events) if event.unit == 'AI tasks' and event.completed == 3)
        self.assertFalse(any(event.steps and event.state == 'finished' for event in events[:third]))
        plans = [event for event in events if event.steps]
        self.assertTrue(all(len(event.steps) == 4 for event in plans))
        finished = [event for event in plans if event.state == 'finished']
        self.assertEqual(len(finished), 2)
        self.assertTrue(all(event.completed == 4 and all(step.state == 'finished' for step in event.steps)
                            for event in finished))

    def test_failed_ai_step_remains_visible_and_retry_reuses_completed_steps(self):
        (self.root / 'inputs' / 'paper.tex').write_bytes(TEX)
        call = 0

        def complete(*args, **kwargs):
            nonlocal call
            call += 1
            if call == 2:
                raise ValueError('offline test failure')
            return LLMResult(data={'items': [], 'unresolved': []}, text='{}', model='m',
                             usage={}, request_id='r', attempts=1, cached=False,
                             run_id='run', prompt_sha256='p' * 64)

        events = []
        with reporting(events.append), patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=complete):
            self.ws.sync()
        plan = next(event for event in events if event.steps and event.state == 'partial')
        self.assertEqual((plan.completed, plan.total), (3, 4))
        self.assertEqual([step.state for step in plan.steps], ['finished', 'failed', 'finished', 'finished'])
        self.assertEqual(plan.steps[1].detail, 'offline test failure')
        batch = next(event for event in events if event.unit == 'AI tasks' and event.state == 'partial')
        self.assertEqual((batch.completed, batch.total), (3, 4))
        events.clear()
        with reporting(events.append), patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=complete):
            self.ws.sync()
        plan = next(event for event in events if event.steps and event.state == 'finished')
        self.assertEqual((plan.completed, plan.total, call), (4, 4, 5))
        self.assertEqual([step.state for step in plan.steps], ['reused', 'finished', 'reused', 'reused'])
        batch = [event.completed for event in events if event.unit == 'AI tasks' and event.state == 'running']
        self.assertEqual(batch, list(range(5)))

    def test_batch_includes_queued_papers_and_keeps_completed_paper_counts(self):
        config = self.root / 'qecgraph.toml'
        config.write_text(config.read_text().replace('max_parallel_packages = 2', 'max_parallel_packages = 1'))
        for marker in ('alpha', 'beta', 'gamma'):
            (self.root / 'inputs' / (marker + '.tar')).write_bytes(
                tar_bytes({'main.tex': TEX.replace(b'unique', marker.encode())}))
        events, counts_at_request = [], []

        def complete(*args, **kwargs):
            batch = next(event for event in reversed(events) if event.unit == 'AI tasks')
            counts_at_request.append((batch.completed, batch.total))
            return LLMResult(data={'items': [], 'unresolved': []}, text='{}', model='m',
                             usage={}, request_id='r', attempts=1, cached=False,
                             run_id='run', prompt_sha256='p' * 64)

        with reporting(events.append), patch('qecgraph.llm.client.LLMClient.complete_json', side_effect=complete):
            self.ws.sync()
        self.assertEqual(counts_at_request, [(n, 12) for n in range(12)])
