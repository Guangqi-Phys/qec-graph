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
    parser.add_argument('--strict', action='store_true', help='Keep partial extraction in staging without changing CURRENT')
    parser.add_argument('--incremental', action='store_true', help='Reuse content-checked per-file ASTs; rebuild semantic projections')


def main(argv=None):
    parser = argparse.ArgumentParser(prog="qecgraph", description="LaTeX source blocks and typed QEC graph; no mathematical proof verification")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser('watch', help='Debounced content polling; rebuild through the shared ingestion pipeline')
    _add_source_arguments(cmd)
    cmd.add_argument('--annotations')
    cmd.add_argument('--catalog')
    cmd.add_argument('--interval', type=float, default=0.5)
    cmd.add_argument('--debounce', type=float, default=0.25)
    cmd.add_argument('--max-polls', type=int)
    cmd.add_argument('--once', action='store_true')
    cmd = sub.add_parser('recover-store', help='Validate CURRENT and inventory abandoned tool-owned builds')
    cmd.add_argument('--store', required=True)
    cmd.add_argument('--remove-abandoned', action='store_true')
    cmd = sub.add_parser('validate-staged', help='Validate an explicitly selected staged snapshot')
    cmd.add_argument('--store', required=True)
    cmd.add_argument('--snapshot', required=True)
    cmd = sub.add_parser('audit-dependencies', help='Report SCCs only in active reviewed logical dependencies')
    _add_query_scope(cmd)
    cmd = sub.add_parser('apply', help='Atomically publish a reviewed proposal with input conflict checks')
    cmd.add_argument('proposal_id')
    cmd.add_argument('--review-id', required=True)
    cmd.add_argument('--corpus', required=True)
    cmd = sub.add_parser('review', help='Create an inspectable proposal, without applying changes')
    cmd.add_argument('input', help='JSON with changes and rationale')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--actor-id', required=True)
    cmd.add_argument('--actor-kind', choices=['ai', 'program', 'human'], default='ai')
    cmd = sub.add_parser('review-decide', help='Bind an explicit decision to an exact proposal')
    cmd.add_argument('proposal_id')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--actor-id', required=True)
    cmd.add_argument('--actor-kind', choices=['ai', 'program', 'human'], default='ai')
    cmd.add_argument('--decision', choices=['approve', 'reject'], required=True)
    cmd.add_argument('--rationale', required=True)
    cmd.add_argument('--checked-scope', choices=['statement', 'hypotheses', 'dependencies'], action='append', default=[])
    cmd = sub.add_parser('check-css', help='Validate binary check matrices; optionally enumerate a small distance')
    cmd.add_argument('--hx', required=True)
    cmd.add_argument('--hz', required=True)
    cmd.add_argument('--lx')
    cmd.add_argument('--lz')
    cmd.add_argument('--enumerate-distance', action='store_true')
    cmd.add_argument('--max-n', type=int, default=20)
    cmd = sub.add_parser('check-experiment', help='Check explicit experiment/metric JSON; no evidence promotion')
    cmd.add_argument('input')
    cmd = sub.add_parser('codes', help='Exact code constraints, metric and currently bound distance evidence')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--registry-revision')
    cmd.add_argument('--n-min', type=int)
    cmd.add_argument('--n-max', type=int)
    cmd.add_argument('--distance-at-least', type=int)
    cmd.add_argument('--metric-definition-id')
    cmd.add_argument('--sector', choices=['X', 'Z', 'joint'], default='joint')
    cmd.add_argument('--construction')
    cmd.add_argument('--limit', type=int, default=100)
    cmd = sub.add_parser('validate-corpus', help='Check typed records, references, sources and managed assets')
    cmd.add_argument('--corpus', required=True)
    cmd.add_argument('--registry-revision')
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
        if args.command in {'search', 'show', 'deps', 'impact', 'context', 'validate', 'audit-dependencies'}:
            if getattr(args, 'corpus', None):
                if args.snapshot:
                    raise ValueError('--snapshot belongs to store queries; use --registry-revision for a corpus')
            else:
                if getattr(args, 'registry_revision', None) or getattr(args, 'source_version_id', None):
                    raise ValueError('Corpus scope arguments require --corpus')
                args.store = pin_snapshot(args.store, args.snapshot)
        if args.command == 'watch':
            from .watch import Watcher, run
            watcher = Watcher(args.entry, args.project_id, args.out, args.project_root, args.config, args.annotations, args.catalog,
                              strict=args.strict, debounce=0 if args.once else args.debounce)
            result = run(watcher, interval=args.interval, max_polls=1 if args.once else args.max_polls,
                         emit=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return result['suggested_exit_code']
        elif args.command == 'recover-store':
            from .store import recover_store
            result = recover_store(args.store, remove_abandoned=args.remove_abandoned)
        elif args.command == 'validate-staged':
            from pathlib import Path
            from .store import safe_relative
            if len(args.snapshot) != 64 or any(c not in '0123456789abcdef' for c in args.snapshot):
                raise ValueError('Invalid staged snapshot ID')
            result = validate_snapshot(safe_relative(Path(args.store).resolve(), 'staging/' + args.snapshot))
        elif args.command == 'audit-dependencies':
            from .status import reviewed_cycles
            if args.corpus:
                from .corpus import project
                graph_input, scope = project(args.corpus, args.registry_revision, args.source_version_id)
                graph = graph_input.graph
            else:
                from .store import load_graph
                graph, _ = load_graph(args.store)
                scope = {'snapshot_id': graph['snapshot_id']}
            result = {'scope': scope, 'issues': reviewed_cycles(graph), 'policy': 'Active reviewed logic only; citation cycles are retained'}
        elif args.command == 'apply':
            from .review import apply
            result = apply(args.corpus, args.proposal_id, args.review_id)
        elif args.command == 'review':
            from .review import create_proposal
            result = create_proposal(args.corpus, actor={'id': args.actor_id, 'kind': args.actor_kind}, **read_json(args.input))
        elif args.command == 'review-decide':
            from .review import decide
            result = decide(args.corpus, args.proposal_id, actor={'id': args.actor_id, 'kind': args.actor_kind},
                            decision=args.decision, rationale=args.rationale, checked_scopes=args.checked_scope)
        elif args.command == 'check-css':
            from .validators.qec import check_css
            result = check_css(read_json(args.hx), read_json(args.hz), read_json(args.lx) if args.lx else None,
                               read_json(args.lz) if args.lz else None, enumerate_distance=args.enumerate_distance, max_n=args.max_n)
            result['suggested_exit_code'] = 0 if result['passed'] else 2
        elif args.command == 'check-experiment':
            from .validators.qec import check_experiment
            payload = read_json(args.input)
            result = check_experiment(payload['record'], payload['metric'])
        elif args.command == 'codes':
            from .domain_query import codes
            result = codes(args.corpus, registry_revision=args.registry_revision, n_min=args.n_min, n_max=args.n_max,
                           distance_at_least=args.distance_at_least, metric_definition_id=args.metric_definition_id,
                           sector=args.sector, construction=args.construction, limit=args.limit)
        elif args.command == 'validate-corpus':
            result = Registry(args.corpus).validate(args.registry_revision)
        elif args.command == 'migrate':
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
            result = ingest(args.entry, args.project_id, args.out, args.project_root, args.config, args.annotations, args.catalog,
                            strict=args.strict, incremental=args.incremental)
        elif args.command == "split":
            result = split_project(args.entry, args.project_id, args.out, args.project_root, args.config,
                                   strict=args.strict, incremental=args.incremental)
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
