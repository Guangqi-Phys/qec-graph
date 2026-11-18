#!/usr/bin/env python3
"""Compare stable prepared material across two retained corpus replays without TeX."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qecgraph.preparation.artifacts import digest, json_bytes  # noqa: E402
from qecgraph.preparation.contract import read_material  # noqa: E402
from qecgraph.preparation.acceptance import replay_material_root  # noqa: E402
from qecgraph.core.transactions import atomic_bytes  # noqa: E402

STABLE_ARTIFACTS = {
    "original.package",
    "entry.tex",
    "normalized.tex",
    "normalized-map.json",
    "source-map.json",
    "references.json",
    "coverage.json",
    "diagnostics.json",
}
MANIFEST_FIELDS = (
    "status",
    "rule_version",
    "entry",
    "source_tree_sha256",
    "sources",
    "package_sha256",
    "stages",
    "model_calls",
    "preparation_capabilities",
    "capabilities",
    "warnings",
)


def material_signature(root, expected_manifest_sha256=None):
    material = read_material(root, expected_manifest_sha256=expected_manifest_sha256)
    manifest = material["manifest"]
    document = {
        key: value
        for key, value in material["document"].items()
        if key not in {"build_view_sha256", "source_projection_sha256"}
    }
    normalized = material["normalization"] or {}
    return {
        "manifest": {key: manifest.get(key) for key in MANIFEST_FIELDS},
        "stable_artifacts": {
            path: value
            for path, value in manifest["artifacts"].items()
            if path in STABLE_ARTIFACTS
            or path.startswith(("sources/", "projected-sources/"))
        },
        "content": digest(json_bytes(document)),
        "normalization": {
            key: normalized.get(key)
            for key in (
                "complete",
                "native_compile",
                "syntax_parse",
                "pdf_text",
                "transformations",
            )
        },
        "validation": material["validation"],
    }


def _rows(root):
    report = json.loads((root / "results.json").read_bytes())
    rows = {row["paper"]: row for row in report["rows"]}
    if len(rows) != len(report["rows"]) or report.get("model_calls") != 0:
        raise ValueError(
            "Replay comparison needs unique input rows and zero model calls"
        )
    return report["manifest_sha256"], rows


def compare_replays(baseline, current):
    before_hash, before = _rows(baseline)
    after_hash, after = _rows(current)
    if before_hash != after_hash or before.keys() != after.keys():
        raise ValueError("Replay comparison requires the same frozen corpus")
    rows = [
        _compare_paper(paper, baseline, current, before[paper], after[paper])
        for paper in sorted(before)
    ]
    return {
        "schema": "qecgraph.preparation_comparison/1",
        "manifest_sha256": before_hash,
        "scope": "Stable material bytes, syntax, references, source coordinates and preparation outcomes. Volatile native logs/PDF bytes and verified build/projection report hashes are excluded. No scientific acceptance.",
        "baseline": str(baseline),
        "current": str(current),
        "inputs": len(rows),
        "matched": sum(not row["differences"] for row in rows),
        "rows": rows,
    }


def _compare_paper(paper, baseline, current, before, after):
    old_path = replay_material_root(baseline, before)
    new_path = replay_material_root(current, after)
    if before["status"] == "failed" and after["status"] == "failed":
        if any(
            root is not None and (root / "manifest.json").exists()
            for root in (old_path, new_path)
        ):
            raise ValueError("Failed replay row conflicts with retained material")
        return {
            "paper": paper,
            "differences": [],
            "scope": "Unprepared failure outcome only",
        }
    if "failed" in {before["status"], after["status"]}:
        return {"paper": paper, "differences": ["preparation_outcome"]}
    old = material_signature(old_path, before.get("material_manifest_sha256"))
    new = material_signature(new_path, after.get("material_manifest_sha256"))
    return {"paper": paper, "differences": [key for key in old if old[key] != new[key]]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = compare_replays(args.baseline, args.current)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        atomic_bytes(args.out, json_bytes(report))
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "inputs": report["inputs"],
                "matched": report["matched"],
                "out": str(args.out),
            }
        )
    )
    return 0 if report["inputs"] == report["matched"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
