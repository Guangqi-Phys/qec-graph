"""A conservative reading view of verbatim source blocks."""
from __future__ import annotations

import re

CITATION_COMMANDS = frozenset({
    'cite', 'citep', 'citet', 'citealp', 'citealt', 'citeauthor', 'citeyear',
    'citeyearpar', 'parencite', 'textcite', 'autocite', 'footcite', 'nocite',
})
_WRAPPERS = frozenset({'emph', 'textbf', 'textit', 'texttt', 'textsc', 'textrm', 'textsf', 'underline',
                       'section', 'subsection', 'subsubsection', 'paragraph', 'subparagraph', 'chapter', 'part'})
_DROP = frozenset({'label', 'bibliography', 'bibliographystyle', 'addbibresource'})
_LITERAL_ENVIRONMENTS = frozenset({'verbatim', 'verbatim*', 'Verbatim', 'lstlisting', 'minted', 'comment'})
_TOKEN = re.compile(r'\\(?:[A-Za-z@]+\*?|[^\r\n])|%[^\r\n]*|\$\$?')
_GROUP = re.compile(r'\\[^\r\n]|%[^\r\n]*|[{}\[\]]')
_LITERAL_GROUP = re.compile(r'\\[^\r\n]|[{}]')
_KEYS = re.compile(r'[\w.:/+*-]+(?:\s*,\s*[\w.:/+*-]+)*')
_SPACE = re.compile(r'\s*')


def _group(text, pos, stop, opening='{', *, literal=False):
    start = _SPACE.match(text, pos, stop).end()
    if start == stop or text[start] != opening:
        return None
    closing = '}' if opening == '{' else ']'
    stack = [closing]
    for match in (_LITERAL_GROUP if literal else _GROUP).finditer(text, start + 1, stop):
        token = match[0]
        if token == '{' or (token == '[' and stack[-1] == ']'):
            stack.append('}' if token == '{' else ']')
        elif token == stack[-1]:
            stack.pop()
            if not stack:
                return start + 1, match.start(), match.end()
    return None


def reading_projection(text, *, kind=None, bibliography=False):
    """Return display text and literal citation tokens with original offsets."""
    citations = []
    if bibliography:
        return '', citations
    if kind == 'equation':
        return text.strip(), citations

    def walk(pos, stop, depth=0):
        if depth == 16:
            return text[pos:stop]
        result = []
        while (match := _TOKEN.search(text, pos, stop)) is not None:
            start, end = match.span()
            token = match[0]
            result.append(text[pos:start])
            pos = end
            if token.startswith('%'):
                continue
            if token in ('$', '$$', r'\(', r'\['):
                closing = {r'\(': r'\)', r'\[': r'\]'}.get(token, token)
                for closer in _TOKEN.finditer(text, end, stop):
                    if closer[0] == closing:
                        pos = closer.end()
                        break
                else:
                    pos = stop
                result.append(text[start:pos])
                continue
            command = token[1:].removesuffix('*')
            if command == 'verb' and end < stop and text[end] not in '\r\n':
                closing = text.find(text[end], end + 1, stop)
                if closing >= 0:
                    pos = closing + 1
                    result.append(text[start:pos])
                    continue
            if command == 'begin':
                arg = _group(text, end, stop)
                name = text[arg[0]:arg[1]] if arg else ''
                if name in _LITERAL_ENVIRONMENTS:
                    closing = '\\end{' + name + '}'
                    close = text.find(closing, arg[2], stop)
                    pos = close + len(closing) if close >= 0 else stop
                    if name != 'comment':
                        result.append(text[start:pos])
                    continue
            if command in CITATION_COMMANDS or command in _WRAPPERS | _DROP | {'href', 'url', 'nolinkurl'}:
                for _ in range(2):
                    optional = _group(text, end, stop, '[')
                    if optional is None:
                        break
                    end = optional[2]
                arg = _group(text, end, stop, literal=command in {'href', 'url', 'nolinkurl'})
                if arg:
                    a, b, tail = arg
                    if command in CITATION_COMMANDS:
                        keys = text[a:b].strip()
                        if _KEYS.fullmatch(keys):
                            citations.append((start, tail, command, [key.strip() for key in keys.split(',')]))
                            pos = tail
                            continue
                    elif command in _DROP:
                        pos = tail
                        continue
                    elif command in {'url', 'nolinkurl'}:
                        result.append(text[a:b])
                        pos = tail
                        continue
                    else:
                        display = _group(text, tail, stop) if command == 'href' else arg
                        if display:
                            a, b, pos = display
                            result.append(walk(a, b, depth + 1))
                            continue
            result.append(token[1:] if token in (r'\%', r'\&', r'\#', r'\_') else token)
        result.append(text[pos:stop])
        return ''.join(result)

    return walk(0, len(text)).strip(), citations
