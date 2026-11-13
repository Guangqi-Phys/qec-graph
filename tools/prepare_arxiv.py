#!/usr/bin/env python3
"""Prepare one arXiv source tree as byte-faithful LaTeX plus document/2 JSON.

The recognition and conversion implementation lives in
``qecgraph/source/prepare.py``. This command is the offline entry point: it
loads a source directory or package, prepares the entry and document model,
and writes the artifacts described in ``docs/design/DESIGN.md`` §5.4.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qecgraph import PARSER_VERSION  # noqa: E402
from qecgraph.source.prepare import (  # noqa: E402
    load_source,
    prepare_source,
    write_outputs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path,
                        help="source directory or arXiv package (.tar.gz, .gz)")
    parser.add_argument("--entry", help="entry path inside the source tree")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--no-parser-recovery", action="store_true",
                        help="do not retry failed strict parses with tolerant parsing")
    parser.add_argument("--no-transparent-containers", action="store_true",
                        help="do not traverse unknown environments transparently")
    parser.add_argument("--json", action="store_true", help="print a JSON summary")
    args = parser.parse_args(argv)
    try:
        tree = load_source(args.source)
        prepared = prepare_source(
            tree, args.entry,
            recover_parse_errors=not args.no_parser_recovery,
            transparent_containers=not args.no_transparent_containers)
        write_outputs(
            prepared, args.out, source=args.source,
            parser_version=PARSER_VERSION,
            parse_options={
                "recover_parse_errors": not args.no_parser_recovery,
                "transparent_containers": not args.no_transparent_containers,
            })
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"prepare failed: {exc}", file=sys.stderr)
        return 1
    summary = prepared.summary()
    summary["out"] = str(args.out)
    if args.json:
        print(json.dumps(summary, indent=1, ensure_ascii=False))
    else:
        coverage = summary["coverage"]
        print(f"entry: {summary['entry']} ({summary['entry_bytes']} bytes)")
        print(f"directives: {coverage['directives']} {coverage['outcomes']}")
        print(f"blocks: {summary['blocks']} sections: {summary['sections']} "
              f"parser errors: {summary['parser_errors']}")
        print(f"output: {summary['out']}")
    return 0 if summary["coverage"]["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
