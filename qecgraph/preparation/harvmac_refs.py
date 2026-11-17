"""Bind literal Harvmac definitions to consumed native bibliography text."""

from collections import Counter
from pathlib import Path
import re

from .options import mask_comments
from .references import group, _record
from ..source.dialects import _syntax


def adapt(build, tree, result, *, compiled=None):
    originals = _originals(build, tree)
    compiled = _compiled(build) if compiled is None else compiled
    counts = Counter(r["key"] for r in originals)
    bindings = []
    for original in originals:
        matches = [
            c
            for c in compiled
            if _payload(c["payload_tex"]) == _payload(original["payload_tex"])
        ]
        resolved = len(matches) == 1 and counts[original["key"]] == 1
        bindings.append(
            {
                "key": original["key"],
                "section": "0",
                "status": "resolved"
                if resolved
                else "ambiguous"
                if matches
                else "unresolved",
                "entries": [original],
                "display_tex": matches[0]["display_tex"] if resolved else None,
                "compiled_entries": matches,
            }
        )
    observed = {
        c["origin"]["chars"][0] for b in bindings for c in b["compiled_entries"]
    }
    complete = all(b["status"] == "resolved" for b in bindings) and len(
        observed
    ) == len(compiled)
    result.update(
        mode="harvmac",
        entries=originals,
        bindings=bindings,
        compiled_entries=compiled,
        complete=complete,
    )
    if not complete:
        result["diagnostics"].append({"code": "harvmac_bibliography_unbound"})
    return result


def _payload(text):
    tokens = []
    for token in re.findall(
        r"\\[A-Za-z@]+|\\.|\s+|[^\\\s]+", mask_comments(text).strip()
    ):
        if token.isspace():
            if tokens and re.fullmatch(r"\\[A-Za-z@]+", tokens[-1]):
                continue
            token = " "
        tokens.append(token)
    return tuple(tokens)


def _originals(build, tree):
    records = []
    for path in build.inputs:
        if path not in tree.files or Path(path).suffix != ".tex":
            continue
        raw = tree.files[path]
        text = raw.decode()
        for match in re.finditer(
            r"\\(ref|nref|lref)\s*\\([A-Za-z@]+)\s*\{", _syntax(text)
        ):
            arg = group(text, match.end() - 1)
            if arg is None:
                raise ValueError("Unclosed Harvmac bibliography definition")
            record = _record(
                match[2], "0", None, path, raw, match.start(), arg[1], True
            )
            record.update(payload_tex=arg[0], definition_command=match[1])
            records.append(record)
    return records


def _compiled(build):
    if "refs.tmp" not in build.inputs:
        return []
    path = build.root / "project/refs.tmp"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Harvmac bibliography is not a consumed regular file")
    return compiled_entries(path.read_bytes())


def compiled_entries(raw):
    text = raw.decode()
    matches = list(re.finditer(r"\\item\s*\{\s*(\[[0-9]+\])\\\s*\}", text))
    records = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        record = _record(
            match[1], "0", None, "refs.tmp", raw, match.start(), end, False
        )
        record.update(display_tex=match[1], payload_tex=text[match.end() : end])
        records.append(record)
    return records


def _key(argument):
    match = re.fullmatch(r"\\([A-Za-z@]+)", argument.strip())
    return match[1] if match else None


def citations(nodes, references, diagnostics):
    bindings = {r["key"]: r for r in references["bindings"]}
    result = []
    for node in nodes:
        if node["region"] != "body":
            continue
        args = node["arguments"]
        if node["name"] == "ref" and len(args) == 2:
            keys = [_key(args[0])]
        elif node["name"] == "refs" and args:
            keys = re.findall(r"\\([A-Za-z@]+)", args[0])
        else:
            continue
        unresolved = [
            k for k in keys if bindings.get(k, {}).get("status") != "resolved"
        ]
        if unresolved:
            diagnostics.append(
                {
                    "code": "harvmac_citation_unbound",
                    "keys": unresolved,
                    "node": node["id"],
                }
            )
        result.append(
            {
                "node": node["id"],
                "keys": keys,
                "section": "0",
                "origin": "native_harvmac_grammar",
                "region": node["region"],
                "source_spans": node["source_spans"],
            }
        )
    return result


def cross_references(nodes):
    labels, references = [], []
    for node in nodes:
        if node["region"] != "body" or node["name"] not in {
            "eqn",
            "eqnn",
            "eqna",
            "figlabel",
            "seclab",
            "subseclab",
        }:
            continue
        if node["arguments"] and (key := _key(node["arguments"][0])):
            labels.append(
                {
                    "node": node["id"],
                    "keys": [key],
                    "command": node["name"],
                    "region": "body",
                }
            )
    definitions = {
        n["children"][0]
        for n in nodes
        if n["children"]
        and n["name"] in {"eqn", "eqnn", "eqna", "figlabel", "seclab", "subseclab"}
    }
    keys = {k for row in labels for k in row["keys"]}
    for node in nodes:
        if (
            node["kind"] == "macro"
            and node["region"] == "body"
            and node["name"] in keys
            and node["id"] not in definitions
        ):
            targets = [r["node"] for r in labels if node["name"] in r["keys"]]
            references.append(
                {
                    "node": node["id"],
                    "keys": [node["name"]],
                    "command": "harvmac_control_reference",
                    "region": "body",
                    "targets": [
                        {
                            "key": node["name"],
                            "nodes": targets,
                            "external_targets": [],
                            "status": "resolved" if len(targets) == 1 else "ambiguous",
                        }
                    ],
                }
            )
    return labels, references
