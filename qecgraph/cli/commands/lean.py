"""CLI handlers for the experimental/deferred Lean tools."""
from __future__ import annotations

from ...graph import read_json
from ...registry import Registry
from ..render import emit_report


def build(args):
    from ...lean import build_project
    result = build_project(args.project, args.out, lake=args.lake, export_declarations=not args.build_only)
    return emit_report(result, quiet=args.quiet)


def import_report(args):
    from ...lean_integration import import_build
    mappings = read_json(args.mapping) if args.mapping else None
    if mappings is not None and isinstance(mappings, dict):
        mappings = [mappings]
    result = import_build(args.corpus, args.report, project_id=args.project_id, project=args.project,
                          mappings=mappings, historical=args.historical)
    return emit_report(result, quiet=args.quiet)


def status(args):
    from ...lean_integration import lean_record_states
    from ...status import review_states
    registry = Registry(args.corpus)
    state, fixed = registry.read(args.registry_revision)
    records = registry.records_from_state(state)
    reviews = review_states(registry, state, records)
    result = {'registry_revision': fixed, 'records': lean_record_states(registry, state, records, reviews),
              'scope': 'read-only freshness; no Lean process or semantic approval'}
    return emit_report(result, quiet=args.quiet)
