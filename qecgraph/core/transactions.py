"""Single-writer filesystem transactions for authoritative JSON pointers.

Immutable objects may be left unreferenced after a crash. Only replacing the
pointer publishes a state; readers never observe half of a transaction.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
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


def _check_lock_file(path, metadata):
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ManagedDataError(path, 'Writer lock must be a regular local file with one link')


@contextmanager
def writer_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / '.writer.lock'
    try:
        _check_lock_file(lock_path, lock_path.lstat())
    except FileNotFoundError:
        pass
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o666)
    try:
        _check_lock_file(lock_path, os.fstat(fd))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WriterBusy(root) from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def _atomic_writer(path, *, text=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        stream = os.fdopen(descriptor, 'w', encoding='utf-8') if text else os.fdopen(descriptor, 'wb')
        with stream as handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path, value):
    with _atomic_writer(path, text=True) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


def publish_pointer(path, pointer_format, /, **binding):
    """Make an already prepared publication visible by replacing CURRENT."""
    atomic_json(path, {'format': pointer_format, **binding})


def immutable_json(path, value):
    path = Path(path)
    if path.exists():
        from .graph import read_json
        if read_json(path) != value:
            raise ValueError(f'Immutable object conflict: {path}')
        return
    atomic_json(path, value)


def atomic_bytes(path, raw):
    with _atomic_writer(path) as handle:
        handle.write(raw)
