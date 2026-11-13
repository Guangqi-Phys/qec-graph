"""Managed paths and bounded regular-file reads shared by workspace consumers."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat

from .errors import PackageError
from .graph import strict_json_loads
from .progress import task

SHA256_HEX = re.compile(r'[0-9a-f]{64}')
_CHUNK_BYTES = 256 << 10


def check_machine_tree(machine):
    """Refuse linked files before any registry reader dereferences a path."""
    machine = Path(machine)
    if machine.is_symlink() or not machine.is_dir():
        raise ValueError('A real machine directory is required')
    pending = [machine]
    while pending:
        with os.scandir(pending.pop()) as children:
            for entry in children:
                mode = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(mode.st_mode):
                    # Atomic register uses an unpublished private directory.
                    if not entry.name.startswith('.register-'):
                        pending.append(entry.path)
                elif not stat.S_ISREG(mode.st_mode) or mode.st_nlink != 1:
                    raise ValueError('Linked or special machine content is not readable by this service')


def managed_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Invalid managed path')
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'Symlink is not allowed in managed path: {relative}')
    return current


@contextmanager
def _regular_input(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('Expected a regular unlinked source file')
        if before.st_size > limit:
            raise PackageError('limit_exceeded', 'Source byte limit exceeded')
        yield stream, before


def _check_input_read(stream, before, size):
    after = os.fstat(stream.fileno())
    if (before.st_size != size or after.st_size != size or after.st_nlink != 1
            or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError('Input changed while reading; retry after writing finishes')


def read_regular(path, limit):
    with _regular_input(path, limit) as (stream, before):
        raw = stream.read(before.st_size + 1)
        _check_input_read(stream, before, len(raw))
    return raw


def read_operational_status(path):
    """Load a previous progress report when its bytes can be trusted and parsed."""
    try:
        raw = read_regular(path, 1 << 20)
    except FileNotFoundError:
        return {}
    try:
        data = strict_json_loads(raw.decode('utf-8'), source=str(path))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def hash_regular(path, limit, *, copy_to=None):
    digest = hashlib.sha256()
    size = 0
    with _regular_input(path, limit) as (stream, before):
        with task("Hashing source bytes", total=before.st_size, unit="bytes") as hashed:
            while chunk := stream.read(min(_CHUNK_BYTES, limit - size + 1)):
                size += len(chunk)
                if size > limit:
                    raise PackageError('limit_exceeded', 'Source byte limit exceeded')
                digest.update(chunk)
                if copy_to is not None:
                    copy_to.write(chunk)
                hashed.advance(len(chunk))
            _check_input_read(stream, before, size)
    return digest.hexdigest()


def matches_regular(path, limit, expected):
    with _regular_input(path, limit) as (stream, before):
        if before.st_size != len(expected):
            return False
        size = 0
        while chunk := stream.read(min(_CHUNK_BYTES, before.st_size - size + 1)):
            end = size + len(chunk)
            if chunk != expected[size:end]:
                return False
            size = end
        _check_input_read(stream, before, size)
    return True

