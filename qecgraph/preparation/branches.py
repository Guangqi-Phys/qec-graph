"""A narrow lexical view for a provably false literal TeX guard, after compilation."""

import re

from ..source.assembly import (
    condition_regions,
    document_bounds,
    _conditional_bounds,
)


def literal_false_ranges(text):
    _, uncertain = condition_regions(text)
    result = []
    for start, stop in uncertain:
        # Whether TeX consumes whitespace or the next literal token, it differs
        # from zero here. Do not generalize this to \\if00 or expanded operands.
        header = re.match(r"\\if(?![A-Za-z@])\s+0\s+(?=[A-Za-z1-9])", text[start:stop])
        if header is None:
            continue
        after = start + header.end()
        alternative, closing, end = _conditional_bounds(text, after)
        if end != stop or closing == len(text):
            continue
        cuts = [(start, alternative if alternative is not None else end)]
        if alternative is not None:
            cuts.append((closing, end))
        ends = [_line_end(text, b) for _, b in cuts]
        if any(b is None for b in ends):
            continue
        result.extend((a, end) for (a, _), end in zip(cuts, ends))
    return result


def syntax_view(text, extra_ranges=(), *, allow_observed_bounds=False):
    """Comment-mask inactive bytes at unchanged codepoint offsets; keep raw source."""
    ranges = list(extra_ranges)
    masked = _mask(text, ranges)
    ranges.extend(literal_false_ranges(masked))
    ranges.extend(_static_ranges(masked))
    masked = _mask(text, ranges)
    if allow_observed_bounds:
        from ..source.assembly import document_bounds_observed

        _, _, end = document_bounds_observed(masked)
    else:
        _, _, end = document_bounds(masked)
    closing = (
        re.match(r"\\end\s*\{\s*document\s*\}", masked[end:])
        if end is not None
        else None
    )
    tail = end + closing.end() if end is not None and closing is not None else len(text)
    if text[tail:].strip():
        ranges.append((tail, len(text)))
    return _mask(text, ranges), ranges


def _static_ranges(text):
    inactive, _ = condition_regions(text)
    result = []
    for start, end in inactive:
        if text[end : end + 3] == r"\fi":
            tail = _line_end(text, end + 3)
        elif text[end - 5 : end] == r"\else":
            tail = _line_end(text, end)
        else:
            tail = None
        if tail is not None:
            result.append((start, tail))
    return result


def _mask(text, ranges):
    chars = list(text)
    for start, end in ranges:
        line_start = True
        for index in range(start, end):
            if text[index] in "\r\n":
                line_start = True
            else:
                chars[index] = "%" if line_start else " "
                line_start = False
    return "".join(chars)


def _line_end(text, position):
    tail = re.match(r"[ \t]*(?=\r?\n|$)", text[position:])
    return position + tail.end() if tail else None
