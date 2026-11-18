#!/usr/bin/env python3
"""Replay a pinned public source manifest through compile-first preparation (zero AI)."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qecgraph.preparation.contract import read_material  # noqa: E402
from qecgraph.preparation.acceptance import (  # noqa: E402
    counts,
    check_cases,
    replay_material_root,
    replay_metadata,
)
from qecgraph.source.normalization import load_for_preparation  # noqa: E402
from qecgraph.preparation.entries import select_build_entry  # noqa: E402


def _record_attempt(output, result, row):
    row["exit"] = result.returncode
    if result.returncode not in {0, 2}:
        row.update(
            status="failed",
            error=result.stderr.decode(errors="replace")[-800:]
            or f"Exit {result.returncode}",
        )
        return
    receipt = json.loads(result.stdout)
    status = "ready" if result.returncode == 0 else "partial"
    if receipt["status"] != status or not receipt["manifest_sha256"]:
        raise ValueError(
            "Preparation receipt disagrees with its exit status or has no manifest hash"
        )
    location = Path(receipt["out"])
    folder = replay_material_root(
        output.parent, {**row, "status": status, "material": location.name}
    )
    if folder.absolute() != location.absolute():
        raise ValueError(
            "Preparation returned a material path outside this replay attempt"
        )
    material = read_material(
        folder, expected_manifest_sha256=receipt["manifest_sha256"]
    )
    manifest = material["manifest"]
    if (
        manifest["status"] != status
        or manifest["package_sha256"] != row["package_sha256"]
    ):
        raise ValueError("Published attempt does not match this input and exit status")
    row.update(
        material=location.name,
        material_manifest_sha256=receipt["manifest_sha256"],
        status=status,
        stages=manifest["stages"],
        source_fidelity=material["validation"]["source_fidelity"],
        nodes=material["validation"]["nodes"],
        reasons=material["coverage"]["reasons"],
    )
    if normalization := material["normalization"]:
        row["normalization"] = {
            k: normalization.get(k)
            for k in (
                "complete",
                "native_compile",
                "syntax_parse",
                "pdf_text",
                "transformations",
            )
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--entries",
        type=Path,
        help="Optional explicit entry hints: paper ID -> original path",
    )
    parser.add_argument("--support-dir", type=Path, action="append", default=[])
    parser.add_argument("--papers", nargs="*")
    parser.add_argument(
        "--cases", type=Path, help="Optional frozen original-source syntax probes"
    )
    parser.add_argument("--jobs", type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    metadata = replay_metadata([sys.executable, *sys.argv], args.entries, args.cases)
    manifest = json.loads(args.manifest.read_bytes())
    hints = json.loads(args.entries.read_bytes()) if args.entries else {}
    args.out.mkdir(parents=True, exist_ok=True)

    def one(sample):
        paper = sample["arxiv_id"]
        package = args.manifest.parent / sample["package"]
        actual = hashlib.sha256(package.read_bytes()).hexdigest()
        if actual != sample["sha256"]:
            raise ValueError("Corpus package hash mismatch: " + paper)
        output = args.out / paper.replace("/", "_")
        row = {
            "paper": paper,
            "package_sha256": actual,
            "entry_selection": "automatic",
            "material": None,
        }
        try:
            tree, _ = load_for_preparation(package, repair_legacy_tar=True)
            try:
                entry = select_build_entry(tree)
            except ValueError:
                entry = hints.get(paper)
                row["entry_selection"] = "configured" if entry else "unresolved"
            command = [
                sys.executable,
                str(ROOT / "tools/prepare_compiled.py"),
                str(package),
                "--out",
                str(output),
            ]
            if entry:
                command += ["--entry", entry]
            for folder in args.support_dir:
                command += ["--support-dir", str(folder)]
            result = subprocess.run(command, capture_output=True, timeout=600)
            (args.out / (output.name + ".log")).write_bytes(
                result.stdout + result.stderr
            )
            _record_attempt(output, result, row)
        except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
            row.update(status="failed", error=str(exc)[:800])
        print(paper, row["status"], row.get("stages", {}), flush=True)
        return row

    samples = [
        s
        for s in manifest["samples"]
        if not args.papers or s["arxiv_id"] in args.papers
    ]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(one, samples))
    report = {
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "model_calls": 0,
        "rows": rows,
        "counts": counts(rows),
        "run_metadata": metadata,
    }
    if args.cases:
        selected = {row["paper"] for row in rows}
        cases = [
            case
            for case in json.loads(args.cases.read_bytes())["cases"]
            if case["paper"] in selected
        ]
        report["syntax_probes"] = check_cases(args.out, cases, rows=rows)
    (args.out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
