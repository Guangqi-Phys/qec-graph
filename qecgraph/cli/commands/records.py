"""CLI handlers for records commands."""
from __future__ import annotations

from ...core.graph import read_json
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
    from ...domain.research_store import load_records, publish_records
    ws = Workspace(args.workspace)
    ws.config()
    if args.command == 'software-import-seed':
        from ...domain.software import adapt_seed, bundled_seed
        result = publish_records(ws.registry, adapt_seed(bundled_seed()))
    elif args.command == 'software-refresh':
        from ...domain.software import refresh
        result = refresh(ws.registry, project_id=args.project_id, limit=args.limit, timeout=args.timeout)
    elif args.command == 'software-coverage':
        from ...domain.software import coverage
        state, release = ws.registry.read()
        result = {'release_id': release, **coverage(r for r in load_records(ws.registry, state) if not r['is_synthetic'])}
    elif args.command == 'research-import':
        payload = read_json(args.input)
        if args.format == 'software-seed':
            from ...domain.software import adapt_seed
            payload = adapt_seed(payload)
        elif args.format == 'synthetic-fixture':
            from ...domain.research import adapt_synthetic
            payload = adapt_synthetic(payload)
        if not isinstance(payload, list):
            raise ValueError('Research import expects a list of records')
        result = publish_records(ws.registry, payload)
    else:
        state, release = ws.registry.read()
        rows = [row for row in load_records(ws.registry, state)
                if not row['is_synthetic'] and row['data'].get('review_status') == 'proposed']
        result = {'release_id': release, 'proposals': rows}
    return emit_report(result, quiet=args.quiet, exit_code=2 if result.get('status') == 'partial' else 0)


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
