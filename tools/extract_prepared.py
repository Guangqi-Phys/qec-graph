#!/usr/bin/env python3
"""Extract source-bound material from a verified compile-prepare-v20 bundle."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import ValidationError  # noqa: E402

from qecgraph.core.graph import strict_json_loads  # noqa: E402
from qecgraph.core.transactions import atomic_bytes  # noqa: E402
from qecgraph.llm.client import LLMClient  # noqa: E402
from qecgraph.llm.config import load_ai_config  # noqa: E402
from qecgraph.llm.prepared import SKILLS, run_semantics, verify_semantics  # noqa: E402
from qecgraph.preparation.artifacts import json_bytes  # noqa: E402
from qecgraph.prepared_extraction import PreparedSource, extract_source  # noqa: E402
from qecgraph.validators import packaged_validator  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("material", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--check", action="store_true", help="Verify a saved extraction"
    )
    parser.add_argument("--skill", action="append", choices=sorted(SKILLS))
    parser.add_argument(
        "--workspace", type=Path, help="Read AI settings from this workspace"
    )
    parser.add_argument(
        "--section", help="Use the prepared outline node as semantic scope"
    )
    args = parser.parse_args(argv)
    if args.skill and (args.check or args.workspace is None):
        parser.error("--skill requires --workspace and is unavailable with --check")
    if args.section and not args.skill:
        parser.error("--section requires --skill")
    try:
        result = _extract(args)
    except (OSError, ValueError, RuntimeError, KeyError, ValidationError) as exc:
        error = (
            f"Extraction schema rejected field {exc.json_path}"
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        print(json.dumps({"status": "failed", "error": error}), file=sys.stderr)
        return 1
    material_status = result["input"]["status"]
    tasks = {name: task["status"] for name, task in result["semantic"].items()}
    complete = material_status == "ready" and all(
        t == "proposed" for t in tasks.values()
    )
    print(
        json.dumps(
            {
                "status": "ready" if complete else "partial",
                "material_status": material_status,
                "out": str(args.out),
                "checked": args.check,
                "units": len(result["source"]["units"]),
                "semantic": tasks,
            }
        )
    )
    return 0 if complete else 2


def _extract(args):
    source = PreparedSource(args.material)
    if args.out.resolve().is_relative_to(source.root):
        raise ValueError("Extraction output must be outside the prepared material")
    result = extract_source(source)
    validator = packaged_validator("prepared-extraction")
    if args.check:
        saved = strict_json_loads(args.out.read_text(encoding="utf-8"))
        validator.validate(saved)
        if any(saved[k] != result[k] for k in ("input", "source")):
            raise ValueError("Saved extraction differs from the verified input")
        verify_semantics(source, saved)
        return saved
    if args.skill:
        config = load_ai_config(args.workspace)
        if not config.allow_source_upload:
            raise ValueError(
                "Semantic extraction requires explicit source upload permission"
            )
        result["semantic"] = run_semantics(
            source, result, LLMClient(config), args.skill, section=args.section
        )
        validator.validate(result)
    atomic_bytes(args.out, json_bytes(result, indent=None))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
