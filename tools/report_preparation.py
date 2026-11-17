#!/usr/bin/env python3
"""Generate or check preparation acceptance from verified frozen-corpus replay evidence."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qecgraph.preparation.acceptance import generate_report  # noqa: E402
from qecgraph.preparation.contract import json_bytes, digest, safe_path  # noqa: E402
from qecgraph.core.transactions import atomic_bytes  # noqa: E402


def baseline_at(revision, path):
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", revision) is None:
        raise ValueError("Baseline revision must be an explicit Git commit hash")
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", revision + "^{commit}"], cwd=ROOT, text=True
    ).strip()
    raw = subprocess.check_output(
        ["git", "show", commit + ":" + safe_path(path)], cwd=ROOT
    )
    baseline = json.loads(raw)
    baseline["code_revision"] = commit
    return baseline, {"commit": commit, "path": path, "sha256": digest(raw)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline-revision")
    parser.add_argument(
        "--baseline-report", default="validation/preparation_acceptance.json"
    )
    parser.add_argument("--machine-evaluation", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the saved report without modifying it or compiling",
    )
    args = parser.parse_args(argv)
    try:
        baseline, provenance = (
            baseline_at(args.baseline_revision, args.baseline_report)
            if args.baseline_revision
            else (None, None)
        )
        report = generate_report(
            args.manifest, args.replay, cases_path=args.cases, baseline=baseline
        )
        report["generator"] = {
            "command": "tools/report_preparation.py",
            "baseline": provenance,
        }
        report["machine_evaluation"] = _machine_evaluation(args.machine_evaluation)
        data = json_bytes(report)
        if args.check:
            if args.out.read_bytes() != data:
                raise ValueError(
                    "Saved acceptance report differs from verified replay evidence"
                )
        else:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            atomic_bytes(args.out, data)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"out": str(args.out), "counts": report["counts"], "checked": args.check},
            indent=2,
        )
    )
    return 0


def _machine_evaluation(path):
    if path is None:
        return {"accepted": False, "status": "not_run"}
    raw = path.read_bytes()
    return {
        "evidence_path": str(path),
        "evidence_sha256": digest(raw),
        "result": json.loads(raw),
    }


if __name__ == "__main__":
    raise SystemExit(main())
