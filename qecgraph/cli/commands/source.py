"""CLI handlers for source commands."""
from __future__ import annotations

from ...source.splitter import split_project
from ...store import ingest, validate_snapshot
from ..render import emit_report, print_json


def watch(args):
    from ...watch import Watcher, run
    watcher = Watcher(args.entry, args.project_id, args.out, args.project_root, args.config, args.annotations, args.catalog,
                      strict=args.strict, debounce=0 if args.once else args.debounce)
    def event_report(event):
        print_json(event, compact=True, flush=True)

    result = run(watcher, interval=args.interval, max_polls=1 if args.once else args.max_polls,
                 emit=None if args.quiet else event_report)
    return emit_report(result, quiet=args.quiet, compact=True)


def recover(args):
    from ...store import recover_store
    result = recover_store(args.store, remove_abandoned=args.remove_abandoned)
    return emit_report(result, quiet=args.quiet)


def validate_staged(args):
    from pathlib import Path
    from ...store import safe_relative
    if len(args.snapshot) != 64 or any(c not in '0123456789abcdef' for c in args.snapshot):
        raise ValueError('Invalid staged snapshot ID')
    result = validate_snapshot(safe_relative(Path(args.store).resolve(), 'staging/' + args.snapshot))
    return emit_report(result, quiet=args.quiet)


def ingest_source(args):
    result = ingest(args.entry, args.project_id, args.out, args.project_root, args.config, args.annotations, args.catalog,
                    strict=args.strict, incremental=args.incremental)
    return emit_report(result, quiet=args.quiet)


def split(args):
    result = split_project(args.entry, args.project_id, args.out, args.project_root, args.config,
                           strict=args.strict, incremental=args.incremental, force=args.force)
    return emit_report(result, quiet=args.quiet)
