"""Locate literal citations and generated notes in recorder-bound namespaces."""

import re

from .artifacts import SourceIndex
from .reference_syntax import group, commands
from ..source.assembly import entry_source_spans
from ..source.syntax import CITATION_COMMANDS


def scope_commands(references):
    return {
        prefix + s["suffix"]: s["id"]
        for s in references.get("scopes", [])
        if s["kind"] == "multibib"
        for prefix in ("cite", "nocite")
    }


def locate_citations(nodes, references, diagnostics, text, assembly, tree):
    required = {(r["section"], r["key"]) for r in references["bindings"]}
    revtex = any(
        n["name"] == "documentclass"
        and any(a and a.startswith("{revtex") for a in n["arguments"])
        for n in nodes
    )
    node_scopes = _node_scopes(nodes, references, diagnostics)
    result, located = _literal_calls(
        nodes, required, revtex, node_scopes, scope_commands(references)
    )
    wildcard_calls, wildcard_keys = _wildcard_calls(
        nodes, references, required, node_scopes
    )
    result.extend(wildcard_calls)
    located.update(wildcard_keys)
    wrapped, wrapped_keys = _wrapper_calls(
        nodes, required, text, assembly, tree, node_scopes
    )
    notes, note_keys = _footnote_calls(nodes, references, node_scopes, revtex)
    result.extend([*wrapped, *notes])
    missing = sorted(required - located - wrapped_keys - note_keys)
    unbound = sorted(located - required)
    if unbound:
        diagnostics.append(
            {"code": "literal_citation_unbound", "bindings": [list(v) for v in unbound]}
        )
    if missing:
        diagnostics.append(
            {
                "code": "expanded_citation_locations_unknown",
                "bindings": [list(v) for v in missing],
            }
        )
    return result


def _wildcard_calls(nodes, references, required, node_scopes):
    extra = scope_commands(references)
    wildcards = set(references.get("wildcard_sections", []))
    result, located = [], set()
    for node in nodes:
        if node["kind"] != "macro" or node["region"] not in {"body", "preamble"}:
            continue
        if node["name"] != "nocite" and not (
            node["name"] in extra and node["name"].startswith("nocite")
        ):
            continue
        args = [a for a in node["arguments"] if a and a.startswith("{")]
        scope = extra.get(node["name"], node_scopes[node["id"]])
        if (
            not args
            or scope not in wildcards
            or "*"
            not in {k.strip() for k in _split_keys(_without_comments(args[-1][1:-1]))}
        ):
            continue
        keys = sorted(k for s, k in required if s == scope)
        located.update((scope, k) for k in keys)
        result.append(
            {
                "node": node["id"],
                "section": scope,
                "keys": keys,
                "origin": "compiled_nocite_wildcard",
                "source_spans": node["source_spans"],
            }
        )
    return result, located


def _node_scopes(nodes, references, diagnostics):
    units = sorted(
        (s for s in references.get("scopes", []) if s["kind"] == "bibunit"),
        key=lambda s: s["ordinal"],
    )
    envs = [n for n in nodes if n["kind"] == "environment" and n["name"] == "bibunit"]
    if len(units) != len(envs):
        diagnostics.append(
            {
                "code": "bibunit_scope_unmapped",
                "source_units": len(envs),
                "compiled_units": len(units),
            }
        )
    ids = (
        {n["id"]: s["id"] for n, s in zip(envs, units)}
        if len(units) == len(envs)
        else {}
    )
    scopes, section = {}, 0
    for node in nodes:
        scope = scopes.get(node["parent"], "0")
        if node["kind"] == "environment" and node["name"] == "refsection":
            section += 1
            scope = str(section)
        scopes[node["id"]] = ids.get(node["id"], scope)
    return scopes


def _literal_calls(nodes, required, revtex, node_scopes, extra):
    result, located = [], set()
    for node in nodes:
        if node["kind"] != "macro" or node["name"] not in CITATION_COMMANDS | set(
            extra
        ):
            continue
        arguments = [a for a in node["arguments"] if a and a.startswith("{")]
        if not arguments or node["region"] not in {"body", "preamble"}:
            continue
        scope = extra.get(node["name"], node_scopes[node["id"]])
        for literal in _split_keys(_without_comments(arguments[-1][1:-1])):
            key = _citation_key(literal.strip(), scope, required, revtex)
            if key in {"", "*"} or (
                node["region"] == "preamble" and (scope, key) not in required
            ):
                continue
            located.add((scope, key))
            result.append(
                {
                    "node": node["id"],
                    "key": key,
                    "section": scope,
                    "call_tex": arguments[-1],
                    "origin": "literal_call",
                    "command": node["name"],
                    "source_spans": node["source_spans"],
                }
            )
    return result, located


def _without_comments(text):
    return re.sub(r"(?m)(?<!\\)%[^\n]*", "", text)


def _note_payload(raw):
    for _, _, stop in commands(raw, {"bibinfo"}):
        field = group(raw, stop)
        value = group(raw, field[1]) if field else None
        if field and value and field[0] == "note":
            return _note_text(value[0])
    return None


def _footnote_calls(nodes, references, node_scopes, revtex):
    if not revtex:
        return [], set()
    candidates = {}
    for node in nodes:
        if node["kind"] == "macro" and node["name"] in {
            "footnote",
            "footnotetext",
            "thanks",
        }:
            args = [a for a in node["arguments"] if a and a.startswith("{")]
            if args:
                value = _note_text(args[-1][1:-1])
                candidates.setdefault((node_scopes[node["id"]], value), []).append(node)
    return _match_notes(candidates, references)


def _match_notes(candidates, references):
    notes = {}
    for binding in references["bindings"]:
        if binding.get("status") != "resolved" or not re.fullmatch(
            r"Note[1-9]\d*", binding["key"]
        ):
            continue
        for entry in binding["entries"]:
            payload = _note_payload(entry["raw_tex"])
            if payload:
                notes.setdefault((binding["section"], payload), []).append(
                    (binding, entry)
                )
    result, located = [], set()
    for (scope, value), matches in notes.items():
        calls = candidates.get((scope, value), [])
        if len(matches) != 1 or len(calls) != 1:
            continue
        binding, entry = matches[0]
        node = calls[0]
        result.append(
            {
                "node": node["id"],
                "key": binding["key"],
                "section": scope,
                "origin": "literal_footnote_matching_compiled_note",
                "source_spans": node["source_spans"],
                "entry_origin": entry["origin"],
            }
        )
        located.add((scope, binding["key"]))
    return result, located


def _citation_key(key, scope, required, revtex):
    if revtex and (scope, key) not in required:
        candidate = key[1:] if key.startswith("*") else key
        for _ in range(2):
            prefix = group(candidate, 0, "[")
            if prefix:
                candidate = candidate[prefix[1] :].strip()
        if (scope, candidate) in required:
            return candidate
    return key


def _split_keys(text):
    parts, start, cursor = [], 0, 0
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text[cursor] in "[{":
            nested = group(text, cursor, text[cursor])
            if nested:
                cursor = nested[1]
                continue
        if text[cursor] == ",":
            parts.append(text[start:cursor])
            start = cursor + 1
        cursor += 1
    return [*parts, text[start:]]


def _note_text(text):
    text = _without_comments(text)
    edits = []
    for _, _, stop in commands(text, CITATION_COMMANDS):
        cursor = stop + (text[stop : stop + 1] == "*")
        for _ in range(2):
            optional = group(text, cursor, "[")
            if optional:
                cursor = optional[1]
        arg = group(text, cursor)
        if arg:
            edits.append(
                (
                    arg[2] + 1,
                    arg[3] - 1,
                    ",".join(k.strip() for k in _split_keys(arg[0])),
                )
            )
    for start, end, value in reversed(edits):
        text = text[:start] + value + text[end:]
    text = re.sub(r"\\protect\s*(?=\\)", "", text)
    text = re.sub(r"(\\[A-Za-z@]+)\s+", r"\1", text)
    return " ".join(text.split())


def _source_span_for_wrapper(tree, path, start, end):
    return SourceIndex(tree.files[path]).span(path, start, end)


def _citation_wrappers(nodes, text):
    wrappers, targets = {}, []
    for node in nodes:
        if node["kind"] != "macro" or node["name"] not in {
            "newcommand",
            "renewcommand",
            "providecommand",
        }:
            continue
        args = node["arguments"]
        target = (
            re.fullmatch(r"\{\\([A-Za-z@]+)\}", args[1] or "")
            if len(args) >= 2
            else None
        )
        if target:
            targets.append(target[1])
        if len(args) != 5 or args[2] != "[1]" or args[3] is not None:
            continue
        cite = re.search(
            r"\\cite(?:p|t)?\{([A-Za-z0-9:._/-]*#1[A-Za-z0-9:._/-]*)\}", args[4] or ""
        )
        if target and cite and (args[4] or "").count("#1") == 1:
            wrappers[target[1]] = (cite[1], node["id"])
    return {
        name: value
        for name, value in wrappers.items()
        if targets.count(name) == 1
        and not re.search(
            r"\\(?:def|gdef|edef|xdef|let)\s*\\" + re.escape(name) + r"(?![A-Za-z@])",
            text,
        )
    }


def _wrapper_calls(nodes, required, text, assembly, tree, node_scopes):
    result, located = [], set()
    wrappers = _citation_wrappers(nodes, text)
    for node in nodes:
        if (
            node["kind"] != "macro"
            or node["region"] != "body"
            or node["name"] not in wrappers
        ):
            continue
        template, definition = wrappers[node["name"]]
        start, stop = node["range"]
        argument = _wrapper_argument(node, text)
        if argument is None:
            continue
        value, end = argument
        key = template.replace("#1", value)
        scope = node_scopes.get(node["id"], "0")
        if (scope, key) in required:
            result.append(
                {
                    "node": node["id"],
                    "section": scope,
                    "keys": [key],
                    "definition_node": definition,
                    "origin": "literal_wrapper_verified_by_aux",
                    "range": [start, end],
                    "source_spans": [
                        _source_span_for_wrapper(tree, p, a, b)
                        for p, a, b in entry_source_spans(assembly, start, end)
                    ],
                }
            )
            located.add((scope, key))
    return result, located


def _wrapper_argument(node, text):
    if len(node["arguments"]) == 1 and node["arguments"][0] is not None:
        raw = node["arguments"][0]
        return (raw[1:-1] if raw.startswith("{") else raw), node["range"][1]
    stop = node["range"][1]
    arg = group(text, stop)
    if arg:
        return arg[:2]
    tail = re.match(r"\s*([A-Za-z0-9])", text[stop:])
    return (tail[1], stop + tail.end()) if tail else None
