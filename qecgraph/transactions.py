"""Single-writer filesystem transactions for authoritative JSON pointers.

Immutable objects may be left unreferenced after a crash. Only replacing the
pointer publishes a state; readers never observe half of a transaction.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


class ManagedDataError(ValueError):
    def __init__(self, path, message):
        self.path = Path(path)
        super().__init__(f'{message}: {self.path}')


class WriterBusy(ValueError):
    def __init__(self, root):
        self.root = Path(root)
        super().__init__(f'Another writer holds {self.root}')


def read_pointer(path, expected_format):
    """Read one authoritative pointer and reject corrupt JSON or format."""
    from .graph import read_json

    try:
        pointer = read_json(path)
    except ValueError as exc:
        raise ManagedDataError(path, 'CURRENT contains invalid JSON') from exc
    if not isinstance(pointer, dict) or pointer.get('format') != expected_format:
        raise ManagedDataError(path, 'CURRENT has an invalid pointer format')
    return pointer


@contextmanager
def writer_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / '.writer.lock'
    if lock_path.is_symlink():
        raise ValueError('Writer lock must be a regular local file')
    with lock_path.open('a+b') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WriterBusy(root) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def immutable_json(path, value):
    path = Path(path)
    if path.exists():
        from .graph import read_json
        if read_json(path) != value:
            raise ValueError(f'Immutable object conflict: {path}')
        return
    atomic_json(path, value)


def atomic_bytes(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
