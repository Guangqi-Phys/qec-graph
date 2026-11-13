"""Read literal bibliography entries and explicit publication identifiers."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

_ENTRY = re.compile(r'(?m)^[ \t]*@([a-z][a-z0-9_-]*)\s*([{(])\s*', re.I)
_KEY = re.compile(r'\s*([^\s,{}()]+)\s*,')
_ARXIV_ID = r'(?:[0-9]{4}\.[0-9]{4,5}|[a-z][a-z.-]*/[0-9]{7})(?:v[1-9][0-9]*)?'
_DOI_ID = r'10\.\d{4,9}/[^\s{}"<>]+'
_FIELD = re.compile(r'\s*,?\s*([a-z][a-z0-9_-]*)\s*=\s*', re.I)
_URL = re.compile(r'https?://[^\s{}"<>\\]+', re.I)
_INLINE = re.compile(r'\barxiv\s*:\s*(' + _ARXIV_ID + r')(?![\w/])', re.I)


def _end(text, start, closer):
    braces = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == '\\':
            escaped = True
        elif not braces and char == closer and (closer == '"' or not quoted):
            return index + 1
        elif char == '"' and not braces:
            quoted = not quoted
        elif char == '{':
            braces += 1
        elif char == '}' and braces:
            braces -= 1
    return None


def bib_entries(text):
    stop = 0
    for entry in _ENTRY.finditer(text):
        if entry.start() < stop:
            continue
        end = _end(text, entry.end(), '}' if entry[2] == '{' else ')')
        if end is None:
            break
        stop = end
        key = _KEY.match(text, entry.end(), stop)
        if key and entry[1].casefold() not in {'comment', 'preamble', 'string'}:
            yield key[1], entry.start(), stop


def _literal_fields(text, start):
    while match := _FIELD.match(text, start):
        name = match[1].casefold()
        start = match.end()
        opener = text[start:start + 1]
        if opener in {'{', '"'}:
            end = _end(text, start + 1, '}' if opener == '{' else '"')
            if end is None:
                return
            tail = text[end:].lstrip()
            if tail.startswith((',', '}', ')')):
                yield name, text[start + 1:end - 1].strip()
                start = end
                continue
        # Bare values and concatenations are opaque. Do not match a field
        # inside an unsupported value.
        comma = _end(text, start, ',')
        if comma is None:
            return
        start = comma


def registered_identifier(url):
    if not url:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme not in {'https', 'http'}:
        return None
    host, address = parsed.hostname, parsed.path.lstrip('/')
    if host in {'doi.org', 'dx.doi.org'} and re.fullmatch(_DOI_ID, address, re.I):
        return 'doi:' + address.lower()
    if host in {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}:
        match = re.fullmatch(r'(?:abs|pdf)/(' + _ARXIV_ID + r')(?:\.pdf)?/?', address, re.I)
        if match:
            return 'arxiv:' + match[1].lower()
    return None


def citation_identifiers(text):
    entry = _ENTRY.match(text)
    key = _KEY.match(text, entry.end()) if entry else None
    if key:
        return _bibtex_identifiers(dict(_literal_fields(text, key.end())))
    arxiv = {'arxiv:' + match[1].lower() for match in _INLINE.finditer(text)}
    urls = {registered_identifier(match[0].rstrip('.,;)')) for match in _URL.finditer(text)}
    return sorted(arxiv | {identifier for identifier in urls if identifier})


def _bibtex_identifiers(fields):
    identifiers = set()
    url = registered_identifier(fields.get('url'))
    if url:
        identifiers.add(url)
    doi = fields.get('doi', '')
    if re.fullmatch(_DOI_ID, doi, re.I):
        identifiers.add('doi:' + doi.lower())
    eprint = fields.get('eprint', '')
    archive = fields.get('archiveprefix', fields.get('eprinttype', 'arxiv'))
    if archive.casefold() == 'arxiv' and re.fullmatch(_ARXIV_ID, eprint, re.I):
        identifiers.add('arxiv:' + eprint.lower())
    return sorted(identifiers)
