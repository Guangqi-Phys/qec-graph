"""Conservative main-document selection from literal front matter.

This module is deliberately offline and lexical: it reads literal ``\title`` and
``\author`` arguments, does not expand macros, and never executes TeX.  It is
used only when more than one file already looks like a complete TeX document.
A candidate is selected only when the source gives one explainable winner;
otherwise the caller keeps the existing ambiguity error.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
from itertools import combinations
import re
from pathlib import PurePosixPath
from typing import Mapping, Sequence

from .reading import _group

_TITLE = re.compile(r'\\title\b')
_AUTHOR = re.compile(r'\\author\b')
_SUPPLEMENT = re.compile(
    r'\b(?:supplement(?:al|ary)?|supporting\s+information|appendix)\b', re.I)
_COMMENT = re.compile(r'(?<!\\)%[^\r\n]*')
_MACRO = re.compile(r'\\([A-Za-z@]+)\*?')
_SIMILARITY = 0.8


def _without_comments(text: str) -> str:
    return _COMMENT.sub(lambda match: ' ' * len(match.group(0)), text)


def _values(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Return literal command arguments in source order, ignoring comments."""
    values: list[str] = []
    for match in pattern.finditer(text):
        pos = match.end()
        if pos < len(text) and text[pos] == '*':
            pos += 1
        if pos < len(text) and text[pos:pos + 1] == '[':
            optional = _group(text, pos, len(text), '[')
            if optional is None:
                continue
            pos = optional[2]
        span = _group(text, pos, len(text))
        if span is not None:
            values.append(text[span[0]:span[1]])
    return values


def _normalize(value: str) -> str:
    """Keep macro names as words and retain Unicode letters for comparison."""
    value = _MACRO.sub(lambda match: ' ' + match.group(1) + ' ', value)
    return ' '.join(''.join(char if char.isalnum() else ' ' for char in value)
                    .casefold().split())


def _text(raw: bytes | str) -> str | None:
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return None


def _metadata(files: Mapping[str, bytes | str], name: str) -> dict | None:
    text = _text(files[name])
    if text is None:
        return None
    text = _without_comments(text)
    titles = _values(text, _TITLE)
    authors = _values(text, _AUTHOR)
    title = titles[-1] if titles else ''
    raw = files[name]
    digest = hashlib.sha256(raw.encode('utf-8') if isinstance(raw, str)
                            else raw).hexdigest()
    return {
        'title': title,
        'normalized_title': _normalize(title),
        'authors': sum(1 for author in authors if _normalize(author)),
        'digest': digest,
    }


def _similar_titles(metadata: Mapping[str, dict], names: Sequence[str]) -> bool:
    """Every remaining title must match every other, without transitive bridges."""
    for left, right in combinations(names, 2):
        a = metadata[left]['normalized_title']
        b = metadata[right]['normalized_title']
        if not a or not b or SequenceMatcher(None, a, b).ratio() < _SIMILARITY:
            return False
    return len(names) > 1


def _identical_context(files, names):
    """Collapse a duplicated package directory only after checking its contents."""
    from .assembly import assemble_files
    files = {path: raw.encode('utf-8') if isinstance(raw, str) else raw
             for path, raw in files.items()}
    representative = min(names, key=lambda name: (len(name), name))
    base = PurePosixPath(representative).parent
    reference = assemble_files(files, representative)
    for name in names:
        parent = PurePosixPath(name).parent
        prefix = '' if str(parent) == '.' else str(parent) + '/'
        for path, raw in files.items():
            if path.startswith(prefix):
                other = str(base / path[len(prefix):])
                if files.get(other) != raw:
                    return None
        if assemble_files(files, name).data != reference.data:
            return None
    return representative


def select_main_document(files: Mapping[str, bytes | str],
                         candidates: Sequence[str]) -> tuple[str | None, str]:
    """Return ``(entry, method)`` or ``(None, "ambiguous")``.

    Selection order is conservative and each step must leave one candidate:

    1. byte-identical candidates in the same directory share a representative;
    2. a supplement title that contains the one remaining paper title loses;
    3. a candidate without any literal title loses to the only titled one;
    4. among near-identical titles, a strictly larger literal author list wins.

    The last step requires all remaining titles to have pairwise similarity
    of at least 0.8. It
    resolves alternate compile wrappers and template copies, not unrelated
    standalone documents.  When any step would leave more than one candidate,
    the caller must keep the ambiguity error.
    """
    ordered = list(dict.fromkeys(name for name in candidates if name in files))
    if len(ordered) < 2:
        return (ordered[0], 'single-candidate') if ordered else (None, 'no-candidate')
    metadata: dict[str, dict] = {}
    for name in ordered:
        value = _metadata(files, name)
        if value is None:
            return None, 'ambiguous'
        metadata[name] = value

    # Relative includes/resources can differ between directories despite equal bytes.
    groups: dict[tuple[str, str], list[str]] = {}
    for name in ordered:
        key = (metadata[name]['digest'], str(PurePosixPath(name).parent))
        groups.setdefault(key, []).append(name)
    representatives = [
        min(group, key=lambda name: (len(name), name))
        for group in groups.values()
    ]
    if len(representatives) == 1:
        return representatives[0], 'identical-content'
    if len({metadata[name]['digest'] for name in representatives}) == 1:
        identical = _identical_context(files, representatives)
        if identical:
            return identical, 'identical-package-context'

    return _select_front_matter(metadata, representatives)


def _select_front_matter(metadata, representatives):
    """Apply only literal title/author comparisons after byte/context checks."""
    # 2. A supplement title contains the paper title it supplements.
    supplements = [name for name in representatives
                   if _SUPPLEMENT.search(metadata[name]['normalized_title'])]
    papers = [name for name in representatives if name not in supplements]
    if len(papers) == 1 and supplements:
        paper = papers[0]
        title = metadata[paper]['normalized_title']
        if title and all(title in metadata[name]['normalized_title']
                         for name in supplements):
            return paper, 'supplement-title'

    # 3. A standalone fragment without a title is not the paper.
    titled = [name for name in representatives
              if metadata[name]['normalized_title']]
    if len(titled) == 1 and len(representatives) > 1:
        if metadata[titled[0]]['authors']:
            return titled[0], 'only-titled-candidate'
    if len(titled) < len(representatives):
        representatives = titled

    # 4. Near-identical titles: prefer the variant with more literal authors.
    if _similar_titles(metadata, representatives):
        if len({metadata[name]['normalized_title'] for name in representatives}) == 1:
            return None, 'ambiguous'
        ranked = sorted(representatives, key=lambda name: (-metadata[name]['authors'],
                                                           len(name), name))
        best, runner_up = ranked[0], ranked[1]
        best_authors = metadata[best]['authors']
        if best_authors and best_authors > metadata[runner_up]['authors']:
            return best, 'near-duplicate-title-author-count'
    return None, 'ambiguous'
