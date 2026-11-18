"""Project the current prepared bundle into a source-bound extraction."""

from bisect import bisect_right
from pathlib import Path

from .preparation.artifacts import SourceIndex, digest, safe_path
from .preparation.contract import read_material
from .preparation.projection import original_locator
from .preparation.reference_syntax import group
from .source.extraction import notation_matches
from .validators import packaged_validator


INPUT_VERSION = "compile-prepare-v20"
SCHEMA = "qecgraph.prepared_extraction/1"
RULE_VERSION = "prepared-extract-v1"
METADATA = frozenset({"title", "author", "date"})
_CAPTIONS = frozenset({"caption", "captionof"})
_STATEMENTS = frozenset(
    {
        "theorem",
        "lemma",
        "proposition",
        "corollary",
        "definition",
        "assumption",
        "conjecture",
        "claim",
        "axiom",
        "remark",
        "hypothesis",
        "notation",
    }
)
_FLOATS = {
    "figure": "figure",
    "subfigure": "figure",
    "table": "table",
    "longtable": "table",
    "algorithm": "algorithm",
    "algorithmic": "algorithm",
}


class PreparedSource:
    """Read a hash-bound bundle and translate entry ranges to source pieces."""

    def __init__(self, root: Path):
        manifest_file = root / "manifest.json"
        if root.is_symlink() or manifest_file.is_symlink():
            raise ValueError("Linked preparation directory or manifest")
        self.manifest_sha256 = digest(manifest_file.read_bytes())
        self.material = read_material(
            root, expected_manifest_sha256=self.manifest_sha256
        )
        self.root = root.resolve()
        self.manifest = self.material["manifest"]
        if self.manifest["rule_version"] != INPUT_VERSION:
            raise ValueError(f"Extraction requires a {INPUT_VERSION} material")
        self.document = self.material["document"]
        self.text = self.material["entry_tex"]
        mapping = self.material["source_map"] or {}
        self.segments = mapping.get("segments", [])
        self.starts = [item["out_char_start"] for item in self.segments]
        projection = self.material["source_projection"] or {}
        self.projections = (
            {row["path"]: row for row in projection.get("files", [])}
            if projection.get("verified")
            else {}
        )
        self.indices: dict[str, SourceIndex] = {}

    def _index(self, path):
        if path not in self.indices:
            folder = "projected-sources/" if path in self.projections else "sources/"
            name = folder + safe_path(path)
            target = self.root / name
            if any(
                p.is_symlink()
                for p in (target, *target.parents)
                if p.is_relative_to(self.root)
            ):
                raise ValueError("Linked preparation source")
            raw = target.read_bytes()
            if digest(raw) != self.manifest["artifacts"][name]:
                raise ValueError("Preparation source changed during extraction")
            self.indices[path] = SourceIndex(raw, "utf-8")
        return self.indices[path]

    def pieces(self, start, end):
        if not 0 <= start < end <= len(self.text):
            raise ValueError("Extraction entry range is out of bounds")
        offset = start
        for index in range(
            max(0, bisect_right(self.starts, start) - 1), len(self.segments)
        ):
            segment = self.segments[index]
            low = max(start, segment["out_char_start"])
            high = min(end, segment["out_char_end"])
            if low >= end:
                break
            if high <= low:
                continue
            if low != offset:
                raise ValueError("Extraction entry range has no continuous mapping")
            span = self._source_span(segment, low, high)
            yield low, high, span
            offset = high
        if offset != end:
            raise ValueError("Extraction entry range has no complete source mapping")

    def _source_span(self, segment, low, high):
        path = segment["path"]
        source = self._index(path)
        start = segment["char_start"] + low - segment["out_char_start"]
        end = start + high - low
        if (
            not 0 <= start < end <= len(source.text)
            or self.text[low:high] != source.text[start:end]
        ):
            raise ValueError("Extraction entry range does not copy prepared source")
        if record := self.projections.get(path):
            span = source.span(path, start, end, layer="projected")
            span["original_source"] = original_locator(
                span, record, {}, text=source.text
            )
            return span
        return source.span(path, start, end)

    def spans(self, start, end):
        return [span for _, _, span in self.pieces(start, end)]


def extract_source(source: PreparedSource) -> dict:
    """Build the unified handoff using prepared syntax and no provider."""
    manifest, document = source.manifest, source.document
    result = {
        "schema": SCHEMA,
        "rule_version": RULE_VERSION,
        "input": {
            "material_sha256": source.manifest_sha256,
            "package_sha256": manifest.get("package_sha256"),
            "source_tree_sha256": manifest["source_tree_sha256"],
            "entry_sha256": manifest["artifacts"]["entry.tex"],
            "source_map_sha256": manifest["artifacts"].get("source-map.json"),
            "entry": manifest["entry"],
            "preparation_version": manifest["rule_version"],
            "status": manifest["status"],
            "stages": manifest["stages"],
            "capabilities": manifest["preparation_capabilities"],
        },
        "source": {
            "files": manifest["sources"],
            "units": _units(source),
            "body_range": document["body_range"],
            **{
                name: document.get(name, [])
                for name in (
                    "outline",
                    "assets",
                    "labels",
                    "citations",
                    "cross_references",
                )
            },
            "bibliography": source.material["references"],
            "coverage": source.material["coverage"],
            "diagnostics": source.material["diagnostics"],
        },
        "semantic": {},
    }
    packaged_validator("prepared-extraction").validate(result)
    return result


def _kind(node, headings):
    name = node["name"]
    if node["id"] in headings:
        return "section"
    if node["kind"] == "math":
        return "formula"
    if node["kind"] == "macro" and name in METADATA | _CAPTIONS:
        return "caption" if name in _CAPTIONS else name
    if node["kind"] != "environment" or name in {"document", "thebibliography"}:
        return None
    name = name.removesuffix("*")
    if name in _STATEMENTS:
        return "statement"
    if name in {"abstract", "proof"}:
        return name
    return "table" if "rows" in node else _FLOATS.get(name, "environment")


def _unit(source, identifier, kind, name, bounds, data, *, spans=None):
    a, b = bounds
    return {
        "id": identifier,
        "kind": kind,
        "name": name,
        "entry_range": bounds,
        "latex": source.text[a:b],
        "data": data,
        "source_spans": source.spans(a, b) if spans is None else spans,
    }


def _node_units(source):
    headings = {row["node"]: row for row in source.document["outline"]}
    nodes = {row["id"]: row for row in source.document["nodes"]}
    for node in source.document["nodes"]:
        kind = _kind(node, headings)
        if kind is None or node["region"] == "bibliography":
            continue
        if node["region"] != "body" and kind not in METADATA:
            continue
        data = {"parent_node": node["parent"], "region": node["region"]}
        data.update({key: node[key] for key in ("arguments", "rows") if key in node})
        if kind == "section":
            data.update(headings[node["id"]])
        parent = nodes.get(node["parent"])
        bounds, spans = _unit_range(source.text, node, parent, kind, data)
        yield _unit(
            source,
            node["id"],
            kind,
            node["name"],
            bounds,
            data,
            spans=spans,
        )


def _unit_range(text, node, parent, kind, data):
    original = node["range"], node["source_spans"]
    if kind not in METADATA | {"caption"} or node.get("arguments"):
        return original
    start, end = node["range"]
    limit = parent["range"][1] if parent else len(text)
    args = _literal_arguments(text, end, node["name"])
    if not args or args[-1][1] > limit:
        data["argument_status"] = "unresolved"
        return original
    data["arguments"] = [text[a:b] for _, _, a, b in args]
    return [start, args[-1][1]], None


def _literal_arguments(text, end, name):
    """Recover only balanced literal arguments attached to a prepared macro."""
    cursor = end + (text[end : end + 1] == "*")
    args = []
    if name == "captionof":
        category = group(text, cursor)
        if category is None:
            return []
        args.append(category)
        cursor = category[1]
    if optional := group(text, cursor, "["):
        args.append(optional)
        cursor = optional[1]
    primary = group(text, cursor)
    return [*args, primary] if primary else []


def _units(source):
    units = list(_node_units(source))
    for row in source.document.get("reading_units", []):
        a, b = row["range"]
        if row["kind"] == "paragraph":
            units.append(
                _unit(source, f"reading:{a}:{b}", "paragraph", None, [a, b], {})
            )
    units.extend(_notation_units(source, units))
    return sorted(units, key=lambda row: (*row["entry_range"], row["id"]))


def excluded_ranges(document):
    """Ranges to omit from literal candidate detection and semantic evidence."""
    marked = [
        tuple(r)
        for key in ("inactive_ranges", "conditional_ranges")
        for r in document.get(key, [])
    ]
    marked.extend(
        tuple(n["range"])
        for n in document["nodes"]
        if n["kind"] in {"comment", "opaque"} or n["region"] == "bibliography"
    )
    merged: list[tuple[int, int]] = []
    for a, b in sorted(marked):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def _notation_units(source, units):
    blocked = excluded_ranges(source.document)
    starts = [a for a, _ in blocked]
    seen = set()
    for unit in units:
        if unit["kind"] not in {"paragraph", "formula", "statement", "table"}:
            continue
        text = unit["latex"]
        if not any(token in text for token in ("[", "((", r"\llbracket")):
            continue
        for match in notation_matches(text):
            a = unit["entry_range"][0] + match.start()
            b = unit["entry_range"][0] + match.end()
            index = bisect_right(starts, b - 1) - 1
            if (a, b) in seen or (index >= 0 and blocked[index][1] > a):
                continue
            seen.add((a, b))
            yield _unit(
                source,
                f"notation:{a}:{b}",
                "code_parameters_mention",
                None,
                [a, b],
                {"status": "candidate", "notation": match.lastgroup},
            )
