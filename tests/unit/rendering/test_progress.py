import io
import os
import re
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

from qecgraph.cli.commands import HANDLERS
from qecgraph.cli.progress import ACTIVITIES, CommandProgress, cell_width, clean, metrics
from qecgraph.core.progress import ProgressEvent, ProgressStep, hide, phase, reporting, task, track


def visible_terminal_text(output, columns=80):
    """Replay cursor-up/erase operations: raw captures still contain erased text."""
    rows = ['']
    y = x = 0
    for token in re.findall(r'\x1b\[[0-9;]*[mAJ]|[^\x1b]', output):
        if token.startswith('\x1b['):
            if token.endswith('A'):
                y = max(0, y - int(token[2:-1] or '1'))
            elif token.endswith('J'):
                rows[y] = rows[y][:x]
                del rows[y + 1:]
        elif token == '\r':
            x = 0
        elif token == '\n':
            y += 1
            x = 0
            if y == len(rows):
                rows.append('')
        else:
            if x == columns:
                y += 1
                x = 0
                if y == len(rows):
                    rows.append('')
            rows[y] = rows[y][:x].ljust(x) + token + rows[y][x + 1:]
            x += 1
    return '\n'.join(rows)


class Terminal(io.StringIO):
    encoding = 'utf-8'

    def isatty(self):
        return True


class ProgressTests(unittest.TestCase):
    def display(self, **kwargs):
        stream = Terminal()
        with redirect_stderr(stream), patch.dict(os.environ, {'TERM': 'xterm-256color'}):
            result = CommandProgress('sync', **kwargs)
        return result, stream

    def test_every_dispatched_command_has_an_explicit_activity(self):
        self.assertFalse(set(HANDLERS) - ACTIVITIES.keys())
        self.assertTrue({'init', 'sync', 'rebuild', 'status', 'validate'} <= ACTIVITIES.keys())

    def test_counts_are_exact_and_unknown_work_has_no_percentage(self):
        event = ProgressEvent(1, None, 'Checking packages', completed=2, total=3, unit='packages')
        self.assertEqual(metrics(event), ' 66.7%  2/3 packages')
        self.assertIn('99.9%', metrics(replace(event, completed=99999, total=100000)))
        self.assertIn('100.0%', metrics(replace(event, completed=3)))
        self.assertNotIn('%', metrics(replace(event, completed=0, total=0)))
        self.assertEqual(metrics(replace(event, completed=0, total=None)), '')
        events = []
        with reporting(events.append), task('Checked files', total=3) as activity:
            activity.advance()
            phase('Waiting for AI provider')
        waiting = next(e for e in events if e.label == 'Waiting for AI provider')
        self.assertEqual((waiting.completed, waiting.total), (0, None))

    def test_a_failed_item_never_advances_or_finishes_the_bar(self):
        events = []
        with reporting(events.append):
            iterator = track([1, 2, 3], 'Writing notes', unit='notes')
            self.assertEqual(next(iterator), 1)
            self.assertEqual(next(iterator), 2)
            with self.assertRaisesRegex(ValueError, 'disk full'):
                iterator.throw(ValueError('disk full'))
        counts = [e.completed for e in events]
        self.assertEqual(max(counts), 1)
        self.assertEqual(events[-1].state, 'failed')

    def test_nested_parallel_work_keeps_its_parent_and_cleans_up(self):
        display, _ = self.display(mode='plain')
        events = []
        barrier = threading.Barrier(2)
        lock = threading.Lock()

        def observe(event):
            with lock:
                events.append(event)
                display.on_event(event)

        def worker(name):
            with task(name):
                barrier.wait(timeout=5)
                phase('Waiting for AI provider', detail=name)

        with reporting(observe), task('Extracting AI proposals', total=2) as batch:
            parent = batch.event.task_id
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(copy_context().run, worker, name) for name in ('alpha.tex', 'beta.tex')]
                for future in futures:
                    future.result()
                    batch.advance()
        waits = [event for event in events if event.label == 'Waiting for AI provider' and event.state == 'running']
        self.assertEqual({event.parent_id for event in waits}, {parent})
        self.assertEqual({event.detail for event in waits}, {'alpha.tex', 'beta.tex'})
        self.assertEqual(display.tasks, {})
        self.assertEqual(display.logged, {})

    def test_responsive_frames_fit_terminal_cells_and_preserve_metrics(self):
        display, _ = self.display()
        display.tasks = {
            1: ProgressEvent(1, None, 'Checking source packages', 1, 3, 'packages'),
            2: ProgressEvent(2, 1, '论文_e\u0301_long_source_filename.tex'),
            3: ProgressEvent(3, 2, 'Waiting for AI provider', detail='attempt 1/3 | timeout 120s'),
        }
        for width in (1, 8, 20, 35, 45, 60, 80, 120):
            for height in (1, 3, 24):
                with self.subTest(width=width, height=height):
                    lines = display.render_lines(width, height)
                    self.assertLessEqual(len(lines), height)
                    for line in lines:
                        text = re.sub(r'\x1b\[[0-9;]*m', '', line)
                        self.assertLessEqual(cell_width(text), width, repr(text))
        frame = '\n'.join(display.render_lines(39))
        self.assertIn('33.3%', frame)
        self.assertIn('1/3 packages', frame)

    def test_progress_depends_on_stderr_tty_and_does_not_write_to_stdout(self):
        stdout = io.StringIO()
        display, stderr = self.display()
        with redirect_stdout(stdout):
            display.start()
            display.on_event(ProgressEvent(1, None, 'Reading source'))
            display.close()
        self.assertTrue(display.live)
        self.assertIn('QEC GRAPH', stderr.getvalue())
        self.assertEqual(stdout.getvalue(), '')
        self.assertFalse(display.worker.is_alive())

    def test_control_sequences_and_nonprinting_characters_cannot_escape_a_row(self):
        display, stream = self.display(mode='plain')
        display.on_event(ProgressEvent(1, None, 'paper\r\n\x1b[2Jbad\x1b]0;owned\x07\u202etex', retain=True))
        text = stream.getvalue()
        self.assertEqual(text.count('\n'), 1)
        self.assertNotIn('\x1b', text)
        self.assertNotIn('\u202e', text)
        self.assertNotIn('owned', text)
        self.assertEqual(clean('one\t two'), 'one two')

    def test_ascii_and_no_color_keep_distinct_text_states(self):
        class AsciiTerminal(Terminal):
            encoding = 'ascii'

        stream = AsciiTerminal()
        with redirect_stderr(stream), patch.dict(os.environ, {'TERM': 'xterm', 'NO_COLOR': '1'}):
            display = CommandProgress('sync')
            self.assertFalse(display.unicode)
            display.on_event(ProgressEvent(1, None, 'Reading a source', 1, 2, 'files'))
            display.finish('A package needs an entry point', 2)
        text = stream.getvalue()
        text.encode('ascii')
        self.assertIn('PARTIAL', text)
        self.assertIn('ERROR: A package needs an entry point', text)
        self.assertNotRegex(text, r'\x1b\[[0-9;]*m')

    def test_non_tty_auto_and_off_are_silent_and_plain_has_no_cursor_codes(self):
        for mode in ('auto', 'off', 'plain'):
            stream = io.StringIO()
            with redirect_stderr(stream):
                display = CommandProgress('sync', mode=mode)
                display.on_event(ProgressEvent(1, None, 'Checking archive'))
                display.finish()
            self.assertNotIn('\x1b', stream.getvalue())
            self.assertEqual(bool(stream.getvalue()), mode == 'plain')

    def test_long_error_preserves_the_actionable_tail(self):
        display, stream = self.display(mode='plain')
        message = 'A source file ' + 'a' * 200 + ' failed; use --entrypoint main.tex'
        display.finish(message, 1)
        self.assertIn('use --entrypoint main.tex', stream.getvalue())

    def test_plain_history_is_compact_and_verbose_can_show_transient_diagnostics(self):
        for verbose in (False, True):
            display, stream = self.display(mode='plain', verbose=verbose)
            with reporting(display.on_event), task('Extracting AI content', retain=True):
                phase('Checking source hashes')
                with task('Waiting to retry AI request', kind='ai'):
                    pass
            display.finish()
            self.assertIn('Extracting AI content [done]', stream.getvalue())
            self.assertEqual('Waiting to retry AI request' in stream.getvalue(), verbose)
            self.assertEqual('Checking source hashes' in stream.getvalue(), verbose)

    def test_shared_batch_counts_stay_monotonic_across_workers(self):
        events = []
        barrier = threading.Barrier(4)

        def advance(batch):
            barrier.wait(timeout=5)
            for _ in range(25):
                batch.advance()

        with reporting(events.append), task('AI extraction', total=100) as batch:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(copy_context().run, advance, batch) for _ in range(4)]
                for future in futures:
                    future.result()
        self.assertEqual([event.completed for event in events if event.state == 'running'], list(range(101)))

    def test_last_transient_task_disappears_without_leaving_an_active_panel(self):
        display, stream = self.display(color='never')
        with reporting(display.on_event), task('Checking response JSON'):
            self.assertIn('Checking response JSON', visible_terminal_text(stream.getvalue()))
        self.assertEqual(visible_terminal_text(stream.getvalue()).strip(), '')

    def test_failed_stage_keeps_count_and_reason_without_child_rows(self):
        display, stream = self.display(color='never')
        with reporting(display.on_event), task('Extracting AI content', total=4, unit='tasks', retain=True) as stage:
            with task('Waiting for AI provider', kind='ai') as request:
                request.outcome('failed')
            stage.advance(3)
            stage.outcome('partial', detail='Assumptions: request timed out')
        visible = visible_terminal_text(stream.getvalue())
        self.assertIn('needs attention', visible)
        self.assertIn('75.0%  3/4 tasks', visible)
        self.assertIn('Assumptions: request timed out', visible)
        self.assertNotIn('Waiting for provider', visible)

    def test_history_keeps_only_major_stages_after_redraw_output_and_close(self):
        display, stream = self.display(color='never')
        with reporting(display.on_event), task('Opening workspace'):
            with task('Extracting source structure', total=2, unit='files', retain=True) as activity:
                phase('Checking file hashes')
                self.assertIn('Checking file hashes', visible_terminal_text(stream.getvalue()))
                activity.advance(2)
            with task('Publishing workspace', retain=True):
                for index in range(30):
                    with task(f'Writing output {index}'):
                        self.assertIn(f'Writing output {index}', visible_terminal_text(stream.getvalue()))
            hide()
            stream.write('JSON report goes here\n')
            # Workspace commands finish their summary inside the root context.
            display.finish()
        display.close()
        visible = visible_terminal_text(stream.getvalue())
        for label in ('Extracting source structure', 'Publishing workspace', 'JSON report goes here'):
            self.assertEqual(visible.count(label), 1, visible)
        for detail in ('Opening workspace', 'Writing output', 'Checking file hashes', '⣿'):
            self.assertNotIn(detail, visible)
        self.assertIn('2/2 files', visible)
        self.assertIn('100.0%', visible)
        self.assertIn('sync: OK', visible)
        self.assertFalse(display.tasks)

    def test_interrupted_history_keeps_real_partial_count(self):
        display, stream = self.display(color='never')
        with self.assertRaises(KeyboardInterrupt), reporting(display.on_event), task(
                'Reading source files', total=3, unit='files', retain=True) as activity:
            activity.advance()
            raise KeyboardInterrupt
        display.close()
        visible = visible_terminal_text(stream.getvalue())
        self.assertIn('Reading source files | interrupted', visible)
        self.assertIn('1/3 files', visible)
        self.assertIn('33.3%', visible)
        self.assertNotIn('100.0%', visible)

    def test_ai_lamp_shows_only_running_steps_and_batch_reflects_partial_packages(self):
        display, _ = self.display(color='never')
        display.tasks = {1: ProgressEvent(1, None, 'Extracting AI content', 3, 8, 'AI tasks')}
        for base, name, done in ((2, 'alpha.tar', 2), (5, 'beta.tar', 1)):
            steps = tuple(ProgressStep(str(index), label,
                          'finished' if index < done else 'running' if index == done else 'queued')
                          for index, label in enumerate(('Theorems', 'Assumptions', 'Data', 'Research thoughts')))
            display.tasks[base] = ProgressEvent(base, 1, name, kind='package')
            display.tasks[base + 1] = ProgressEvent(base + 1, base, 'Extracting AI content', done, 4, 'tasks', steps=steps)
            display.tasks[base + 2] = ProgressEvent(base + 2, base + 1, 'Waiting for AI provider',
                                                  detail='attempt 1/3 | timeout 120s | provider / model', kind='ai')
        frame = '\n'.join(display.render_lines(79, 23, 9))
        for name in ('AI • Data · Waiting for provider', 'AI • Assumptions · Waiting for provider'):
            self.assertEqual(frame.count(name), 1)
        for name in ('Theorems', 'Research thoughts', 'done', 'queued'):
            self.assertNotIn(name, frame)
        self.assertIn('37.5%  3/8 AI tasks', frame)
        self.assertEqual(sum('⣿⣿⣿' in row for row in frame.splitlines()), 1)
        self.assertNotIn('more activity', frame)
        self.assertIn('AI • Data · Waiting for provider', '\n'.join(display.render_lines(79, 23, 0)))
        for width in (12, 20, 35, 45, 60, 79, 120):
            for height in (1, 3, 12, 24):
                for line in display.render_lines(width, height, 90):
                    self.assertLessEqual(cell_width(line), width, repr(line))
        display.tasks = {1: ProgressEvent(1, None, 'Waiting for AI provider', kind='ai')}
        waiting = '\n'.join(display.render_lines(79, 23, 9))
        self.assertIn('AI • Waiting for provider', waiting)
        self.assertNotIn('%', waiting)
        self.assertNotIn('⣿', waiting)

    def test_breathing_changes_only_color_and_compact_matrix_keeps_exact_counts(self):
        display, _ = self.display(color='always')
        lamps = [display._lamp(frame) for frame in range(24)]
        self.assertGreater(len(set(lamps)), 5)
        self.assertEqual({re.sub(r'\x1b\[[0-9;]*m', '', lamp) for lamp in lamps}, {'•'})
        event = ProgressEvent(1, None, 'Checking packages', 2, 3, 'packages')
        frames = [display._meter(event, 76, frame) for frame in (0, 12, 24)]
        self.assertTrue(all(len(frame) == 1 for frame in frames))
        plain = [re.sub(r'\x1b\[[0-9;]*m', '', frame[0]) for frame in frames]
        self.assertEqual(len(set(plain)), 1)  # Shimmer must not imply unmeasured progress.
        self.assertIn('66.7%  2/3 packages', plain[0])
        self.assertLessEqual(len(plain[0].split('  ')[0]), 12)
