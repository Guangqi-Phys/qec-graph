"""Source label locations, including literal wrappers confirmed by consumed AUX."""

from collections import Counter
import json
import re

from .reference_syntax import group
from .options import fields, mask_comments

from .artifacts import CROSS_REFERENCE_POLICY as CROSS_REFERENCE_POLICY


def check_reference_candidates(files, document, text, manifest):
    """Rebuild all candidates; preserving ambiguity never permits dropping a target."""
    policy = document.get("cross_reference_policy")
    if manifest.get("rule_version") == "compile-prepare-v19" or policy is not None:
        if policy != CROSS_REFERENCE_POLICY:
            raise ValueError(
                "Unsupported or missing cross-reference preparation policy"
            )
    if policy == CROSS_REFERENCE_POLICY:
        _check_prepared_targets(document, manifest)
    if policy is None or "references.json" not in files or document.get("dialect"):
        return  # Legacy bundles retain their original gate; Harvmac checks its grammar.
    references = json.loads(files["references.json"])
    labels, rows = cross_references(
        document["nodes"],
        references.get("external_labels", []),
        references.get("observed_labels", []),
        text,
        document.get("environment_label_declarations", []),
    )
    if labels != document.get("labels", []) or rows != document.get(
        "cross_references", []
    ):
        raise ValueError(
            "Cross-reference candidates do not match retained source evidence"
        )


def _check_prepared_targets(document, manifest):
    missing = any(
        target["status"] == "unresolved"
        for row in document.get("cross_references", [])
        if row["region"] == "body"
        for target in row["targets"]
    )
    if manifest["status"] == "ready" and missing:
        raise ValueError("Ready preparation has unresolved cross-reference targets")


def _tex_key(value):
    """Match TeX argument tokenization: runs of whitespace become one space."""
    return re.sub(r"\s+", " ", value).strip()


def cross_references(
    nodes, external_labels=(), observed_labels=(), text="", declarations=()
):
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
    labels.extend(_environment_labels(nodes, observed_labels, text, declarations))
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


def _environment_labels(nodes, observations, text, declarations=()):
    """Require a consumed source declaration and a unique runtime label."""
    declared = {d["environment"]: d for d in declarations if d["supports_label_option"]}
    counts = Counter(item["key"] for item in observations)
    result = []
    for node in nodes:
        if node["kind"] != "environment" or node["region"] != "body":
            continue
        declaration = declared.get(node["name"])
        if declaration is None:
            continue
        option = _label_option(node, text)
        if option is None or counts.get(_tex_key(option[0])) != 1:
            continue
        value, start, end = option
        key = _tex_key(value)
        result.append(
            {
                "node": node["id"],
                "keys": [key],
                "command": "begin:" + node["name"],
                "region": node["region"],
                "origin": "environment_option_verified_by_aux",
                "environment": node["name"],
                "source_spans": node["source_spans"],
                "label_chars": [start, end],
                "declaration": declaration["origin"],
                "observations": [item for item in observations if item["key"] == key],
            }
        )
    return result


def _label_option(node, text):
    start, end = node["range"]
    header = re.match(
        r"\\begin\s*\{\s*" + re.escape(node["name"]) + r"\s*\}", text[start:end]
    )
    optional = group(text, start + header.end(), "[") if header else None
    if optional is None:
        return None
    body, _, bracket_start, _ = optional
    values = []
    for a, b, field in fields(mask_comments(body)):
        match = re.fullmatch(r"\s*label\s*=\s*(.*?)\s*", field, re.S)
        if match:
            value = match[1]
            value = (
                value[1:-1] if value.startswith("{") and value.endswith("}") else value
            )
            if not any(c in value for c in "\\#{}"):
                values.append((value, bracket_start + 1 + a, bracket_start + 1 + b))
    return values[0] if len(values) == 1 else None


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
