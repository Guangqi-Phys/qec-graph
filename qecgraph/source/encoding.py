"""Strict UTF-8 projections for explicitly declared single-byte TeX encodings."""
from __future__ import annotations

from hashlib import sha256
import re

from ..core.errors import PackageError

_CODECS = {
    'utf8': 'utf-8', 'utf-8': 'utf-8',
    'latin1': 'iso-8859-1', 'iso-8859-1': 'iso-8859-1',
    'latin9': 'iso-8859-15', 'iso-8859-15': 'iso-8859-15',
    'ansinew': 'cp1252', 'cp1252': 'cp1252', 'windows-1252': 'cp1252',
}
_DECLARATION = re.compile(
    rb'^[ \t]*%[ \t]*![ \t]*TeX[ \t]+encoding[ \t]*=[ \t]*([\w-]+)|'
    rb'^[ \t]*\\usepackage\[([\w-]+)\]\{inputenc\}', re.I | re.M,
)


def declared_encoding(raw: bytes) -> str | None:
    matches = {next(group for group in match.groups() if group).decode('ascii').lower()
               for match in _DECLARATION.finditer(raw[:8192])}
    codecs = {_CODECS.get(name, name) for name in matches}
    if len(codecs) > 1:
        raise PackageError('unsupported_encoding', 'Conflicting TeX encoding declarations')
    return next(iter(codecs), None)


def supported_encoding(name: str) -> bool:
    return name.lower() in _CODECS


def project_encoding(raw: bytes, explicit: str | None = None) -> tuple[bytes, dict[str, str] | None]:
    encoding = explicit or declared_encoding(raw)
    codec = _CODECS.get(encoding.lower()) if encoding else 'utf-8'
    if codec is None:
        raise PackageError('unsupported_encoding', 'Unsupported declared TeX encoding')
    try:
        text = raw.decode(codec)
    except UnicodeDecodeError as exc:
        raise PackageError('unsupported_encoding', 'TeX bytes are not UTF-8 or do not match the declared encoding') from exc
    if codec == 'utf-8':
        return raw, None
    return text.encode('utf-8'), {'encoding': codec, 'original_sha256': sha256(raw).hexdigest()}


def project_tex_files(files: dict[str, bytes], explicit: str | None = None):
    projected = dict(files)
    mappings = {}
    for path, raw in files.items():
        if path.lower().endswith('.tex'):
            projected[path], mapping = project_encoding(raw, explicit)
            if mapping:
                mappings[path] = mapping
    return projected, mappings


def original_range(mapping, span):
    """Single-byte codecs map Unicode codepoint offsets directly to raw byte offsets."""
    return {'path': span['path'], 'encoding': mapping['encoding'],
            'file_sha256': mapping['original_sha256'],
            'byte_start': span['char_start'], 'byte_end': span['char_end'],
            'line_start': span['line_start'], 'line_end': span['line_end']}
