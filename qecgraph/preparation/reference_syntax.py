"""Literal reference token readers and source-bound records, without build policy."""

import re
from .artifacts import digest
from ..source.bibliography import citation_identifiers


def group(text, start, opener="{"):
    """Read a balanced TeX argument, retaining positions and skipping comments."""
    start = _space(text, start)
    if start >= len(text) or text[start] != opener:
        return None
    closer = "}" if opener == "{" else "]"
    depth, braces, cursor = 1, 0, start + 1
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "%":
            newline = text.find("\n", cursor)
            cursor = newline if newline >= 0 else len(text)
            continue
        if opener == "[" and char in "{}":
            braces += 1 if char == "{" else -1
        elif not braces and char == opener:
            depth += 1
        elif not braces and char == closer:
            depth -= 1
            if not depth:
                return text[start + 1 : cursor], cursor + 1, start, cursor + 1
        cursor += 1
    return None


def _space(text, start):
    while start < len(text):
        if text[start].isspace():
            start += 1
        elif text[start] == "%":
            end = text.find("\n", start)
            start = len(text) if end < 0 else end + 1
        else:
            break
    return start


def commands(text, names):
    # Mask comments without moving source coordinates.
    masked = re.sub(r"(?m)(?<!\\)%[^\n]*", lambda m: " " * len(m[0]), text)
    pattern = (
        r"\\(" + "|".join(sorted(names, key=len, reverse=True)) + r")(?![A-Za-z@])"
    )
    for match in re.finditer(pattern, masked):
        yield match[1], match.start(), match.end()


def origin(path, raw, start, end, *, layer):
    text = raw.decode("utf-8")
    return {
        "path": path,
        "sha256": digest(raw),
        "layer": layer,
        "encoding": "utf-8",
        "chars": [start, end],
        "bytes": [len(text[:start].encode()), len(text[:end].encode())],
        "lines": [
            text.count("\n", 0, start) + 1,
            text.count("\n", 0, max(start, end - 1)) + 1,
        ],
    }


def _record(key, section, context, path, raw, start, end, original):
    text = raw.decode()
    return {
        "key": key,
        "section": section,
        "context": context,
        "raw_tex": text[start:end],
        "identifiers": citation_identifiers(text[start:end]),
        "origin": origin(
            path, raw, start, end, layer="original" if original else "compiled"
        ),
    }
