"""Literal TeX option fields with balanced groups and exact character offsets."""


def fields(text):
    start, depth, position = 0, 0, 0
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "%":
            end = text.find("\n", position)
            position = len(text) if end < 0 else end + 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "," and depth == 0:
            yield start, position, text[start:position]
            start = position + 1
        position += 1
    if depth != 0:
        return
    yield start, len(text), text[start:]


def mask_comments(text):
    chars, position = list(text), 0
    while position < len(text):
        if text[position] == "\\":
            position += 2
        elif text[position] == "%":
            end = text.find("\n", position)
            end = len(text) if end < 0 else end
            chars[position:end] = " " * (end - position)
            position = end
        else:
            position += 1
    return "".join(chars)
