#!/usr/bin/env python3
"""Prepare original TeX through isolated local compilation and lossless syntax conversion."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qecgraph.preparation.pipeline import prepare_material  # noqa: E402
from qecgraph.preparation.contract import read_material  # noqa: E402
from qecgraph.source.prepare import recover_output  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--entry")
    parser.add_argument("--engine", choices=["pdflatex", "xelatex", "lualatex", "latex", "etex", "pdftex"])
    parser.add_argument("--support-dir", action="append", type=Path, default=[])
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--json", action="store_true", help="JSON output (the default)")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--check", action="store_true", help="validate an existing material without compiling")
    args = parser.parse_args(argv)
    try:
        if args.recover:
            result = {"recovered": recover_output(args.out)}
            code = 1 if result["recovered"] == "conflict" else 0
        elif args.check:
            result = read_material(args.out)["validation"]
            code = 0 if result["ready_for_extraction"] else 2
        else:
            if args.source is None:
                parser.error("source is required unless --check or --recover is used")
            result = prepare_material(args.source, args.out, entry=args.entry, engine=args.engine,
                                      support=args.support_dir, overwrite=args.overwrite)
            code = 0 if result["status"] == "ready" else 2
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
