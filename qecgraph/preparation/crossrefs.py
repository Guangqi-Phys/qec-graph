"""Source label locations, including literal wrappers confirmed by consumed AUX."""

from collections import Counter
import re

from .references import group


def _tex_key(value):
    """Match TeX argument tokenization: runs of whitespace become one space."""
    return re.sub(r"\s+", " ", value).strip()


def cross_references(nodes, external_labels=(), observed_labels=(), text=""):
    labels, references = [], []
    for node in nodes:
        if node["kind"] != "macro" or node["name"] not in {
            "label",
            "ref",
            "eqref",
            "pageref",
            "autoref",
            "cref",
            "Cref",
        }:
            continue
        args = [a for a in node["arguments"] if a and a.startswith("{")]
        if not args:
            continue
        row = {
            "node": node["id"],
            "keys": [_tex_key(k) for k in args[-1][1:-1].split(",")],
            "command": node["name"],
            "region": node["region"],
        }
        (labels if node["name"] == "label" else references).append(row)
    labels.extend(_wrapper_labels(nodes, observed_labels, text))
    labels.extend(_environment_labels(nodes, observed_labels, text))
    for row in references:
        row["targets"] = []
        for key in row["keys"]:
            matches = [
                n["node"] for n in labels if n["region"] == "body" and key in n["keys"]
            ]
            imported = [label for label in external_labels if label["key"] == key]
            count = len(matches) + len(imported)
            row["targets"].append(
                {
                    "key": key,
                    "nodes": matches,
                    "external_targets": imported,
                    "status": "resolved"
                    if count == 1
                    else "ambiguous"
                    if count
                    else "unresolved",
                }
            )
    return labels, references


def _environment_labels(nodes, observations, text):
    """Bind ``label={key}`` in a literal environment option to an emitted AUX key.

    This is the tcolorbox/newtcolorbox convention: the environment creates the
    label from a key/value option, so no source ``\\label`` call exists.  AUX
    confirmation is still mandatory and a key emitted more than once is left
    ambiguous rather than assigned to this environment.
    """
    if not text:
        return []
    counts = Counter(item["key"] for item in observations)
    result = []
    for node in nodes:
        if node["kind"] != "environment" or node["region"] != "body":
            continue
        start, end = node["range"]
        header = re.match(
            r"\s*\\begin\s*\{\s*" + re.escape(node["name"] or "") + r"\s*\}",
            text[start:end],
        )
        if header is None:
            continue
        optional = group(text, start + header.end(), "[")
        if optional is None:
            continue
        body, _, bracket_start, _ = optional
        for match in re.finditer(r"(?<![A-Za-z@])label\s*=\s*", body):
            value = _option_value(body, match.end())
            if value is None:
                continue
            key = _tex_key(value)
            if counts.get(key) != 1:
                continue
            result.append(
                {
                    "node": node["id"],
                    "keys": [key],
                    "command": "begin:" + node["name"],
                    "region": node["region"],
                    "origin": "environment_option_verified_by_aux",
                    "environment": node["name"],
                    "source_spans": node["source_spans"],
                    "label_chars": [
                        bracket_start + 1 + match.start(),
                        bracket_start + 1 + match.end(),
                    ],
                    "observations": [
                        item for item in observations if item["key"] == key
                    ],
                }
            )
    return result


def _option_value(body, position):
    while position < len(body) and body[position].isspace():
        position += 1
    if position >= len(body):
        return None
    if body[position] == "{":
        value = group(body, position)
        return value[0] if value else None
    match = re.match(r"[^,\]]+", body[position:])
    return match[0].strip() if match else None


def _wrapper_labels(nodes, observations, text):
    templates = _label_templates(nodes, text)
    observed = {r["key"] for r in observations}
    result = []
    for node in nodes:
        if node["kind"] != "macro" or node["region"] != "body":
            continue
        template = templates.get(node["name"])
        if template is None:
            continue
        definition, offset, prefix, number, suffix = template
        if offset > node["range"][0]:
            continue
        arguments = node["arguments"]
        if len(arguments) < number or arguments[number - 1] is None:
            continue
        argument = arguments[number - 1]
        argument = argument[1:-1] if argument.startswith("{") else argument
        if not re.fullmatch(r"[A-Za-z0-9:._/-]+", argument):
            continue
        key = prefix + argument + suffix
        if key in observed:
            result.append(
                {
                    "node": node["id"],
                    "keys": [key],
                    "command": node["name"],
                    "region": node["region"],
                    "definition_node": definition,
                    "origin": "literal_wrapper_verified_by_aux",
                    "source_spans": node["source_spans"],
                    "observations": [r for r in observations if r["key"] == key],
                }
            )
    return result


def _label_templates(nodes, text):
    definitions = [
        n
        for n in nodes
        if n["kind"] == "macro"
        and n["name"]
        in {
            "newcommand",
            "renewcommand",
            "providecommand",
            "def",
            "gdef",
            "edef",
            "xdef",
            "let",
        }
    ]
    names = [_definition_name(n) for n in definitions]
    counts = Counter(names)
    result = {}
    for node, name in zip(definitions, names):
        args = node["arguments"]
        if (
            name is None
            or counts[name] != 1
            or len(args) != 5
            or _indirect_redefinition(name, text)
        ):
            continue
        body = args[-1] or ""
        # No conditional execution or indirect label construction is inferred.
        if re.search(r"\\(?:if[A-Za-z@]*|loop|foreach)\b", body):
            continue
        label = re.search(
            r"\\label\{([A-Za-z0-9:._/-]*)#([1-9])([A-Za-z0-9:._/-]*)\}", body
        )
        if label and body.count(r"\label") == 1:
            result[name] = (
                node["id"],
                node["range"][1],
                label[1],
                int(label[2]),
                label[3],
            )
    return result


def _definition_name(node):
    args = node["arguments"]
    if len(args) != 5:
        return None
    match = re.fullmatch(r"\{?\\([A-Za-z@]+)\}?", args[1] or "")
    return match[1] if match else None


def _indirect_redefinition(name, text):
    return bool(
        re.search(
            r"\\(?:def|gdef|edef|xdef|let)\s*\\" + re.escape(name) + r"(?![A-Za-z@])",
            text,
        )
    )
