#!/usr/bin/env python3
"""Reproduce the shipped prototype without executing TeX, Lean, or Docker.

Run from any directory after installing the package/dependency:
    python tools/reproduce.py --out build/reproduce

Outputs are generated reports and managed stores. The knowledge starter's
verify command is read-only; its source records and archived evidence remain
unchanged. JSON Schema checks are explicit optional checks, never assumed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="build/reproduce", help="Dedicated generated-output directory")
    args = parser.parse_args(argv)
    out = Path(args.out).expanduser().resolve()
    marker = out / ".qecgraph-reproduce.json"
    if out.exists() and (not out.is_dir() or (any(out.iterdir()) and not marker.exists())):
        parser.error("--out must be empty or a previously managed reproduce directory")
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")) != {"format": "qecgraph.reproduce.v1"}:
        parser.error("Incompatible reproduce output marker")
    out.mkdir(parents=True, exist_ok=True)
    write_json(marker, {"format": "qecgraph.reproduce.v1"})
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    report = {
        "format": "qecgraph.reproduction.v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "sqlite": sqlite3.sqlite_version},
        "code_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted((ROOT / "qecgraph").rglob("*")) if p.suffix in {'.py', '.json'}},
        "steps": [],
        "not_executed": ["Lean build / declaration export / axiom audit", "Docker build",
                         "External CodeGraph checkout or code reuse", "MCP client connection",
                         "Tests on a user-supplied real paper"],
    }

    def run(name: str, arguments: list[str], json_output=True) -> dict:
        command = [sys.executable, *arguments]
        proc = subprocess.run(command, cwd=ROOT, env=environment, text=True,
                              encoding="utf-8", capture_output=True, timeout=180)
        (out / f"{name}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
        (out / f"{name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
        step = {"name": name, "command": command, "exit_code": proc.returncode,
                "stdout": f"{name}.stdout.txt", "stderr": f"{name}.stderr.txt"}
        report["steps"].append(step)
        if proc.returncode != 0:
            raise RuntimeError(f"{name} failed with exit code {proc.returncode}; see saved logs")
        if not json_output:
            count = re.search(r"Ran (\d+) tests?", proc.stderr)
            step["test_count"] = int(count.group(1)) if count else None
            return step
        value = json.loads(proc.stdout)
        step["result"] = value
        return value

    try:
        report["runtime"]["pylatexenc"] = importlib.metadata.version("pylatexenc")
        if report["runtime"]["pylatexenc"] != "2.10":
            raise RuntimeError("This prototype requires pylatexenc==2.10")
        with sqlite3.connect(":memory:") as con:
            con.execute("CREATE VIRTUAL TABLE ft USING fts5(body)")
        report["runtime"]["fts5_available"] = True
        has_schema = importlib.util.find_spec("jsonschema") is not None
        report["runtime"]["jsonschema"] = importlib.metadata.version("jsonschema") if has_schema else None

        run("unit_tests", ["-m", "unittest", "discover", "-s", "tests", "-v"], json_output=False)
        base = ["examples/paper/main.tex", "--project-id", "qec-demo"]
        split_store, graph_store, catalog_store = (out / name for name in ("split", "graph", "catalog"))
        split = run("split", ["-m", "qecgraph", "split", *base, "--out", str(split_store)])
        run("split_validate", ["-m", "qecgraph", "validate", "--store", str(split_store)])
        graph = run("graph_ingest", ["-m", "qecgraph", "ingest", *base, "--out", str(graph_store),
                                    "--annotations", "examples/annotations.example.json"])
        run("graph_validate", ["-m", "qecgraph", "validate", "--store", str(graph_store)])
        shown = run("show", ["-m", "qecgraph", "show", "thm:hgp-css", "--store", str(graph_store)])
        if shown["node"]["kind"] != "theorem" or "thm:hgp-css" not in shown["node"]["labels"]:
            raise RuntimeError("The exact label query did not resolve to the expected theorem")
        hits = run("search", ["-m", "qecgraph", "search", "HGP", "--store", str(graph_store)])
        context = run("context", ["-m", "qecgraph", "context", "thm:hgp-length", "--store", str(graph_store)])
        deps = run("dependencies", ["-m", "qecgraph", "deps", "thm:hgp-css", "--store", str(graph_store)])
        impact = run("impact", ["-m", "qecgraph", "impact", "def:gf2", "--store", str(graph_store)])
        if not hits["results"]:
            raise RuntimeError("The demo HGP query returned no results")
        if not any("proof:hgp-length" in node["labels"] for node in context["nodes"]):
            raise RuntimeError("The explicitly linked whole proof was missing from context")
        if any(edge["status"] in {"candidate", "stale", "unbound_review", "unresolved"}
               for result in (deps, impact, context) for edge in result["edges"]):
            raise RuntimeError("Default dependency/context queries exposed a filtered relation")

        catalog = run("catalog_ingest", ["-m", "qecgraph", "ingest", *base, "--out", str(catalog_store),
                                        "--catalog", "knowledge_starter/records",
                                        "--annotations", "examples/catalog-links.example.json"])
        run("catalog_validate", ["-m", "qecgraph", "validate", "--store", str(catalog_store)])
        data = run("catalog_context", ["-m", "qecgraph", "context", "code:rep3-hgp:13", "--store", str(catalog_store)])
        required = {"code:rep3-hgp:13", "presentation:rep3-hgp:standard", "claim:rep3-hgp:distance"}
        if not required <= {node["id"] for node in data["nodes"]}:
            raise RuntimeError("Catalog context did not retain instance/presentation/distance separation")

        verify_args = ["knowledge_starter/tools/qec_kb.py", "verify"]
        if has_schema:
            verify_args.append("--json-schema")
        evidence = run("finite_qec_verification", verify_args)
        report["schema_checks"] = {"status": "skipped_dependency_missing", "schemas": []}
        if has_schema:
            from jsonschema import Draft202012Validator
            for filename in ("graph.schema.json", "annotations.schema.json"):
                schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                validator = Draft202012Validator(schema)
                if filename.startswith("graph"):
                    for generated in (split, graph, catalog):
                        validator.validate(json.loads((Path(generated["snapshot"]) / "graph.json").read_text(encoding="utf-8")))
                else:
                    for filename2 in ("annotations.example.json", "catalog-links.example.json"):
                        validator.validate(json.loads((ROOT / "examples" / filename2).read_text(encoding="utf-8")))
            report["schema_checks"] = {"status": "passed", "schemas": ["graph.schema.json", "annotations.schema.json", "knowledge_starter schemas via verify"]}
        report["summary"] = {
            "unit_tests": report["steps"][0]["test_count"],
            "source_files": len(split["sources"]), "source_fragments": split["fragment_count"],
            "source_only_graph": {"nodes": split["node_count"], "edges": split["edge_count"]},
            "annotated_graph": {"nodes": graph["node_count"], "edges": graph["edge_count"], "snapshot_id": graph["snapshot_id"]},
            "catalog_graph": {"nodes": catalog["node_count"], "edges": catalog["edge_count"]},
            "search_hits": len(hits["results"]), "context_nodes": len(context["nodes"]),
            "catalog_context_nodes": len(data["nodes"]),
            "finite_qec_check": evidence,
            "mathematical_scope": "Finite Python demonstration only; no Lean verification",
        }
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(out / "results.json", report)
    print(json.dumps({"status": report["status"], "report": str(out / "results.json"),
                      "summary": report.get("summary"), "error": report.get("error")}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
