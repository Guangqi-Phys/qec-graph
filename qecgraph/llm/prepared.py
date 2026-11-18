"""Use the existing proposal skills with verified, active v20 source evidence."""

from bisect import bisect_right
from dataclasses import dataclass
import re

from jsonschema import Draft202012Validator

from ..prepared_extraction import METADATA, PreparedSource, excluded_ranges
from .client import BudgetExceeded, LLMClient
from .errors import LLMError
from .extract import (
    _EXTRACTION_SKILLS as SKILLS,
    _LINE_REF,
    extract,
    validate_extraction,
    validate_source_refs,
)
from .normalize import NormalizedSource
from .skills import load_skill


_ENTRY = "entry.tex"


@dataclass(frozen=True)
class _Evidence:
    view: NormalizedSource
    bounds: tuple[int, int]
    record: dict

    @property
    def ranges(self):
        return {_ENTRY: self.bounds}


def _section_body(result, section):
    start, end = result["source"]["body_range"]
    if section is None:
        return start, end
    headings = [row for row in result["source"]["units"] if row["kind"] == "section"]
    for index, row in enumerate(headings):
        if row["id"] != section:
            continue
        level = row["data"]["level"]
        stop = next(
            (
                h["entry_range"][0]
                for h in headings[index + 1 :]
                if h["data"]["level"] <= level
            ),
            end,
        )
        return row["entry_range"][0], stop
    raise ValueError("Unknown prepared section identifier")


def _selected(result, section):
    a, b = _section_body(result, section)
    if a is None or b is None or a >= b:
        return []
    metadata = [
        tuple(row["entry_range"])
        for row in result["source"]["units"]
        if row["kind"] in METADATA
        and row["entry_range"][1] <= a
        and row["data"].get("argument_status") != "unresolved"
    ]
    merged = []
    for start, end in sorted([*metadata, (a, b)]):
        if merged and merged[-1][1] >= start:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _active_parts(ranges, blocked):
    ends = [b for _, b in blocked]
    for start, end in ranges:
        for index in range(bisect_right(ends, start), len(blocked)):
            lo, hi = blocked[index]
            if lo >= end:
                break
            if start < lo:
                yield start, lo
            start = hi
        if start < end:
            yield start, end


def _evidence(source, result, section):
    allowed = [
        (a, b, span)
        for start, end in _active_parts(
            _selected(result, section), excluded_ranges(source.document)
        )
        for a, b, span in source.pieces(start, end)
        if span["layer"] == "original"
    ]
    if not any(source.text[a:b].strip() for a, b, _ in allowed):
        return None
    view = _masked_view(source, allowed)
    bounds = allowed[0][0], allowed[-1][1]
    return _Evidence(
        view,
        bounds,
        {
            "entry_range": list(bounds),
            "copy_ranges": [[a, b] for a, b, _ in allowed],
            "source_spans": [span for _, _, span in allowed],
            "entry_sha256": result["input"]["entry_sha256"],
        },
    )


def _masked_view(source, allowed):
    """Retain entry character and line coordinates while hiding excluded text."""
    chunks, segments = [], []
    cursor = offset = 0
    for start, end, span in allowed:
        gap = re.sub(r"[^\n]", " ", source.text[cursor:start]).encode()
        original = source.text[start:end].encode()
        chunks.extend((gap, original))
        offset += len(gap)
        segments.append(
            {
                "normalized": {
                    "byte_start": offset,
                    "byte_end": offset + len(original),
                },
                "origin": {
                    "path": span["path"],
                    "byte_start": span["bytes"][0],
                    "byte_end": span["bytes"][1],
                },
            }
        )
        offset += len(original)
        cursor = end
    return NormalizedSource(
        source.manifest["source_tree_sha256"],
        b"".join(chunks),
        {"entry": _ENTRY},
        tuple(segments),
    )


def run_semantics(
    source: PreparedSource, result, client: LLMClient, skills, *, section=None
):
    """Run only explicitly selected semantic jobs, with the usual upload permission."""
    names = tuple(dict.fromkeys(skills))
    if not names or set(names) - SKILLS:
        raise ValueError("Select one or more prepared extraction skills")
    if not (
        client.config.enabled
        and client.config.allow_source_upload
        and client.config.extract_proposals
    ):
        raise ValueError(
            "Semantic extraction requires enabled AI, proposals and source upload"
        )
    evidence = _evidence(source, result, section)
    return {
        skill: _run_task(source, evidence, client, skill, section) for skill in names
    }


def _run_task(source, evidence, client, skill, section):
    if evidence is None:
        return {
            "status": "no_evidence",
            "section": section,
            "error": "No active original source is available in the selected reading scope",
        }
    common = {"section": section, "evidence": evidence.record}
    try:
        output = extract(
            evidence.view,
            client,
            skill,
            projection_path=_ENTRY,
            source_ranges=evidence.ranges,
        )
    except BudgetExceeded:
        return {
            "status": "budget_exceeded",
            **common,
            "error": "The selected reading scope exceeds the configured AI budget",
        }
    except LLMError as exc:
        return {
            "status": "failed",
            **common,
            "error": f"Semantic extraction did not produce a valid proposal ({type(exc).__name__})",
        }
    return {
        "status": "proposed",
        **common,
        "proposal": output.proposal,
        "references": _reference_locators(source, evidence, output.data),
    }


def _source_refs(value):
    if isinstance(value, dict):
        yield from value.get("source_refs", [])
        for key, child in value.items():
            if key != "source_refs":
                yield from _source_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _source_refs(child)


def _reference_locators(source, evidence, data):
    refs = sorted(set(_source_refs(data)))
    offsets = [0, *(m.end() for m in re.finditer(r"\n", source.text)), len(source.text)]
    return {ref: _reference_spans(source, evidence, offsets, ref) for ref in refs}


def _reference_spans(source, evidence, offsets, reference):
    match = _LINE_REF.fullmatch(reference)
    if match is None or match[1] != _ENTRY:
        raise ValueError("Unrecognized prepared evidence reference")
    start, end = offsets[int(match[2]) - 1], offsets[int(match[3] or match[2])]
    return [
        span
        for lo, hi in evidence.record["copy_ranges"]
        if max(start, lo) < min(end, hi)
        for span in source.spans(max(start, lo), min(end, hi))
    ]


def verify_semantics(source: PreparedSource, result):
    """Recompute evidence scopes and validate accepted proposals offline."""
    views = {
        section: _evidence(source, result, section)
        for section in {task["section"] for task in result["semantic"].values()}
    }
    for skill, task in result["semantic"].items():
        evidence = views[task["section"]]
        if task.get("evidence") != (evidence.record if evidence else None):
            raise ValueError("Saved semantic evidence differs from the prepared source")
        if task["status"] == "proposed":
            if evidence is None:
                raise ValueError("Saved proposal has no active original evidence")
            _verify_proposal(source, evidence, skill, task)
        elif (task["status"] == "no_evidence") != (evidence is None):
            raise ValueError(
                "Saved semantic readiness differs from the prepared source"
            )


def _verify_proposal(source, evidence, name, task):
    skill = load_skill(name)
    proposal = task["proposal"]
    identity = {
        "skill": name,
        "projection_path": _ENTRY,
        "source_tree_hash": source.manifest["source_tree_sha256"],
        "normalization_id": evidence.view.sha256,
        "evidence_sources": [{"path": _ENTRY, "sha256": evidence.view.sha256}],
    }
    if (
        any(proposal.get(key) != value for key, value in identity.items())
        or proposal.get("provenance", {}).get("skill_version") != skill.version
    ):
        raise ValueError(
            "Saved proposal differs from its skill or prepared evidence binding"
        )
    data = {
        key: proposal[key]
        for key in ("items", "unresolved", "paper")
        if key in proposal
    }
    Draft202012Validator(skill.schema).validate(data)
    validate_extraction(name, data, skill_version=skill.version)
    validate_source_refs(
        evidence.view, _ENTRY, name, data, source_ranges=evidence.ranges
    )
    if task["references"] != _reference_locators(source, evidence, data):
        raise ValueError(
            "Saved proposal citations differ from their original source locations"
        )
