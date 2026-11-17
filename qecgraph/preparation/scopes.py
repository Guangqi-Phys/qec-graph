"""Literal bibliography/document namespaces bound to actual recorder inputs."""

from pathlib import PurePosixPath
import re


def reference_scopes(build, tree, aux):
    from .references import commands, group

    source = "\n".join(
        _configuration_text(tree.files[p])
        for p in build.inputs
        if p in tree.files and PurePosixPath(p).suffix in {".tex", ".sty", ""}
    )
    available = set(aux)
    scopes, claimed = [], set()
    for _, _, stop in commands(source, {"externaldocument"}):
        optional = group(source, stop, "[")
        arg = group(source, optional[1] if optional else stop)
        if arg and arg[0] + ".aux" in available:
            name = arg[0] + ".aux"
            scopes.append(
                _scope(
                    "external:" + arg[0],
                    "external_document",
                    [name],
                    prefix=optional[0] if optional else "",
                    active=False,
                )
            )
            claimed.add(name)
    for suffix in _multibib_names(source):
        name = suffix + ".aux"
        if name in available:
            scopes.append(
                _scope("multibib:" + suffix, "multibib", [name], suffix=suffix)
            )
            claimed.add(name)
    if re.search(
        r"\\(?:usepackage|RequirePackage)(?:\[[^]]*\])?\{[^}]*\bbibunits\b", source
    ):
        for name in sorted(available):
            match = re.fullmatch(r"bu([1-9]\d*)\.aux", name)
            if match:
                scopes.append(
                    _scope(
                        "bibunit:" + match[1], "bibunit", [name], ordinal=int(match[1])
                    )
                )
                claimed.add(name)
    job = PurePosixPath(build.entry).stem + ".aux"
    family = _aux_family(job, aux, claimed)
    primary = _scope("0", "document", sorted(family))
    scopes.insert(0, primary)
    bbls = {p for p in build.inputs if p.endswith(".bbl")}
    for scope in scopes[1:]:
        scope["bbl"] = [
            p[:-4] + ".bbl" for p in scope["aux"] if p[:-4] + ".bbl" in bbls
        ]
    assigned = {p for scope in scopes[1:] for p in scope["bbl"]}
    primary["bbl"] = sorted(bbls - assigned)
    # Unknown AUX files are retained, never silently merged into the primary paper.
    for name in sorted(available - family - claimed):
        scopes.append(_scope("unassigned:" + name, "unassigned", [name], active=False))
    return scopes


def _configuration_text(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # ASCII configuration probe only; this is never a source encoding migration.
        return raw.decode("latin1")


def _scope(identifier, kind, aux, **fields):
    return {
        "id": identifier,
        "kind": kind,
        "aux": aux,
        "bbl": [],
        "active": True,
        **fields,
    }


def _multibib_names(source):
    from .references import commands, group

    for _, _, stop in commands(source, {"newcites"}):
        arg = group(source, stop)
        if arg:
            yield from (
                s.strip()
                for s in arg[0].split(",")
                if re.fullmatch(r"[A-Za-z]+", s.strip())
            )


def _aux_family(root, aux, excluded):
    from .references import commands, group

    seen, pending = set(), [root]
    while pending:
        name = pending.pop()
        if name in seen or name in excluded or name not in aux:
            continue
        seen.add(name)
        for _, _, stop in commands(aux[name], {"@input"}):
            arg = group(aux[name], stop)
            if arg and arg[0] in aux:
                pending.append(arg[0])
    return seen


def imported_labels(scopes, aux, tree):
    from .references import commands, group, origin

    labels = []
    for scope in scopes:
        if scope["kind"] != "external_document":
            continue
        for path in scope["aux"]:
            for _, start, stop in commands(aux[path], {"newlabel"}):
                key = group(aux[path], stop)
                value = group(aux[path], key[1]) if key else None
                if key and value and path in tree.files:
                    labels.append(
                        {
                            "key": scope["prefix"] + key[0],
                            "scope": scope["id"],
                            "display_tex": value[0],
                            "raw_tex": aux[path][start : value[1]],
                            "availability": "imported_aux_metadata",
                            "origin": origin(
                                path,
                                tree.files[path],
                                start,
                                value[1],
                                layer="original",
                            ),
                        }
                    )
    return labels
