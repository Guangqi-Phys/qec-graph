"""Generate mechanical acceptance evidence from a pinned replay and verified materials."""

from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import subprocess

from . import PREPARATION_VERSION
from .contract import digest, read_material, safe_path

ROOT = Path(__file__).resolve().parents[2]


def execution_sources():
    paths = [
        *ROOT.joinpath("qecgraph").rglob("*.py"),
        ROOT / "tools/prepare_compiled.py",
        ROOT / "tools/reproduce_preparation.py",
    ]
    return {
        p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in sorted(paths)
    }


def replay_metadata(argv, entries=None, cases=None):
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return {
        "argv": argv,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "code_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "rule_version": PREPARATION_VERSION,
        "execution_sources": execution_sources(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "entries_sha256": digest(entries.read_bytes()) if entries else None,
        "cases_sha256": digest(cases.read_bytes()) if cases else None,
    }


def counts(rows):
    return {
        "papers": len(rows),
        "ready": sum(r["status"] == "ready" for r in rows),
        "partial": sum(r["status"] == "partial" for r in rows),
        "failed": sum(r["status"] == "failed" for r in rows),
        "compiled": sum(r.get("stages", {}).get("compile") == "complete" for r in rows),
        "source_fidelity": sum(
            bool(r.get("source_fidelity")) and r.get("nodes", 0) > 0 for r in rows
        ),
        "normalized_recompiled": sum(
            r.get("normalization", {}).get("native_compile") == "complete" for r in rows
        ),
        "normalized_text_equal": sum(
            r.get("normalization", {}).get("pdf_text") == "equal" for r in rows
        ),
    }


def check_cases(root, cases):
    results, cache = [], {}
    for case in cases:
        paper = case["paper"]
        folder = root / safe_path(paper.replace("/", "_"))
        if paper not in cache:
            cache[paper] = read_material(folder)
        raw = (folder / "sources" / safe_path(case["file"])).read_bytes()
        if digest(raw) != case["source_sha256"]:
            raise ValueError("Syntax probe source hash mismatch")
        positions = {
            m.start() for m in re.finditer(re.escape(case["anchor"]), raw.decode())
        }
        matches = [
            n
            for n in cache[paper]["document"]["nodes"]
            if n["kind"] == case["kind"]
            and n["name"] == case["name"]
            and any(
                s["path"] == case["file"] and s["chars"][0] in positions
                for s in n["source_spans"]
            )
        ]
        results.append(
            {"paper": paper, "anchor": case["anchor"], "passed": bool(matches)}
        )
    return {
        "scope": "Mechanical syntax/source checks, not scientific accuracy or human acceptance",
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "cases": results,
    }


def generate_report(manifest_path, replay, *, cases_path=None, baseline=None):
    raw = manifest_path.read_bytes()
    corpus, results = (
        json.loads(raw),
        json.loads((replay / "results.json").read_bytes()),
    )
    _check_replay(results, raw, corpus, cases_path)
    rows = [
        _verified_row(replay, row, sample)
        for row, sample in _samples(results, corpus, manifest_path)
    ]
    if counts(rows) != results["counts"]:
        raise ValueError(
            "Replay counts do not match independently verified material rows"
        )
    probes = _verify_probes(results, replay, cases_path)
    metadata = results["run_metadata"]
    report = {
        "schema": "qecgraph.preparation_acceptance/1",
        "status": "Mechanical preparation evidence; scientific usability is not accepted",
        "date": metadata["started_at"],
        "code_revision": metadata["code_revision"],
        "rule_version": metadata["rule_version"],
        "scope": "Offline preparation only; zero model calls, no scientific extraction or original-database writes",
        "input": {
            "manifest": str(manifest_path),
            "manifest_sha256": digest(raw),
            "tex_inputs": sum(s.get("format") != "pdf" for s in corpus["samples"]),
            "negative_pdf_inputs": sum(
                s.get("format") == "pdf" for s in corpus["samples"]
            ),
        },
        "counts": counts(rows),
        "bibliography_complete": sum(
            r.get("stages", {}).get("references") == "complete" for r in rows
        ),
        "normalization_complete": sum(
            bool(r.get("normalization", {}).get("complete", False)) for r in rows
        ),
        "normalization_files": sum(r.get("normalization_file", False) for r in rows),
        "original_bundles_validated": sum(r["status"] != "failed" for r in rows),
        "nonempty_syntax_bundles_validated": counts(rows)["source_fidelity"],
        "model_calls": 0,
        "syntax_probes": probes,
        "rows": rows,
        "ready_papers": sorted(r["paper"] for r in rows if r["status"] == "ready"),
        "remaining_partial": [r for r in rows if r["status"] == "partial"],
        "replay": {
            "root": str(replay),
            "results_sha256": digest((replay / "results.json").read_bytes()),
            **metadata,
        },
        "criteria": "Native compilation, complete supported source syntax and reference bindings, exact source mapping, and normalized syntax/recompilation. Observed guards additionally require matching instrumented PDF text and validated native log evidence. Ready is not portability or scientific correctness.",
        "scientific_acceptance": {
            "accepted": False,
            "reason": "No independent scientific gold or extraction is evaluated by this preparation report.",
        },
    }
    if baseline is not None:
        report["comparison"] = _comparison(baseline, report)
    return report


def _check_replay(results, raw, corpus, cases_path):
    if results["manifest_sha256"] != digest(raw) or results.get("model_calls") != 0:
        raise ValueError("Replay corpus identity or zero-model boundary mismatch")
    metadata = results.get("run_metadata", {})
    if (
        metadata.get("rule_version") != PREPARATION_VERSION
        or metadata.get("execution_sources") != execution_sources()
    ):
        raise ValueError(
            "Replay code snapshot differs from the current preparation implementation"
        )
    actual_cases = digest(cases_path.read_bytes()) if cases_path else None
    if metadata.get("cases_sha256") != actual_cases:
        raise ValueError("Replay syntax-probe configuration identity mismatch")
    ids = [s["arxiv_id"] for s in corpus["samples"]]
    papers = [r["paper"] for r in results["rows"]]
    if (
        len(set(ids)) != len(ids)
        or len(set(papers)) != len(papers)
        or set(ids) != set(papers)
    ):
        raise ValueError(
            "Acceptance requires one replay row for every frozen corpus input"
        )


def _samples(results, corpus, manifest_path):
    samples = {s["arxiv_id"]: s for s in corpus["samples"]}
    for row in results["rows"]:
        sample = samples[row["paper"]]
        package = manifest_path.parent / safe_path(sample["package"])
        if package.is_symlink() or not package.resolve().is_relative_to(
            manifest_path.parent.resolve()
        ):
            raise ValueError("Corpus package escapes the frozen manifest directory")
        if digest(package.read_bytes()) != sample["sha256"]:
            raise ValueError("Corpus package bytes changed since the frozen manifest")
        if row["package_sha256"] != sample["sha256"]:
            raise ValueError("Replay package identity differs from corpus manifest")
        yield row, sample


def _verified_row(replay, row, sample):
    root = replay / safe_path(row["paper"].replace("/", "_"))
    if row["status"] == "failed":
        if (root / "manifest.json").exists() or not row.get("error"):
            raise ValueError("Failed replay row conflicts with published material")
        return {**row, "expected_negative": sample.get("format") == "pdf"}
    material = read_material(root)
    manifest, check = material["manifest"], material["validation"]
    _match_row(row, material)
    if (
        manifest["package_sha256"] != sample["sha256"]
        or manifest["rule_version"] != PREPARATION_VERSION
        or manifest["model_calls"] != 0
    ):
        raise ValueError(
            "Material package, rule version or model-call boundary mismatch"
        )
    document = material["document"]
    normalized = material["normalization"] or {}
    build = _listed_json(root, manifest, "build.json", {})
    version_path = "build/logs/engine-version.log"
    version = (
        (root / version_path).read_text().splitlines()[0]
        if version_path in manifest["artifacts"]
        else None
    )
    diagnostics = _listed_json(root, manifest, "diagnostics.json", [])
    view = _listed_json(root, manifest, "build-view.json", {})
    return {
        **row,
        "engine": build.get("engine"),
        "engine_version": version,
        "source_tree_sha256": manifest["source_tree_sha256"],
        "entry": manifest["entry"],
        "source_fidelity": check["source_fidelity"],
        "nodes": check["nodes"],
        "warnings": manifest.get("warnings", []),
        "diagnostic_codes": sorted({d["code"] for d in diagnostics}),
        "normalization_file": bool(material["normalized_map"]),
        "normalization": {
            k: normalized.get(k)
            for k in (
                "complete",
                "native_compile",
                "syntax_parse",
                "pdf_text",
                "transformations",
            )
        },
        "unresolved_cross_references": sorted(
            {
                t["key"]
                for r in document.get("cross_references", [])
                for t in r["targets"]
                if t["status"] != "resolved"
            }
        ),
        "unmapped_conditions": [
            v for v in document.get("conditional_views", []) if v["kind"] == "unmapped"
        ],
        "native_guard_view": {
            "verified": view.get("verified", False),
            "observed_guards": sum(
                g.get("status") == "observed" for g in view.get("guards", [])
            ),
        },
        "environment_declaration_count": sum(
            d["supports_label_option"]
            for d in document.get("environment_label_declarations", [])
        ),
    }


def _match_row(row, material):
    actual = {
        "status": material["manifest"]["status"],
        "stages": material["manifest"]["stages"],
        "source_fidelity": material["validation"]["source_fidelity"],
        "nodes": material["validation"]["nodes"],
        "reasons": material["coverage"]["reasons"],
    }
    if any(row.get(k) != value for k, value in actual.items()):
        raise ValueError(
            "Replay row does not match the independently verified material"
        )
    normalized = material["normalization"] or {}
    if row.get("normalization", {}) != {
        k: normalized.get(k) for k in row.get("normalization", {})
    }:
        raise ValueError("Replay normalization result differs from material evidence")


def _listed_json(root, manifest, name, default):
    return (
        json.loads((root / name).read_bytes())
        if name in manifest["artifacts"]
        else default
    )


def _verify_probes(results, replay, cases_path):
    if cases_path is None:
        if "syntax_probes" in results:
            raise ValueError("Replay probes have no frozen configuration")
        return None
    probes = check_cases(replay, json.loads(cases_path.read_bytes())["cases"])
    if probes != results.get("syntax_probes"):
        raise ValueError("Replay probe claims differ from independent source checks")
    return probes


def _comparison(baseline, report):
    if baseline["input"]["manifest_sha256"] != report["input"]["manifest_sha256"]:
        raise ValueError("Baseline and current corpus identities differ")
    if {r["paper"] for r in baseline["rows"]} != {r["paper"] for r in report["rows"]}:
        raise ValueError("Baseline and current replay input sets differ")
    before = {r["paper"] for r in baseline["rows"] if r["status"] == "ready"}
    after = set(report["ready_papers"])
    return {
        "baseline_rule_version": baseline["rule_version"],
        "baseline_code_revision": baseline["code_revision"],
        "before": baseline["counts"],
        "after": report["counts"],
        "newly_ready": sorted(after - before),
        "ready_regressions": sorted(before - after),
        "gate_change_note": "Current preparation additionally requires declared environment syntax, verified native guard evidence, and recorder-bound include expansion. These are mechanical coverage counts, not scientific extraction quality.",
    }
