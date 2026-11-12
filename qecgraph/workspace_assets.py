"""Explicit managed assets; no query path can point into the human vault."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

from .domain.research import ASSET_FIELDS as FIELDS, ASSET_URI_PATTERN
from .core.transactions import writer_lock
from .workspace import Workspace
from .core.fs import hash_regular as _hash_regular, managed_path as _managed, read_regular as _read_regular

ASSET_URI = re.compile(ASSET_URI_PATTERN)
MAX_ASSET_BYTES = 16 << 20


def references(record):
    data = record['data']
    for field, multiple in FIELDS.get(record['kind'], {}).items():
        value = data.get(field)
        if value is None:
            continue
        if multiple and not isinstance(value, list):
            raise ValueError(f'{field} needs a list of registered asset IDs or null')
        for binding in value if multiple else [value]:
            if not isinstance(binding, str) or not ASSET_URI.fullmatch(binding):
                raise ValueError(f'{field} needs a managed qecasset:sha256 ID, never a filesystem path')
            yield binding


def add_asset(workspace, source, *, media_type='application/octet-stream'):
    ws = Workspace(workspace)
    ws.config()
    path = Path(source).expanduser().absolute()
    vault = ws.root / 'human'
    if path.is_symlink() or path.is_relative_to(vault) or path.resolve().is_relative_to(vault.resolve()):
        raise ValueError('Human vault and linked files cannot be machine asset inputs')
    if not isinstance(media_type, str) or not re.fullmatch(r'[\w.+-]+/[\w.+-]+', media_type, flags=re.ASCII):
        raise ValueError('Invalid asset media type')
    raw = _read_regular(path, MAX_ASSET_BYTES)
    with writer_lock(ws.registry.root):
        return ws.registry._put_asset(raw, media_type)


def _asset_binding(registry, uri):
    match = ASSET_URI.fullmatch(uri)
    if not match:
        raise ValueError('Invalid managed asset ID')
    digest = match[1]
    return _managed(registry.root, 'assets/' + digest), digest


def verify_asset(registry, uri):
    path, digest = _asset_binding(registry, uri)
    if _hash_regular(path, MAX_ASSET_BYTES) != digest:
        raise ValueError('Managed asset content changed')


def asset_bytes(registry, uri):
    path, digest = _asset_binding(registry, uri)
    raw = _read_regular(path, MAX_ASSET_BYTES)
    if sha256(raw).hexdigest() != digest:
        raise ValueError('Managed asset content changed')
    return raw
