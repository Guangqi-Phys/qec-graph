"""Read-only inspection of workspace health and locally stored snapshots."""

import platform
import sqlite3
from contextlib import closing
from pathlib import Path

from . import __version__
from .graph import read_json
from .registry import Registry
from .store import current_snapshot
from .transactions import ManagedDataError
from .workspace import HEX, JOB, Workspace
from .workspace_query import check_machine_tree


def doctor(workspace):
    ws = Workspace(workspace)
    checks = {}

    def probe(name, check):
        try:
            checks[name] = {'status': 'ok', **check()}
        except FileNotFoundError:
            checks[name] = {'status': 'error', 'message': 'Required workspace file or directory is missing'}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            checks[name] = {'status': 'error', 'message': str(exc)}

    def pointer():
        check_machine_tree(ws.registry.root)
        _, release = ws.registry.read()
        return {'release_id': release}

    def inventory():
        blobs = ws.path('archive/blobs/sha256')
        receipts = ws.path('archive/receipts')
        return {'blobs': sum(bool(HEX.fullmatch(path.name)) for path in blobs.iterdir()),
                'receipts': sum(path.suffix == '.json' and bool(JOB.fullmatch(path.stem))
                                for path in receipts.iterdir())}

    def inbox():
        result = ws.list_inputs()
        return {'pending': len(result['inputs']), 'pending_claims': result['pending_claims'],
                'quarantined': len(result['quarantined_inputs'])}

    def sqlite_fts5():
        try:
            with closing(sqlite3.connect(':memory:')) as connection:
                connection.execute('CREATE VIRTUAL TABLE qec_probe USING fts5(content)')
        except sqlite3.Error as exc:
            raise ValueError('SQLite cannot create an FTS5 index. Use a QEC Graph runtime with FTS5.') from exc
        return {'available': True}

    probe('config', lambda: {'workspace_id': ws.config()['workspace_id']})
    probe('machine/CURRENT.json', pointer)
    probe('archive_inventory', inventory)
    probe('inbox', inbox)
    probe('sqlite_fts5', sqlite_fts5)
    release = checks['machine/CURRENT.json'].get('release_id')
    human = None
    if release is not None:
        operational = ws.path('machine/operational/status.json')
        if operational.is_file():
            def renderer():
                try:
                    status = read_json(operational)
                except ValueError as exc:
                    raise ManagedDataError(operational, 'Invalid renderer status JSON') from exc
                if not isinstance(status, dict) or not isinstance(status.get('human', {}), dict):
                    raise ManagedDataError(operational, 'Invalid renderer status record')
                data = status.get('human', {})
                return {'renderer_status': ('current' if data.get('status') == 'current'
                                             and data.get('rendered_release_id') == release else 'human_stale')}

            probe('renderer', renderer)
            human = checks['renderer'].get('renderer_status')
    passed = all(check['status'] == 'ok' for check in checks.values())
    return {'status': 'ok' if passed else 'invalid', 'suggested_exit_code': 0 if passed else 1,
            'workspace': str(ws.root), 'release_id': release, 'checks': checks, 'human_status': human,
            'runtime': {'qecgraph': __version__, 'python': platform.python_version(),
                        'sqlite': sqlite3.sqlite_version},
            'scope': 'workspace metadata and inventory; use validate to verify archive and snapshot hashes'}


def list_snapshots(*, store=None, corpus=None, workspace=None):
    if store is not None:
        root = Path(store).expanduser().resolve()
        current = current_snapshot(root).name
        directory = root / 'snapshots'
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Expected a local snapshots directory')
        rows = [path.name for path in directory.iterdir()
                if HEX.fullmatch(path.name) and not path.is_symlink() and path.is_dir()]
        return {'scope': 'store', 'current': current, 'snapshots': sorted(rows)}

    registry = Registry(corpus) if corpus is not None else Workspace(workspace).registry
    check_machine_tree(registry.root)
    _, current = registry.read()
    rows = [path.stem for path in (registry.root / 'states').iterdir()
            if path.suffix == '.json' and HEX.fullmatch(path.stem) and path.is_file()]
    return {'scope': 'corpus' if corpus is not None else 'workspace', 'current': current,
            'stored_states': sorted(rows), 'includes_unpublished_candidates': True}
