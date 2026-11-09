"""CLI handlers for records commands."""
from __future__ import annotations

from ...graph import read_json
from ...registry import Registry
from ..render import emit_report


def _command_object(path, required, optional=()):
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError("Input must be a JSON object")
    if missing := set(required) - value.keys():
        raise ValueError("Input is missing fields: " + ", ".join(sorted(missing)))
    if extra := value.keys() - (set(required) | set(optional)):
        raise ValueError("Unknown input fields: " + ", ".join(sorted(extra)))
    return value


def workspace_records(args):
    from ...workspace import Workspace
    from ...research_store import load_records, publish_records
    ws = Workspace(args.workspace)
    ws.config()
    if args.command == 'software-import-seed':
        from ...software import adapt_seed, bundled_seed
        result = publish_records(ws.registry, adapt_seed(bundled_seed()))
    elif args.command == 'software-refresh':
        from ...software import refresh
        result = refresh(ws.registry, project_id=args.project_id, limit=args.limit, timeout=args.timeout)
    elif args.command == 'software-coverage':
        from ...software import coverage
        state, release = ws.registry.read()
        result = {'release_id': release, **coverage(r for r in load_records(ws.registry, state) if not r['is_synthetic'])}
    elif args.command == 'research-import':
        payload = read_json(args.input)
        if args.format == 'software-seed':
            from ...software import adapt_seed
            payload = adapt_seed(payload)
        elif args.format == 'synthetic-fixture':
            from ...research import adapt_synthetic
            payload = adapt_synthetic(payload)
        if not isinstance(payload, list):
            raise ValueError('Research import expects a list of records')
        result = publish_records(ws.registry, payload)
    else:
        state, release = ws.registry.read()
        rows = [row for row in load_records(ws.registry, state)
                if not row['is_synthetic'] and row['data'].get('review_status') == 'proposed']
        from ...semantic import queued
        result = {'release_id': release, 'proposals': rows, 'provider_drafts': queued(ws.root, state)}
    return emit_report(result, quiet=args.quiet, exit_code=2 if result.get('status') == 'partial' else 0)


def apply(args):
    from ...review import apply
    result = apply(args.corpus, args.proposal_id, args.review_id)
    return emit_report(result, quiet=args.quiet)


def propose(args):
    from ...review import create_proposal
    payload = _command_object(args.input, ('changes', 'rationale'), ('expected_registry_revision',))
    result = create_proposal(args.corpus, actor={'id': args.actor_id, 'kind': args.actor_kind}, **payload)
    return emit_report(result, quiet=args.quiet)


def review_show(args):
    if args.corpus:
        from ...review import read_proposal
        result = read_proposal(Registry(args.corpus), args.proposal_id)
    else:
        from ...semantic import get_draft
        from ...workspace import Workspace
        ws = Workspace(args.workspace)
        ws.config()
        state, release = ws.registry.read()
        result = {'release_id': release, 'provider_draft': get_draft(ws, state, args.proposal_id)}
    return emit_report(result, quiet=args.quiet)


def decide(args):
    from ...review import decide
    result = decide(args.corpus, args.proposal_id, actor={'id': args.actor_id, 'kind': args.actor_kind},
                    decision=args.decision, rationale=args.rationale, checked_scopes=args.checked_scope)
    return emit_report(result, quiet=args.quiet)


def check_css(args):
    from ...validators.qec import check_css
    result = check_css(read_json(args.hx), read_json(args.hz), read_json(args.lx) if args.lx else None,
                       read_json(args.lz) if args.lz else None, enumerate_distance=args.enumerate_distance, max_n=args.max_n)
    result['suggested_exit_code'] = 0 if result['passed'] else 2
    return emit_report(result, quiet=args.quiet)


def check_experiment(args):
    from ...validators.qec import check_experiment
    payload = _command_object(args.input, ('record', 'metric'))
    result = check_experiment(payload['record'], payload['metric'])
    return emit_report(result, quiet=args.quiet)


def codes(args):
    if args.corpus is None:
        from .query import research_query
        return research_query(args)
    if any(getattr(args, flag) is not None for flag in ('release', 'metric_revision', 'evidence_policy', 'offset', 'max_chars')):
        raise ValueError('Workspace filters require --workspace or --machine')
    from ...domain_query import codes
    result = codes(args.corpus, registry_revision=args.registry_revision, n_min=args.n_min, n_max=args.n_max,
                   distance_at_least=args.distance_at_least, metric_definition_id=args.metric_definition_id,
                   sector=args.sector or 'joint', construction=args.construction, limit=100 if args.limit is None else args.limit)
    return emit_report(result, quiet=args.quiet)


def validate_corpus(args):
    result = Registry(args.corpus).validate(args.registry_revision)
    return emit_report(result, quiet=args.quiet)


def migrate(args):
    from ...migrations import migrate
    result = migrate(args.input, args.out, source_root=args.source_root)
    return emit_report(result, quiet=args.quiet)


def import_migration(args):
    result = Registry(args.corpus).import_migration(args.input)
    return emit_report(result, quiet=args.quiet)


def add_record(args):
    result = Registry(args.corpus).add_record(read_json(args.input))
    return emit_report(result, quiet=args.quiet)


def link_claim(args):
    payload = _command_object(args.input, ('link_id', 'source_version_id', 'source_selector', 'claim_id'),
                              ('claim_revision', 'assumptions', 'notation_scope'))
    result = Registry(args.corpus).link_claim(**payload)
    return emit_report(result, quiet=args.quiet)


def register(args):
    result = Registry(args.corpus).register_source(args.work_id, args.source_version_id, args.store,
                                                 title=args.title, upstream_version=args.upstream_version)
    return emit_report(result, quiet=args.quiet)
