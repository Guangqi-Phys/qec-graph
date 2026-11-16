#!/usr/bin/env python3
"""Replay a pinned public source manifest through compile-first preparation (zero AI)."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qecgraph.preparation.contract import read_material  # noqa: E402
from qecgraph.source.normalization import load_for_preparation  # noqa: E402
from qecgraph.source.prepare import select_entry  # noqa: E402


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
        row = {"paper": paper, "package_sha256": actual, "entry_selection": "automatic"}
        try:
            tree, _ = load_for_preparation(package, repair_legacy_tar=True)
            try:
                entry = select_entry(tree)
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
            row["exit"] = result.returncode
            if (output / "manifest.json").is_file():
                material = read_material(output)
                row.update(
                    status=material["manifest"]["status"],
                    stages=material["manifest"]["stages"],
                    source_fidelity=material["validation"]["source_fidelity"],
                    nodes=material["validation"]["nodes"],
                    reasons=json.loads((output / "coverage.json").read_bytes())[
                        "reasons"
                    ],
                )
            else:
                row.update(
                    status="failed", error=result.stderr.decode(errors="replace")[-800:]
                )
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
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
        "counts": {
            "papers": len(rows),
            "ready": sum(r["status"] == "ready" for r in rows),
            "compiled": sum(
                r.get("stages", {}).get("compile") == "complete" for r in rows
            ),
            "partial": sum(r["status"] == "partial" for r in rows),
            "failed": sum(r["status"] == "failed" for r in rows),
            "source_fidelity": sum(
                r.get("source_fidelity", False) and r.get("nodes", 0) > 0 for r in rows
            ),
        },
    }
    if args.cases:
        report["syntax_probes"] = check_cases(
            args.out, json.loads(args.cases.read_bytes())["cases"]
        )
    (args.out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["counts"], indent=2))
    return 0


def check_cases(root, cases):
    results = []
    for case in cases:
        folder = root / case["paper"].replace("/", "_")
        material = read_material(folder)
        raw = (folder / "sources" / case["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != case["source_sha256"]:
            raise ValueError("Syntax probe source hash mismatch")
        original = raw.decode()
        positions = {
            match.start() for match in re.finditer(re.escape(case["anchor"]), original)
        }
        matches = [
            n
            for n in material["document"]["nodes"]
            if n["kind"] == case["kind"]
            and n["name"] == case["name"]
            and any(
                s["path"] == case["file"] and s["chars"][0] in positions
                for s in n["source_spans"]
            )
        ]
        results.append(
            {"paper": case["paper"], "anchor": case["anchor"], "passed": bool(matches)}
        )
    return {
        "scope": "Mechanical syntax/source checks, not scientific accuracy or human acceptance",
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "cases": results,
    }


if __name__ == "__main__":
    raise SystemExit(main())
