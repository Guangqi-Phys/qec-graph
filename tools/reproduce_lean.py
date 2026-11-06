"""Explicitly rebuild the pinned Lean project and retain real command evidence."""
import argparse
import json
from pathlib import Path

from qecgraph.lean import build_project


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=str(Path(__file__).resolve().parents[1] / 'lean'))
    parser.add_argument('--out', default='build/reproduce-lean')
    parser.add_argument('--lake')
    args = parser.parse_args(argv)
    result = build_project(args.project, args.out, lake=args.lake)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result['suggested_exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
