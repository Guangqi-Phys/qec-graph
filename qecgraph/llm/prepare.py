"""Plan source-format conversion; never run the content parser or classify blocks."""

from __future__ import annotations

import re
import json

from ..core.graph import canonical
from ..source.normalization import apply_plan
from .client import InputBudgetExceeded, ResponseSchemaError
from .errors import LLMError
from .providers.base import Message
from .skills import load_skill

SKILL = "prepare_input"
VERSION = 9


def normalize_input(tree, client, diagnostics="", *, entry=None):
    if not client.config.enabled or not client.config.allow_source_upload:
        raise LLMError(
            "AI preparation requires enabled AI and explicit source-upload permission"
        )
    skill = load_skill(SKILL)
    if skill.version != VERSION:
        raise ValueError("Unsupported input-preparation skill version")
    evidence = preparation_evidence(tree, diagnostics, entry)
    messages = [
        Message("system", skill.system_prompt),
        Message("user", canonical(evidence)),
    ]
    if sum(len(m.content) for m in messages) > client.config.max_input_chars:
        raise InputBudgetExceeded("Preparation evidence exceeds [ai].max_input_chars")

    normalized = None

    def validate(plan):
        nonlocal normalized
        try:
            if entry is not None and plan.get("entry") != entry:
                raise ValueError("Preparation plan changes the selected entry")
            normalized = apply_plan(tree, plan, skill.schema)
        except ValueError as exc:
            raise ResponseSchemaError(str(exc)) from None

    result = client.complete_json(
        messages,
        skill.schema,
        max_output_tokens=32768,
        validate=validate,
    )
    assert normalized is not None
    normalized.provenance.update(
        skill=skill.name,
        skill_version=skill.version,
        model=result.model,
        prompt_sha256=result.prompt_sha256,
        run_id=result.run_id,
        cached=result.cached,
        provider=client.config.provider,
        reasoning_effort=getattr(client.provider, "reasoning_effort", None),
        usage=result.usage,
    )
    return normalized


def _locations(value):
    """Read locators supplied by the downstream validator, not paper semantics."""
    result = {}
    if isinstance(value, dict):
        path = value.get("path")
        if path and ("line_start" in value or "char_start" in value):
            result.setdefault(path, []).append(value)
        for item in value.values():
            for path, spans in _locations(item).items():
                result.setdefault(path, []).extend(spans)
    elif isinstance(value, list):
        for item in value:
            for path, spans in _locations(item).items():
                result.setdefault(path, []).extend(spans)
    return result


def preparation_evidence(tree, diagnostics, entry):
    """Send failure-local source windows, never ask AI to inspect a whole paper."""
    try:
        locations = _locations(json.loads(diagnostics))
    except (ValueError, TypeError):
        locations = {}
    from ..source.prepare import entry_candidates

    try:
        candidates = entry_candidates(tree)
    except ValueError:
        candidates = []
    files = []
    guard_names = set()
    for path in locations:
        raw = tree.files.get(path, b"").decode("utf-8", errors="replace")
        guard_names.update(re.findall(r"\\(?:ifdefined|ifx)\s*\\([A-Za-z@]+)", raw))
    for path, raw in sorted(tree.files.items()):
        evidence = _file_evidence(path, raw, locations, entry, candidates, guard_names)
        if evidence is not None:
            files.append(evidence)
    return {
        "schema": "qecgraph.preparation_evidence/1",
        "source_tree_hash": tree.digest,
        "requested_entry": entry,
        "entry_candidates": candidates,
        "members": list(sorted(tree.files)),
        "diagnostics": diagnostics,
        "files": files,
    }


def _file_evidence(path, raw, locations, entry, candidates, guard_names):
    if (
        not path.endswith(".tex")
        and path != entry
        and not re.search(
            rb"\\(?:documentclass|documentstyle|input|def|bye)\b", raw[:8192]
        )
    ):
        return None
    text, encoding, encoding_error = _decode_evidence(raw)
    lines = text.splitlines(keepends=True)
    guard_rows = {
        i
        for i, line in enumerate(lines)
        if any("\\" + name in line for name in guard_names)
    }
    if (
        entry is not None
        and path != entry
        and path not in locations
        and not guard_rows
        and encoding == "utf-8"
    ):
        return None
    head = 120 if entry is None and path in candidates else (30 if path == entry else 6)
    selected = set(range(min(head, len(lines))))
    selected.update(range(max(0, len(lines) - 4), len(lines)))
    for i in guard_rows:
        selected.update(range(max(0, i - 1), min(len(lines), i + 3)))
    spans = locations.get(path, [])
    failure_rows = _failure_rows(text, lines, spans)
    selected.update(failure_rows)
    for i, line in enumerate(lines):
        # Compilation guards and literal front matter are format evidence.
        # Do not upload every unrelated math macro or drawing command.
        if re.search(
            r"\\(?:ifdefined|ifx|if|else|fi|title|Title|author|input|include)(?![A-Za-z@])",
            line,
        ):
            selected.update(range(max(0, i - 1), min(len(lines), i + 3)))
    if encoding_error is not None:
        row = raw[: encoding_error["byte_start"]].count(b"\n")
        selected.update(range(max(0, row - 3), min(len(lines), row + 4)))
    kept, used = [], 0
    for i in dict.fromkeys([*sorted(failure_rows), *sorted(selected)]):
        if used + len(lines[i]) <= (14000 if spans or path == entry else 4000):
            kept.append(i)
            used += len(lines[i])
    return {
        "path": path,
        "encoding": encoding,
        "encoding_error": encoding_error,
        "syntax_sites": _syntax_sites(text),
        "total_lines": len(lines),
        "truncated": len(kept) != len(lines),
        "lines": [[i + 1, lines[i]] for i in sorted(kept)],
    }


def _failure_rows(text, lines, spans):
    failure_rows = set()
    for span in spans:
        first = (
            span.get("line_start", text[: span.get("char_start", 0)].count("\n") + 1)
            - 1
        )
        last = span.get(
            "line_end",
            text[: span.get("char_end", span.get("char_start", 0))].count("\n") + 1,
        )
        failure_rows.update(
            range(
                max(0, first - 12),
                min(len(lines), max(first + 18, min(last + 8, first + 80))),
            )
        )
        failure_rows.update(range(max(0, last - 5), min(len(lines), last + 4)))
    for span in spans:
        position = span.get("char_start", 0)
        opening = text.rfind(r"\begin{tikzpicture}", 0, position)
        closing = text.find(r"\end{tikzpicture}", position)
        if opening >= 0 and closing >= 0:
            for offset in (opening, closing):
                row = text[:offset].count("\n")
                failure_rows.update(range(max(0, row - 1), min(len(lines), row + 2)))
    return failure_rows


def _decode_evidence(raw):
    try:
        return raw.decode("utf-8"), "utf-8", None
    except UnicodeDecodeError as exc:
        start = max(0, exc.start - 160)
        return (
            raw.decode("latin1"),
            "latin1-preview",
            {
                "byte_start": exc.start,
                "byte_end": exc.end,
                "hex": raw[exc.start : exc.end].hex(),
                "preview_start_byte": start,
                "preview": raw[start : exc.end + 160].decode("latin1"),
            },
        )


def _syntax_sites(text):
    """Literal occurrence locators, including comments; they assert no active branch."""
    pattern = r"\\(?:ifdefined\s*\\[A-Za-z@]+|ifx\s*\\[A-Za-z@]+\s*\\undefined|if\s+0)|\\(?:begin|end)\{tikzpicture\}"
    return [
        {
            "old": m[0],
            "line": text[: m.start()].count("\n") + 1,
            "occurrence": text[: m.end()].count(m[0]),
        }
        for m in re.finditer(pattern, text)
    ]
