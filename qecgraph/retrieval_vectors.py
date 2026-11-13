"""Immutable float32 vectors addressed by their exact stored bytes."""
from __future__ import annotations

import hashlib
import math
import re
import struct
from collections.abc import Iterable

from .core.fs import managed_path
from .core.transactions import atomic_bytes

_SPARSE_VALUE = struct.Struct('<Hf')


def vector_path(machine, digest):
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Invalid retrieval vector binding')
    return managed_path(machine, f'retrieval/vectors/{digest[:2]}/{digest[2:]}.bin')


def write_vector(machine, vector, dimensions, *, repair=False):
    if len(vector) * _SPARSE_VALUE.size < dimensions * 4:
        raw = b'S' + b''.join(_SPARSE_VALUE.pack(int(i), x) for i, x in sorted(vector.items()))
    else:
        raw = b'D' + struct.pack(f'<{dimensions}f', *(vector.get(str(i), 0) for i in range(dimensions)))
    digest = hashlib.sha256(raw).hexdigest()
    path = vector_path(machine, digest)
    if repair or not path.exists():
        atomic_bytes(path, raw)
    elif path.read_bytes() != raw:
        raise ValueError('Immutable retrieval vector differs from its binding')
    return digest


def read_vector(machine, digest, dimensions):
    path = vector_path(machine, digest)
    with path.open('rb') as handle:
        raw = handle.read(dimensions * _SPARSE_VALUE.size + 2)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Retrieval vector hash mismatch')
    header, data = raw[:1], raw[1:]
    pairs: Iterable[tuple[int, float]]
    if header == b'D' and len(data) == dimensions * 4:
        pairs = enumerate(struct.unpack(f'<{dimensions}f', data))
    elif header == b'S' and len(data) % _SPARSE_VALUE.size == 0:
        pairs = _SPARSE_VALUE.iter_unpack(data)
    else:
        raise ValueError('Invalid retrieval vector encoding')
    result = {}
    for index, value in pairs:
        key = str(index)
        if index >= dimensions or key in result or not math.isfinite(value):
            raise ValueError('Invalid retrieval vector dimension or value')
        result[key] = value
    return result
