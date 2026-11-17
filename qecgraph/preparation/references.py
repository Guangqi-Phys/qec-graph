"""Adapt emitted citation bindings and literal BIB/BBL, without semantic inference."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .contract import digest
from ..source.bibliography import bib_entries, citation_identifiers


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


def _entries(path, raw, original, *, scan_text=None):
    text = raw.decode() if scan_text is None else scan_text
    section, context = "0", None
    events = list(
        commands(
            text,
            {
                "refsection",
                "datalist",
                "enddatalist",
                "bibitem",
                "entry",
                "endentry",
                "end",
            },
        )
    )
    for index, (name, start, stop) in enumerate(events):
        arg = group(text, stop)
        if name == "refsection" and arg:
            section = arg[0]
        elif name == "datalist":
            optional = group(text, stop, "[")
            arg = group(text, optional[1] if optional else stop)
            context = arg[0] if arg else None
        elif name == "enddatalist":
            context = None
        elif name in {"entry", "bibitem"}:
            optional = group(text, stop, "[") if name == "bibitem" else None
            arg = group(text, optional[1] if optional else stop)
            if not arg:
                continue
            end = len(text)
            terminators = (
                {"entry", "endentry"} if name == "entry" else {"bibitem", "end"}
            )
            for next_name, next_start, next_stop in events[index + 1 :]:
                if next_name in terminators:
                    end = next_stop if next_name == "endentry" else next_start
                    break
            yield _record(arg[0], section, context, path, raw, start, end, original)


def _bcf_requests(raw, *, include_wildcards=False):
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("BCF document types and entities are unsupported")
    requested = set()
    for section in ET.fromstring(raw).iter():
        if section.tag.endswith("}section"):
            for item in section:
                if (
                    item.tag.endswith("}citekey")
                    and item.text
                    and (include_wildcards or item.text.strip() != "*")
                ):
                    requested.add((section.get("number", "0"), item.text.strip()))
    return requested


def adapt_references(build, tree, *, source_views=None):
    """Only FLS-listed files are treated as consumed build evidence."""
    project = build.root / "project"
    job = Path(build.entry).stem
    diagnostics = []
    from .scopes import reference_scopes, imported_labels, observed_labels

    aux, entries = _consumed(build, tree, diagnostics)
    controls, originals = _originals(build, tree, diagnostics)
    bcf = project / (job + ".bcf")
    scopes = reference_scopes(build, tree, aux)
    _unassigned_scopes(scopes, aux, controls, diagnostics)
    active = {
        s["id"]: "\n".join(aux[p] for p in s["aux"]) for s in scopes if s["active"]
    }
    text = "\n".join(active.values())
    biblatex = bcf.is_file() and not bcf.is_symlink()
    if biblatex:
        requested = _bcf_requests(bcf.read_bytes(), include_wildcards=True)
        labels = {}
    else:
        _scope_entries(entries, scopes)
        requested = {
            (scope, key)
            for scope, body in active.items()
            for _, key in _classic_requests(body, controls, include_wildcards=True)
        }
        labels = _scope_labels(active)
        _inline_entries(build, tree, entries, labels, diagnostics, source_views or {})
    requested, wildcards = _expand_wildcards(requested, entries, labels, diagnostics)
    result = _resolve(
        requested, entries, originals, text, diagnostics, controls, biblatex, labels
    )
    result["wildcard_sections"] = sorted(wildcards)
    result["scopes"] = scopes
    result["external_labels"] = imported_labels(scopes, aux, tree)
    result["observed_labels"] = observed_labels(scopes, aux)
    return result


def _unassigned_scopes(scopes, aux, controls, diagnostics):
    for scope in scopes:
        if scope["kind"] == "unassigned" and any(
            _classic_requests(aux[p], controls, include_wildcards=True)
            for p in scope["aux"]
        ):
            diagnostics.append(
                {"code": "unassigned_bibliography_scope", "aux": scope["aux"]}
            )


def _expand_wildcards(requested, entries, labels, diagnostics):
    wildcards = {scope for scope, key in requested if key == "*"}
    result = {(scope, key) for scope, key in requested if key != "*"}
    emitted = {(r["section"], r["key"]) for r in entries} | set(labels)
    for scope in wildcards:
        expanded = {(s, key) for s, key in emitted if s == scope}
        if not expanded:
            diagnostics.append(
                {"code": "wildcard_bibliography_unobserved", "section": scope}
            )
        result.update(expanded)
    return result, wildcards


def _scope_entries(entries, scopes):
    names = {p: s["id"] for s in scopes for p in s["bbl"]}
    for entry in entries:
        entry["section"] = names.get(entry["origin"]["path"], "0")


def _scope_labels(active):
    labels = {}
    for scope, body in active.items():
        for _, _, stop in commands(body, {"bibcite"}):
            key = group(body, stop)
            value = group(body, key[1]) if key else None
            if key and value:
                labels.setdefault((scope, key[0]), []).append(value[0])
    return labels


def _classic_requests(text, controls, *, include_wildcards=False):
    requested = set()
    for name, _, stop in commands(text, {"citation"}):
        arg = group(text, stop)
        if arg:
            requested.update(
                ("0", key.strip())
                for key in arg[0].split(",")
                if key.strip() not in controls
                and (include_wildcards or key.strip() != "*")
            )
    return requested


def _inline_entries(build, tree, entries, labels, diagnostics, source_views):
    from .branches import syntax_view

    bound = {}
    for scope, key in labels:
        bound.setdefault(key, set()).add(scope)
    for path in build.inputs:
        if path not in tree.files or Path(path).suffix not in {".tex", ""}:
            continue
        try:
            scan_text = syntax_view(source_views.get(path, tree.files[path].decode()))[
                0
            ]
            for entry in _entries(path, tree.files[path], True, scan_text=scan_text):
                _bind_inline(entry, bound, entries, diagnostics)
        except UnicodeDecodeError:
            continue


def _bind_inline(entry, bound, entries, diagnostics):
    scopes = bound.get(entry["key"], set())
    if len(scopes) == 1:
        entry["section"] = next(iter(scopes))
        entries.append(entry)
    elif scopes:
        diagnostics.append(
            {
                "code": "inline_bibliography_scope_ambiguous",
                "key": entry["key"],
                "scopes": sorted(scopes),
                "origin": entry["origin"],
            }
        )


def _resolve(
    requested, entries, originals, aux, diagnostics, controls, biblatex, labels
):
    grouped = {}
    for entry in entries:
        grouped.setdefault((entry["section"], entry["key"]), []).append(entry)
    references = []
    for section, key in sorted(requested):
        variants = grouped.get((section, key), [])
        counts = Counter(v["context"] for v in variants)
        ambiguous = (
            any(count > 1 for count in counts.values())
            or len(labels.get((section, key), [])) > 1
        )
        has_label = biblatex or len(labels.get((section, key), [])) == 1
        status = (
            "ambiguous"
            if ambiguous
            else "resolved"
            if variants and has_label
            else "unresolved"
        )
        references.append(
            {
                "section": section,
                "key": key,
                "status": status,
                "display_tex": labels.get((section, key), [None])[0],
                "entries": variants,
            }
        )
    return {
        "schema": "qecgraph.prepared_references/1",
        "mode": "biblatex" if biblatex else "classic",
        "bindings": references,
        "entries": entries,
        "original_bib_entries": originals,
        "excluded_control_keys": sorted(controls),
        "diagnostics": diagnostics,
        "complete": not diagnostics
        and all(r["status"] == "resolved" for r in references),
    }


def _consumed(build, tree, diagnostics):
    project = build.root / "project"
    aux, entries = {}, []
    for path in build.inputs:
        if Path(path).suffix not in {".aux", ".bbl", ".tex", ""}:
            continue
        file = project / path
        if file.is_symlink() or not file.is_file():
            continue
        raw = file.read_bytes()
        try:
            if path.endswith(".aux"):
                aux[path] = raw.decode()
            elif path.endswith(".bbl"):
                entries.extend(_entries(path, raw, tree.files.get(path) == raw))
        except UnicodeDecodeError:
            diagnostics.append({"code": "bibliography_encoding", "path": path})
    return aux, entries


def _originals(build, tree, diagnostics):
    project = build.root / "project"
    originals = []
    controls = set()
    for path in sorted(set(tree.files) | set(getattr(build, "outputs", []))):
        if not path.endswith(".bib"):
            continue
        file = project / path
        if path in tree.files:
            raw = tree.files[path]
        elif file.is_file() and not file.is_symlink():
            raw = file.read_bytes()
        else:
            continue
        try:
            body = raw.decode()
        except UnicodeDecodeError:
            diagnostics.append({"code": "bib_encoding", "path": path})
            continue
        controls.update(re.findall(r"@CONTROL\s*\{([^,}\s]+)", body, re.I))
        for key, start, end in bib_entries(body):
            if key not in controls and path in tree.files:
                originals.append(_record(key, None, None, path, raw, start, end, True))
    return controls, originals
