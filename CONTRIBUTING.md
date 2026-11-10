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
The [documentation index](docs/README.md) and [system design](docs/design/DESIGN.md)
point to workspace, MCP, and Lean checks that need separate setup. Mention which commands ran and which were
not run when proposing a change.

Keep source bytes, stable IDs, revisions, and evidence bindings intact.
Use temporary workspaces for tests. Commit only fixtures you have permission
to redistribute, and document their license and origin. A synthetic record
should be marked synthetic and should never establish a paper's findings.

See the [documentation index](docs/README.md) for where to update a guide,
the [changelog](CHANGELOG.md) for compatibility changes, and the
[security policy](SECURITY.md) for private reports.

## Documentation rules

- Current pages live only under `docs/user/`, `docs/design/` and
  `docs/operations/`. There is no redirect or archive tree; superseded pages
  are recovered from Git history.
- `docs/design/DESIGN.md` is the only design document. Extend it in the same
  change as the implementation instead of adding a parallel design page.
- Every current page starts with a one-line status marker. Pages with more than
  one `##` section include an `## On this page` table of contents whose anchors
  match the headings.
- Prefer small tables, GitHub alerts (`> [!NOTE]`, `> [!TIP]`, `> [!WARNING]`)
  and Mermaid diagrams where they clarify a branch or workflow. Do not add
  decorative markup that repeats the prose.
- Run `python -m unittest tests.test_docs -v` after moving or renaming a page;
  it checks status markers, links, reachability and table-of-contents anchors.
