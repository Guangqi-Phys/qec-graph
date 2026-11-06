from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from .query import context, dependencies, search, show
from .splitter import split_project
from .store import current_snapshot, ingest, pin_snapshot, validate_snapshot
from .registry import Registry
from .graph import read_json


def _add_query_scope(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--store')
    group.add_argument('--corpus')
    parser.add_argument('--snapshot', help='Fixed store snapshot ID')
    parser.add_argument('--registry-revision', help='Fixed corpus state revision')
    parser.add_argument('--source-version-id', help='Restrict corpus source scope')


def _add_source_arguments(parser):
    parser.add_argument("entry")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--config")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="qecgraph", description="LaTeX source blocks and typed QEC graph; no mathematical proof verification")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser('migrate', help='Adapt legacy inputs into a new location with a rejection report')
    cmd.add_argument('input')
    cmd.add_argument('--out', required=True)
    cmd.add_argument('--source-root')
    cmd = sub.add_parser('migration-import', help='Import adapted records and managed assets atomically')
    cmd.add_argument('input')
    cmd.add_argument('--corpus', required=True)
    for name in ('record-add', 'claim-link'):
        cmd = sub.add_parser(name, help="Add an explicit record or provenance mapping from JSON")
        cmd.add_argument("input")
        cmd.add_argument("--corpus", required=True)
    cmd = sub.add_parser("register", help="Archive a store as an explicit work/source version in a corpus")
    cmd.add_argument("--corpus", required=True)
    cmd.add_argument("--store", required=True)
    cmd.add_argument("--work-id", required=True)
    cmd.add_argument("--source-version-id", required=True)
    cmd.add_argument("--title")
    cmd.add_argument("--upstream-version")
    cmd = sub.add_parser("ingest", help="Parse a LaTeX project and write an immutable snapshot")
    _add_source_arguments(cmd)
    cmd.add_argument("--annotations")
    cmd.add_argument("--catalog", help="Directory of existing JSON records, such as the earlier starter records/")
    cmd = sub.add_parser("split", help="Write source-only semantic fragments and return their exact file paths")
    _add_source_arguments(cmd)
    cmd = sub.add_parser("search", help="Search titles, labels and text")
    cmd.add_argument("query")
    _add_query_scope(cmd)
    cmd.add_argument("--kind")
    cmd.add_argument("--limit", type=int, default=20)
    cmd = sub.add_parser("show", help="Read one node with its incoming/outgoing edges")
    cmd.add_argument("id_or_label")
    _add_query_scope(cmd)
    for name in ("deps", "impact", "context"):
        cmd = sub.add_parser(name)
        cmd.add_argument("id_or_label")
        _add_query_scope(cmd)
        cmd.add_argument("--depth", type=int, default=2)
        cmd.add_argument("--include-candidates", action="store_true")
        cmd.add_argument("--max-nodes", type=int, default=60)
    cmd = sub.add_parser("validate", help="Validate hashes, source spans, endpoints and SQLite")
    cmd.add_argument("--store", required=True)
    cmd.add_argument('--snapshot')
    args = parser.parse_args(argv)
    try:
        if args.command in {'search', 'show', 'deps', 'impact', 'context', 'validate'}:
            if getattr(args, 'corpus', None):
                if args.snapshot:
                    raise ValueError('--snapshot belongs to store queries; use --registry-revision for a corpus')
            else:
                if getattr(args, 'registry_revision', None) or getattr(args, 'source_version_id', None):
                    raise ValueError('Corpus scope arguments require --corpus')
                args.store = pin_snapshot(args.store, args.snapshot)
        if args.command == 'migrate':
            from .migrations import migrate
            result = migrate(args.input, args.out, source_root=args.source_root)
        elif args.command == 'migration-import':
            result = Registry(args.corpus).import_migration(args.input)
        elif args.command == 'record-add':
            result = Registry(args.corpus).add_record(read_json(args.input))
        elif args.command == 'claim-link':
            result = Registry(args.corpus).link_claim(**read_json(args.input))
        elif args.command == "register":
            result = Registry(args.corpus).register_source(args.work_id, args.source_version_id, args.store,
                                                         title=args.title, upstream_version=args.upstream_version)
        elif args.command == "ingest":
            result = ingest(args.entry, args.project_id, args.out, args.project_root, args.config, args.annotations, args.catalog)
        elif args.command == "split":
            result = split_project(args.entry, args.project_id, args.out, args.project_root, args.config)
        elif getattr(args, 'corpus', None):
            from .corpus import execute
            result = execute(args.corpus, args.command, getattr(args, 'id_or_label', None),
                             registry_revision=args.registry_revision, source_version_id=args.source_version_id,
                             text=getattr(args, 'query', None), kind=getattr(args, 'kind', None),
                             limit=getattr(args, 'limit', 20), depth=getattr(args, 'depth', 2),
                             include_candidates=getattr(args, 'include_candidates', False),
                             max_nodes=getattr(args, 'max_nodes', 60))
        elif args.command == "search":
            result = search(args.store, args.query, args.kind, args.limit)
        elif args.command == "show":
            result = show(args.store, args.id_or_label)
        elif args.command == "validate":
            result = validate_snapshot(current_snapshot(args.store))
        elif args.command == "context":
            result = context(args.store, args.id_or_label, args.depth, args.include_candidates, args.max_nodes)
        else:
            result = dependencies(args.store, args.id_or_label, args.depth, args.include_candidates,
                                  args.command == "impact", args.max_nodes)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result.get('suggested_exit_code', 2 if result.get("extraction_status") == "partial" else 0)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
