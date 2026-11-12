"""Reject new or increased C901 complexity; retain explicit legacy debt."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'validation/complexity_baseline.json'


def inventory() -> dict[str, int]:
    run = subprocess.run([sys.executable, '-m', 'ruff', 'check', '--select', 'C90',
                          '--output-format', 'json', 'qecgraph'], cwd=ROOT, capture_output=True, text=True)
    if run.returncode not in (0, 1):
        raise RuntimeError('Ruff complexity scan failed: ' + run.stderr)
    result = {}
    trees = {}
    for item in json.loads(run.stdout):
        path = Path(item['filename'])
        if path not in trees:
            trees[path] = ast.parse(path.read_text())
        line = item['location']['row']
        scopes = [node for node in ast.walk(trees[path])
                  if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.lineno <= line <= (node.end_lineno or node.lineno)]
        scopes.sort(key=lambda node: node.lineno)
        key = path.relative_to(ROOT).as_posix() + ':' + '.'.join(node.name for node in scopes)
        match = re.search(r'\((\d+) >', item['message'])
        if match is None or key in result:
            raise RuntimeError('Ambiguous complexity diagnostic')
        result[key] = int(match[1])
    return result


def main() -> int:
    observed = inventory()
    if sys.argv[1:] == ['--update']:
        BASELINE.write_text(json.dumps(observed, sort_keys=True, indent=2) + '\n')
        print(f'Recorded {len(observed)} existing complex functions; review baseline changes explicitly')
        return 0
    if sys.argv[1:]:
        raise SystemExit('Usage: python tools/check_complexity.py [--update]')
    baseline = json.loads(BASELINE.read_text())
    regressions = {key: value for key, value in observed.items() if value > baseline.get(key, 10)}
    print(json.dumps({'legacy_functions_over_10': len(observed), 'regressions': regressions}, sort_keys=True))
    return int(bool(regressions))


if __name__ == '__main__':
    raise SystemExit(main())
