"""CLI handlers for source commands."""
from __future__ import annotations

from ...source.splitter import split_project
from ..render import emit_report


def split(args):
    result = split_project(args.entry, args.project_id, args.out, args.project_root, args.config,
                           strict=args.strict, incremental=args.incremental, force=args.force)
    return emit_report(result, quiet=args.quiet)
