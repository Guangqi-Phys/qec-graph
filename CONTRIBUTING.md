# Contributing to QEC Graph

Use Python 3.11 or later on a POSIX system with SQLite FTS5. From a checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'pip>=25.1'
python -m pip install --group dev -e .
python -m ruff check qecgraph tests tools
python -m mypy
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
```

For an end-to-end check, run `python tools/reproduce.py --out build/reproduce`.
The [development guide](START_HERE.md) points to workspace, MCP, and Lean
checks that need separate setup. Mention which commands ran and which were
not run when proposing a change.

Keep source bytes, stable IDs, revisions, and evidence bindings intact.
Use temporary workspaces for tests. Commit only fixtures you have permission
to redistribute, and document their license and origin. A synthetic record
should be marked synthetic and should never establish a paper's findings.

See the [documentation index](docs/README.md) for where to update a guide,
the [changelog](CHANGELOG.md) for compatibility changes, and the
[security policy](SECURITY.md) for private reports.
