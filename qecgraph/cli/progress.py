"""Persistent phase history and a live dot-matrix display, exclusively on stderr."""
from __future__ import annotations

from dataclasses import replace
import math
import os
import re
import sys
from threading import Event, RLock, Thread
from time import monotonic
import unicodedata

from ..core.progress import ProgressEvent


# Explicit descriptions cover the entire dispatch table, including aliases.
ACTIVITIES = {
    'init': 'Preparing workspace configuration', 'sync': 'Opening workspace',
    'rebuild': 'Opening archive for rebuild', 'status': 'Reading workspace status',
    'validate': 'Checking source and release integrity', 'doctor': 'Checking workspace health',
    'snapshot': 'Listing stored snapshots', 'inputs': 'Inspecting inbox packages',
    'human-build': 'Opening the published release', 'asset-add': 'Verifying and registering asset',
    'workspace-migrate': 'Migrating corpus into workspace',
    'extract-request': 'Preparing source evidence', 'extract-submit': 'Validating extraction response',
    'extract-review': 'Recording extraction review', 'research-import': 'Validating research records',
    'review-list': 'Reading the review queue', 'review-show': 'Loading proposal and review bindings',
    'review': 'Preparing a review proposal', 'review-decide': 'Validating review decision',
    'apply': 'Checking review bindings before publication',
    'software-import-seed': 'Importing the software catalog', 'software-coverage': 'Checking software coverage',
    'software-refresh': 'Refreshing software metadata',
    'search': 'Searching the pinned source and record index', 'show': 'Resolving the requested entity',
    'deps': 'Tracing eligible dependencies', 'impact': 'Tracing dependent entities',
    'context': 'Collecting bounded source context', 'audit-dependencies': 'Auditing reviewed dependency cycles',
    'mcp-config': 'Preparing a pinned MCP configuration', 'serve-mcp': 'Opening read-only MCP session',
    'query-tool': 'Running the requested read-only tool',
    'lean-build': 'Running Lean build and evidence audit', 'lean-import': 'Validating Lean evidence',
    'lean-status': 'Reading Lean evidence status', 'watch': 'Checking source changes',
    'recover-store': 'Checking store recovery state', 'validate-staged': 'Verifying staged snapshot',
    'ingest': 'Opening LaTeX source', 'split': 'Opening LaTeX source',
    'check-css': 'Checking CSS matrices and distance constraints',
    'check-experiment': 'Checking experiment and metric consistency',
    'codes': 'Filtering registered codes', 'query-performance': 'Filtering performance records',
    'query-software': 'Searching software records', 'validate-corpus': 'Checking corpus integrity',
    'record-add': 'Validating and registering record', 'claim-link': 'Validating claim and source bindings',
    'register': 'Verifying and registering source snapshot',
    'ai-test': 'Checking AI provider connectivity', 'ai-status': 'Reading AI provider status',
    'ai-config': 'Reading redacted AI configuration', 'ai-proposals': 'Loading published AI proposals',
    'ai-decide': 'Checking AI proposal review bindings', 'ai-decisions': 'Loading AI review decisions',
}

_ESCAPES = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]')


def clean(text):
    return ' '.join(''.join(c if c.isprintable() else ' ' for c in _ESCAPES.sub('', str(text))).split())


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def fit(text, width, ellipsis='…'):
    if cell_width(text) <= width:
        return text
    if width < len(ellipsis):
        return '.' * max(0, width)
    result = ''
    for char in text:
        if cell_width(result + char) > width - len(ellipsis):
            break
        result += char
    return result + ellipsis


def wrap(text, width):
    """Wrap retained records without dropping filenames, counts or error tails."""
    rows, row = [], ''
    for char in text:
        if row and cell_width(row + char) > width:
            rows.append(row)
            row = ''
        row += char
    return [*rows, row] if row else rows


def duration(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


def metrics(event):
    if event.total is None:
        return f'{event.completed:,} {event.unit} completed' if event.completed else ''
    if event.total == 0:
        return f'0 {event.unit}'
    percent = 100.0 if event.completed >= event.total else min(99.9, event.completed * 100 / event.total)
    return f'{percent:5.1f}%  {event.completed:,}/{event.total:,} {event.unit}'


class CommandProgress:
    def __init__(self, action, *, quiet=False, color='auto', mode='auto', verbose=False, animate=True):
        self.action = action
        self.quiet = quiet
        self.verbose = verbose
        self.stderr = sys.stderr
        terminal = self.stderr.isatty() and os.environ.get('TERM') != 'dumb'
        self.enabled = not quiet and mode != 'off' and (terminal or mode == 'plain' or verbose)
        self.live = self.enabled and terminal and mode != 'plain' and not verbose and animate
        forced = os.environ.get('FORCE_COLOR')
        self.color = (color == 'always' or color == 'auto' and not os.environ.get('NO_COLOR')
                      and (forced != '0' if forced is not None else terminal))
        if mode == 'plain':
            self.color = False
        self.color_mode = color
        self.unicode = True
        try:
            '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏╭╰│─✓✗…⣿•·→↺'.encode(self.stderr.encoding or 'ascii')
        except (UnicodeEncodeError, LookupError):
            self.unicode = False
        self.started = None
        self.stopped = Event()
        self.worker = None
        self.lock = RLock()
        self.tasks: dict[int, ProgressEvent] = {}
        self.phase_started: dict[int, float] = {}
        self.logged: dict[int, tuple[str, float, int]] = {}
        self.last = None
        self.lines = 0
        self.line_widths: list[int] = []
        self.hidden = False
        self.closed = False
        self.frame = 0

    def _text(self, text):
        value = clean(text)
        return value.encode(self.stderr.encoding or 'ascii', errors='replace').decode(self.stderr.encoding or 'ascii')

    def _paint(self, text, style):
        return f'\x1b[{style}m{text}\x1b[0m' if self.color else text

    def start(self):
        self.started = monotonic()
        if self.live:
            self.worker = Thread(target=self._animate, name='qecgraph-progress', daemon=True)
            self.worker.start()

    def _animate(self):
        while not self.stopped.wait(0.1):
            with self.lock:
                self._draw(self.frame)
                self.frame += 1

    def on_event(self, event):
        if not self.enabled or self.closed:
            return
        with self.lock:
            if event.state == 'output':
                self.hidden = True
                self._clear()
                return
            old = self.tasks.get(event.task_id)
            event = replace(event, label=self._text(event.label), detail=self._text(event.detail), unit=self._text(event.unit),
                            steps=tuple(replace(step, label=self._text(step.label), detail=self._text(step.detail))
                                        for step in event.steps))
            changed = old is not None and (old.label, old.detail) != (event.label, event.detail)
            if self.live and event.retain and event.state != 'running':
                self._commit(event)
            if event.state == 'running':
                self.tasks[event.task_id] = event
                if old is None or changed and not event.retain:
                    self.phase_started[event.task_id] = monotonic()
                self.hidden = False
                self.last = event
            else:
                self.tasks.pop(event.task_id, None)
                self.phase_started.pop(event.task_id, None)
            if not self.live:
                self._log(event)
            elif not self.hidden and self.tasks:
                self._draw(self.frame)
            elif not self.tasks and self.lines:
                self._clear()
                self._write('\n')

    def _log(self, event):
        if not event.retain and not self.verbose:
            return
        stamp = monotonic()
        detail = event.detail if self.verbose or event.state != 'running' else ''
        steps = '; '.join(f'{step.label}: {self._state(step.state)}' for step in event.steps) if self.verbose else ''
        signature = event.label + detail + steps
        previous = self.logged.get(event.task_id)
        if event.state != 'running':
            self.logged.pop(event.task_id, None)
        # Bounded logs for large loops; phase transitions and final counts survive.
        if event.state == 'running' and previous and previous[0] == signature:
            if previous[2] == event.completed or (stamp - previous[1] < 1 and event.completed != event.total):
                return
        if event.state == 'running':
            self.logged[event.task_id] = signature, stamp, event.completed
        extra = ' | '.join(filter(None, (metrics(event), detail, steps)))
        label = ('AI: ' if event.kind == 'ai' else '') + event.label
        scope = self._scope(event)
        label = f'{scope} / {label}' if scope else label
        self._write(f'qec-graph {self.action}: {label} [{self._state(event.state)}]' + (f' | {extra}' if extra else '')
                    + f' | elapsed {duration(stamp - (self.started or stamp))}\n')

    def _size(self):
        try:
            size = os.get_terminal_size(self.stderr.fileno())
            return max(1, size.columns - 1), max(1, size.lines - 1)
        except (OSError, ValueError, AttributeError):
            return 79, 23

    def _state(self, state):
        return {'finished': 'done', 'advanced': 'phase ended', 'partial': 'needs attention',
                'reused': 'reused', 'running': 'running', 'queued': 'queued',
                'failed': 'failed', 'interrupted': 'interrupted'}.get(state, state)

    def _marker(self, state):
        glyph = {'finished': '✓', 'reused': '↺', 'failed': '✗', 'interrupted': '!',
                 'partial': '!', 'advanced': '→', 'running': '›', 'queued': '·'}.get(state, '·')
        if not self.unicode:
            glyph = {'finished': '+', 'reused': '=', 'failed': 'x', 'advanced': '>',
                     'running': '>', 'queued': '.'}.get(state, '!')
        style = {'finished': '32', 'reused': '2', 'failed': '31', 'interrupted': '33',
                 'partial': '33', 'running': '33'}.get(state, '2')
        return self._paint(glyph, style)

    def _amber(self, text, light=1.0):
        # CodeGraph's amber palette is a visual reference; provenance is in DESIGN.md.
        light = min(1.0, max(0.0, light))
        red, green, blue = (round(low + (high - low) * light)
                            for low, high in ((160, 251), (100, 191), (9, 36)))
        return self._paint(text, f'38;2;{red};{green};{blue}')

    def _lamp(self, frame):
        # A single baseline-aligned bullet: only luminance changes, never size or position.
        light = (1 - math.cos(frame * math.tau / 24)) / 2
        return self._amber('•' if self.unicode else '*', light)

    def _meter(self, event, width, frame=0, elapsed=''):
        """Four microscopic dot rows in one text row; luminance never changes the count."""
        if not event.total:
            return [fit(metrics(event), width)] if metrics(event) else []
        count = metrics(event).strip()
        beside = width >= cell_width(count) + 8
        columns = min(12, max(4, width - cell_width(count) - 2) if beside else width)
        filled = min(columns * 8, max(0, int(columns * 8 * event.completed / event.total)))
        cells = []
        # Braille's left column is bits 0,1,2,6; the right is bits 3,4,5,7.
        bits = (0, 1, 2, 6, 3, 4, 5, 7)
        sweep = (frame % 36) * (columns + 4) / 36 - 2
        for column in range(columns):
            dots = min(8, max(0, filled - column * 8))
            if dots:
                glyph = chr(0x2800 + sum(1 << bit for bit in bits[:dots])) if self.unicode else ':'
                light = 0.35 + 0.65 * max(0, 1 - abs(column - sweep) / 2) if event.state == 'running' else 0.8
                cells.append(self._amber(glyph, light))
            else:
                cells.append(self._paint('⣿' if self.unicode else '.', '2;37'))
        matrix = ''.join(cells)
        if beside:
            return [f'{matrix}  {count}']
        return [fit(count, width, '…' if self.unicode else '...'), matrix]

    def _ancestor(self, event, task_id):
        parent = self.tasks.get(event.parent_id)
        while parent:
            if parent.task_id == task_id:
                return True
            parent = self.tasks.get(parent.parent_id)
        return False

    def _scope(self, event):
        parent = self.tasks.get(event.parent_id)
        while parent:
            if parent.kind == 'package':
                return parent.label
            parent = self.tasks.get(parent.parent_id)
        return ''

    def _commit(self, event):
        """Retain one compact major-stage result, without its transient children."""
        self._clear()
        width, _ = self._size()
        elapsed = duration(monotonic() - self.phase_started.get(event.task_id, monotonic()))
        scope = self._scope(event)
        label = ('AI / ' if event.kind == 'ai' else '') + event.label
        if scope:
            label = scope + ' / ' + label
        text = ' | '.join(filter(None, (label, self._state(event.state), metrics(event), elapsed)))
        rows = wrap(text, max(1, width - 4))
        lines = [f'  {self._marker(event.state)} {rows[0]}', *('    ' + row for row in rows[1:])]
        lines.extend('    ' + row for row in wrap(event.detail, max(1, width - 4)))
        self._write('\n'.join(lines) + '\n')

    def render_lines(self, width, height=23, frame=0):
        """Render a bounded frame; also used by terminal regression tests and previews."""
        if not self.tasks:
            return []
        ellipsis = '…' if self.unicode else '...'
        edge = '│' if self.unicode else '|'
        spinner = ('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' if self.unicode else '|/-\\')[frame % (10 if self.unicode else 4)]
        available = max(1, width - 3)
        events = list(self.tasks.values())
        now = monotonic()
        parents = {event.parent_id for event in events}
        leaves = [event for event in events if event.task_id not in parents]
        counted = next((event for event in events if event.total is not None), None)
        primary = counted or leaves[0]
        if width < 12:
            return [fit(primary.label, width, ellipsis)]
        heading = f'QEC GRAPH / {self.action}' if width >= 45 else self.action
        heading = ('╭─ ' if self.unicode else '+- ') + heading
        if width >= 60:
            heading = fit(heading, width - 10, ellipsis)
            heading += ' ' * (width - cell_width(heading) - 7) + 'RUNNING'
        lines = [self._paint(fit(heading, width, ellipsis), '1')]

        def action_rows(event, step_label=''):
            ai = event.kind == 'ai'
            prefix = f'AI {self._lamp(frame)} ' if ai else ''
            label = event.label.replace('AI ', '') if ai else event.label
            if step_label and step_label != label:
                label = f'{step_label} · {label}' if self.unicode else f'{step_label} / {label}'
            space = available - (5 if ai else 0)
            elapsed = duration(now - self.phase_started.get(event.task_id, now))
            if space >= 40:
                label = fit(label, space - len(elapsed) - 2, ellipsis)
                label += ' ' * (space - cell_width(label) - len(elapsed)) + elapsed
            lines.append(f'{edge}  {prefix}{fit(label, space, ellipsis)}')
            if event.detail:
                lines.extend(f'{edge}    {row}' for row in wrap(event.detail, max(1, available - 2)))

        if primary.kind == 'ai':
            action_rows(primary)
        else:
            label = fit(primary.label, max(0, available - 2), ellipsis)
            lines.append(f'{edge} {self._amber(spinner)} {self._paint(label, "1")}')
            lines.extend(f'{edge}  {row}' for row in self._meter(
                primary, available, frame, duration(now - self.phase_started.get(primary.task_id, now))))
            if primary.detail:
                lines.append(f'{edge}  {fit(primary.detail, available, ellipsis)}')

        plans = [event for event in events if event.steps]
        for plan in plans:
            context = self._scope(plan) or plan.label
            count = f'{plan.completed}/{plan.total} tasks'
            if available < len(count) + 5:
                lines.append(f'{edge}  {fit(count, available, ellipsis)}')
            else:
                context = fit(context, available - len(count) - 2, ellipsis)
                lines.append(f'{edge}  {self._paint(context, "1")}  {count}')
            running = next((step.label for step in plan.steps if step.state == 'running'), '')
            active = [leaf for leaf in leaves if self._ancestor(leaf, plan.task_id)]
            for leaf in active:
                action_rows(leaf, running)
            if running and not active:
                lines.append(f'{edge}  {fit(running, available, ellipsis)}')
        for leaf in leaves:
            if leaf.task_id == primary.task_id or leaf.steps or any(self._ancestor(leaf, plan.task_id) for plan in plans):
                continue
            path = []
            subtotal = ''
            parent = self.tasks.get(leaf.parent_id)
            while parent and parent.task_id != primary.task_id and parent.parent_id is not None:
                if parent.total is not None and not subtotal:
                    subtotal = f'{parent.completed}/{parent.total} {parent.unit}'
                elif parent.total is None:
                    path.insert(0, parent.label)
                parent = self.tasks.get(parent.parent_id)
            # Give concurrent packages a stable name; put the changing action
            # first on its own row so long paths cannot hide a wait or retry.
            context = ' / '.join(dict.fromkeys([*path[:1], *path[-1:]]))
            if subtotal:
                context += (' | ' if context else '') + subtotal
            if context:
                lines.append(f'{edge}  {self._paint(fit(context, available, ellipsis), "2")}')
            action_rows(leaf)
            lines.extend(f'{edge}  {row}' for row in self._meter(leaf, available, frame))
        elapsed = duration(now - (self.started or now))
        phase_time = duration(now - self.phase_started.get(primary.task_id, now))
        footer = f'elapsed {elapsed} | phase {phase_time}' if width >= 45 else f'elapsed {elapsed}'
        footer = fit(('╰─ ' if self.unicode else '+- ') + footer, width, ellipsis)
        max_body = max(1, height - 1)
        if len(lines) > max_body:
            omitted = len(lines) - max_body + 1
            # Cycle overflow at a readable pace; only major results enter history.
            room = max(1, max_body - 2)
            start = ((frame // 40) * room) % (len(lines) - 1)
            body = lines[1:]
            selected = (body + body)[start:start + room]
            lines = [lines[0], *selected, fit(f'{edge}  +{omitted} rows | cycling active work', width, ellipsis)]
        if height > 1:
            lines.append(self._paint(footer, '2'))
        return lines[:height]

    def _write(self, text):
        try:
            self.stderr.write(text)
            self.stderr.flush()
        except (OSError, ValueError):
            # A closed terminal must not abort a publication or background job.
            self.stopped.set()
            self.enabled = self.live = False

    def _clear(self):
        if self.lines:
            columns = self._size()[0] + 1
            rows = sum(max(1, (width + columns - 1) // columns) for width in self.line_widths)
            self._write('\r' + (f'\x1b[{rows - 1}A' if rows > 1 else '') + '\x1b[J')
            self.lines = 0
            self.line_widths = []

    def _draw(self, frame):
        if not self.live or self.hidden or not self.tasks:
            return
        width, height = self._size()
        lines = self.render_lines(width, height, frame)
        self._clear()
        self._write('\n'.join(lines))
        self.lines = len(lines)
        self.line_widths = [cell_width(_ESCAPES.sub('', line)) for line in lines]

    def close(self, state='interrupted'):
        self.stopped.set()
        if self.worker and self.worker.is_alive():
            self.worker.join()
        with self.lock:
            if self.closed:
                return
            if self.live:
                for event in reversed(list(self.tasks.values())):
                    if event.retain:
                        self._commit(replace(event, state=state, detail=''))
                self._clear()
            else:
                for event in reversed(list(self.tasks.values())):
                    self._log(replace(event, state=state, detail='' if event.retain else event.detail))
            self.tasks.clear()
            self.phase_started.clear()
            self.closed = True

    def finish(self, message='', code=0, *, summary=False):
        self.close('interrupted' if code == 130 else 'partial' if code == 2 else 'failed' if code else 'finished')
        if summary and self.quiet and not code or not summary and not self.enabled:
            return code
        label = 'INTERRUPTED' if code == 130 else 'PARTIAL' if code == 2 else 'ERROR' if code else 'OK'
        marker = ('!' if code == 2 else '✗' if code else '✓') if self.unicode else ('!' if code else '+')
        style = '33' if code in (2, 130) else '31' if code else '32'
        target = sys.stdout if summary and not code else self.stderr
        colored = target is self.stderr or target.isatty() or self.color_mode == 'always'
        badge = self._paint(marker, style) if colored else marker
        elapsed = duration(monotonic() - self.started) if self.started is not None else '00:00'
        outcome = f'{badge} {self.action}: {label}  {elapsed}'
        if message:
            outcome += ' | ' + ('ERROR: ' if code == 2 else '') + self._text(message)
        print(outcome, file=target, flush=True)
        return code


# Keep the import used by older CLI integrations available.
WorkspaceProgress = CommandProgress
