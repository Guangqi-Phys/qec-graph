"""Optional, context-local activity events. Never write to a terminal here.

Counts describe completed work in one named phase, never estimated wall time.
Thread-pool callers must copy the context for each submitted job.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from itertools import count

@dataclass(frozen=True)
class ProgressStep:
    key: str
    label: str
    state: str = 'queued'
    detail: str = ''


@dataclass(frozen=True)
class ProgressEvent:
    task_id: int
    parent_id: int | None
    label: str
    completed: int = 0
    total: int | None = None
    unit: str = 'items'
    detail: str = ''
    state: str = 'running'
    kind: str = 'task'
    steps: tuple[ProgressStep, ...] = ()


_sink: ContextVar[Callable[[ProgressEvent], None] | None] = ContextVar('progress_sink', default=None)
_current: ContextVar[Activity | None] = ContextVar('progress_activity', default=None)
_ids = count(1)


def _emit(event: ProgressEvent) -> None:
    if sink := _sink.get():
        sink(event)


class Activity:
    event: ProgressEvent

    def __init__(self, label: str, *, total: int | None = None, unit='items', detail='', kind='task', steps=()):
        parent = _current.get()
        self.event = ProgressEvent(next(_ids), parent.event.task_id if parent else None,
                                   label, total=total, unit=unit, detail=detail, kind=kind, steps=tuple(steps))
        self.final_state = 'finished'

    def advance(self, amount: int = 1) -> None:
        self.event = replace(self.event, completed=self.event.completed + amount)
        _emit(self.event)

    def phase(self, label: str, *, detail: str = '') -> None:
        self.event = replace(self.event, label=label, detail=detail, completed=0, total=None)
        _emit(self.event)

    def step(self, key: str, state: str, *, detail: str = '') -> None:
        self.event = replace(self.event, steps=tuple(
            replace(step, state=state, detail=detail) if step.key == key else step for step in self.event.steps))
        _emit(self.event)

    def outcome(self, state: str, *, detail: str | None = None) -> None:
        """Record a caught failure or a reused result without inventing completed units."""
        self.final_state = state
        if detail is not None:
            self.event = replace(self.event, detail=detail)


@contextmanager
def reporting(sink: Callable[[ProgressEvent], None] | None) -> Iterator[None]:
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def task(label: str, *, total: int | None = None, unit='items', detail='', kind='task', steps=()) -> Iterator[Activity]:
    activity = Activity(label, total=total, unit=unit, detail=detail, kind=kind, steps=steps)
    token = _current.set(activity)
    _emit(activity.event)
    try:
        yield activity
    except BaseException as exc:
        _emit(replace(activity.event, state='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed'))
        raise
    else:
        # Finishing a task does not invent completed units.
        _emit(replace(activity.event, state=activity.final_state))
    finally:
        _current.reset(token)


def phase(label: str, *, detail: str = '') -> None:
    if current := _current.get():
        current.phase(label, detail=detail)


def outcome(state: str, *, detail: str | None = None) -> None:
    if current := _current.get():
        current.outcome(state, detail=detail)


def track(items, label: str, *, unit='items', detail: Callable | None = None) -> Iterator:
    """Count only items whose loop body returned successfully; do not pre-consume iterators."""
    if _sink.get() is None:
        yield from items
        return
    total = len(items) if hasattr(items, '__len__') else None
    with task(label, total=total, unit=unit) as batch:
        for item in items:
            if detail:
                with task(detail(item)):
                    yield item
            else:
                yield item
            batch.advance()


def hide() -> None:
    """Clear the live region before a CLI report or protocol frame is written."""
    _emit(ProgressEvent(0, None, '', state='output'))
