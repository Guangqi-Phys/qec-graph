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
from qecgraph.preparation.artifacts import json_bytes  # noqa: E402
from qecgraph.prepared_extraction import PreparedSource, extract_source  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("material", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--check", action="store_true", help="Verify a saved extraction"
    )
    args = parser.parse_args(argv)
    try:
        source = PreparedSource(args.material)
        if args.out.resolve().is_relative_to(source.root):
            raise ValueError("Extraction output must be outside the prepared material")
        result = extract_source(source)
        if args.check:
            saved = strict_json_loads(args.out.read_text(encoding="utf-8"))
            if saved != result:
                raise ValueError("Saved extraction differs from the verified input")
        else:
            atomic_bytes(args.out, json_bytes(result, indent=None))
    except (OSError, ValueError, RuntimeError, KeyError, ValidationError) as exc:
        error = exc.message if isinstance(exc, ValidationError) else str(exc)
        print(json.dumps({"status": "failed", "error": error}), file=sys.stderr)
        return 1
    status = result["input"]["status"]
    print(
        json.dumps(
            {
                "status": status,
                "out": str(args.out),
                "checked": args.check,
                "units": len(result["source"]["units"]),
            }
        )
    )
    return 0 if status == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
