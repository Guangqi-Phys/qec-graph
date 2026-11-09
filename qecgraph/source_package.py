"""Read untrusted source packages without using extraction APIs or executing TeX."""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import tarfile
import tempfile
import unicodedata
import zipfile
import zlib

from .graph import canonical, hash_text


class PackageError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Limits:
    input_bytes: int = 32 * 1024 * 1024
    expanded_bytes: int = 64 * 1024 * 1024
    member_bytes: int = 16 * 1024 * 1024
    members: int = 2048
    depth: int = 16

    def __post_init__(self):
        for name, maximum in {'input_bytes': 128 << 20, 'expanded_bytes': 256 << 20,
                              'member_bytes': 128 << 20, 'members': 16384, 'depth': 64}.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'Invalid {name} limit (must be within 1..{maximum})')


@dataclass
class SourceTree:
    format: str
    files: dict[str, bytes]

    @property
    def manifest(self):
        return [{'path': path, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                for path, raw in sorted(self.files.items())]

    @property
    def digest(self):
        return hash_text(canonical(self.manifest))

    def materialize(self, destination):
        destination = Path(destination)
        destination.mkdir()
        for name, raw in sorted(self.files.items()):
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as output:
                output.write(raw)

    def entrypoints(self):
        candidates = []
        for name, raw in self.files.items():
            if PurePosixPath(name).suffix.lower() != '.tex':
                continue
            try:
                body = _tex_body(raw)
            except UnicodeDecodeError:
                continue
            if _DOCUMENT_CLASS.search(body) and _BEGIN_DOCUMENT.search(body):
                candidates.append(name)
        return sorted(candidates)


_DOCUMENT_CLASS = re.compile(r'\\documentclass\s*(?:\[[^\]]*\]\s*)?\{')
_BEGIN_DOCUMENT = re.compile(r'\\begin\s*\{document\}')
_TEX = re.compile(r'\\(?:documentclass|documentstyle|begin|input|def|newcommand|section)\b')
_NON_TEX_PREFIX = re.compile(br'\s*(?:<html|<!doctype|%pdf-)', re.I)
_WINDOWS_RESERVED = re.compile(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$', re.I)


def _tex_body(raw):
    return re.sub(r'(?<!\\)%[^\r\n]*', '', raw.decode('utf-8'))


def _path(name, limits):
    if name.startswith('/') or '\\' in name or any(ord(ch) < 32 for ch in name):
        raise PackageError('unsafe_archive', f'Unsafe archive path: {name!r}')
    while name.startswith('./'):
        name = name[2:]
    parts = name.rstrip('/').split('/')
    if len(parts) > limits.depth:
        raise PackageError('limit_exceeded', 'Archive directory depth exceeds limit')
    if any(not p or p in ('.', '..') or any(c in p for c in ':*?"<>|') or p.endswith((' ', '.'))
           or _WINDOWS_RESERVED.fullmatch(p) or len(p.encode('utf-8')) > 255 for p in parts):
        raise PackageError('unsafe_archive', f'Unsafe archive path: {name!r}')
    return '/'.join(parts)


def read_bounded(stream, maximum):
    raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise PackageError('limit_exceeded', 'Source byte limit exceeded')
    return raw


class _TreeBuilder:
    def __init__(self, limits):
        self.limits = limits
        self.files = {}
        self.entries = set()
        self.paths = {}
        self.members = self.size = 0

    def add(self, name, directory, size, open_file):
        self.members += 1
        if self.members > self.limits.members:
            raise PackageError('limit_exceeded', 'Too many archive members')
        if directory and name in ('.', './'):
            return
        path = _path(name, self.limits)
        if path in self.entries:
            raise PackageError('unsafe_archive', f'Duplicate archive member: {path}')
        self.entries.add(path)
        parents = list(PurePosixPath(path).parents)[:-1]
        for item, is_dir in [(str(parent), True) for parent in reversed(parents)] + [(path, directory)]:
            normalized = unicodedata.normalize('NFC', item).casefold()
            previous = self.paths.setdefault(normalized, (item, is_dir))
            if previous != (item, is_dir):
                raise PackageError('unsafe_archive', f'Archive path collision: {item}')
        if directory:
            return
        maximum = min(self.limits.member_bytes, self.limits.expanded_bytes - self.size)
        if size < 0 or size > maximum:
            raise PackageError('limit_exceeded', 'Archive expanded or member size exceeds limit')
        with open_file() as stream:
            raw = stream.read(size + 1)
        if len(raw) != size:
            raise PackageError('damaged_archive', 'Archive member size differs from header')
        self.files[path] = raw
        self.size += len(raw)


_CHUNK_BYTES = 256 << 10
_ZIP_DIRECTORY_ENTRY = struct.Struct('<4s24x3H12x')


def _check_zip_members(stream, maximum):
    # Use the same ZIP/ZIP64 footer reader as ZipFile so both inspect the
    # same directory. The footer's entry count is not authoritative.
    footer = zipfile._EndRecData(stream)
    if footer is None:
        raise zipfile.BadZipFile('Missing ZIP end of central directory')
    end = footer[zipfile._ECD_LOCATION]
    if footer[zipfile._ECD_SIGNATURE] == zipfile.stringEndArchive64:
        stream.seek(end)
        if stream.read(4) == zipfile.stringEndArchive:
            # Older Python releases return the ordinary footer's position.
            end -= zipfile.sizeEndCentDir64 + zipfile.sizeEndCentDir64Locator
    directory_size = footer[zipfile._ECD_SIZE]
    position = end - directory_size
    if position < 0:
        raise zipfile.BadZipFile('Bad offset for ZIP central directory')
    if directory_size < (maximum + 1) * _ZIP_DIRECTORY_ENTRY.size:
        return
    for _ in range(maximum):
        stream.seek(position)
        header = stream.read(_ZIP_DIRECTORY_ENTRY.size)
        if len(header) != _ZIP_DIRECTORY_ENTRY.size:
            raise zipfile.BadZipFile('Truncated ZIP central directory')
        signature, name, extra, comment = _ZIP_DIRECTORY_ENTRY.unpack(header)
        if signature != zipfile.stringCentralDir:
            raise zipfile.BadZipFile('Invalid ZIP central directory header')
        position += _ZIP_DIRECTORY_ENTRY.size + name + extra + comment
        if position > end:
            raise zipfile.BadZipFile('Truncated ZIP central directory entry')
        if position == end:
            return
    raise PackageError('limit_exceeded', 'Too many archive members')


def _unpack(stream, size, compressed, limits):
    prefix = stream.read(262)
    stream.seek(0)
    tree = _TreeBuilder(limits)
    if prefix.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')):
        _check_zip_members(stream, limits.members)
        with zipfile.ZipFile(stream) as archive:
            for item in archive.infolist():
                mode = stat.S_IFMT(item.external_attr >> 16)
                if item.flag_bits & 1 or mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise PackageError('unsafe_archive', 'Encrypted or special ZIP member')
                if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise PackageError('unsupported_format', 'ZIP member must be stored or DEFLATE')
                tree.add(item.orig_filename, item.is_dir(), item.file_size, lambda: archive.open(item))
        return SourceTree('gzip_zip' if compressed else 'zip', tree.files)
    try:
        archive = tarfile.open(fileobj=stream, mode='r:')
    except tarfile.ReadError as exc:
        if prefix[257:262] == b'ustar':
            raise PackageError('damaged_archive', 'Invalid tar header') from exc
    else:
        with archive:
            for item in archive:
                if item.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE) or item.issparse():
                    raise PackageError('unsafe_archive', 'Linked or special tar member')
                tree.add(item.name, item.isdir(), item.size, lambda: archive.extractfile(item))
            trailer_size = size - archive.offset
            if trailer_size < 1024:
                raise PackageError('damaged_archive', 'Tar missing a valid zero-block trailer')
            stream.seek(archive.offset)
            while chunk := stream.read(_CHUNK_BYTES):
                if chunk.count(0) != len(chunk):
                    raise PackageError('damaged_archive', 'Tar missing a valid zero-block trailer')
        return SourceTree('tar.gz' if compressed else 'tar', tree.files)
    stream.seek(0)
    raw = stream.read()
    if _NON_TEX_PREFIX.match(raw) or b'\x00' in raw:
        raise PackageError('unsupported_format', 'Expected TeX source, not PDF, HTML or binary data')
    try:
        text = _tex_body(raw)
    except UnicodeDecodeError as exc:
        raise PackageError('unsupported_format', 'Standalone source is not UTF-8 TeX') from exc
    if not _TEX.search(text):
        raise PackageError('unsupported_format', 'No recognizable standalone TeX syntax')
    if len(raw) > min(limits.member_bytes, limits.expanded_bytes):
        raise PackageError('limit_exceeded', 'Standalone source exceeds expanded byte limit')
    return SourceTree('gzip_tex' if compressed else 'tex', {'main.tex': raw})


def unpack(raw, limits=Limits()):
    if len(raw) > limits.input_bytes:
        raise PackageError('limit_exceeded', 'Input package exceeds byte limit')
    try:
        with io.BytesIO(raw) as source:
            if not raw.startswith(b'\x1f\x8b'):
                return _unpack(source, len(raw), False, limits)
            # Bound headers and padding too. Spill large expanded streams to a
            # temporary file, then reuse that stream for format detection.
            maximum = limits.expanded_bytes + (4 << 20)
            with gzip.GzipFile(fileobj=source) as compressed, tempfile.SpooledTemporaryFile(max_size=4 << 20) as expanded:
                size = 0
                while chunk := compressed.read(min(_CHUNK_BYTES, maximum - size + 1)):
                    size += len(chunk)
                    if size > maximum:
                        raise PackageError('limit_exceeded', 'Source byte limit exceeded')
                    expanded.write(chunk)
                expanded.seek(0)
                return _unpack(expanded, size, True, limits)
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, OSError, zlib.error, NotImplementedError) as exc:
        raise PackageError('damaged_archive', f'Could not read archive: {exc}') from exc
