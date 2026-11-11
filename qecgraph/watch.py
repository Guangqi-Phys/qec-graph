"""Debounced polling watch; scheduling only, always the same ingestion pipeline."""
from __future__ import annotations

from .core.progress import phase

import hashlib
import math
import sqlite3
import time
from pathlib import Path

from .core.graph import canonical, hash_text, read_json
from .source.incremental import input_inventory
from .store import ingest, safe_relative


class Watcher:
    def __init__(self, entry, project_id, out, project_root=None, config_path=None,
                 annotations_path=None, catalog_dir=None, *, strict=False, debounce=0.25, retry_interval=1.0):
        if not math.isfinite(debounce) or not math.isfinite(retry_interval) or debounce < 0 or retry_interval < 0:
            raise ValueError('Watch timing values must be nonnegative')
        self.entry = Path(entry).resolve()
        self.root = Path(project_root).resolve() if project_root else self.entry.parent
        self.out = Path(out).resolve()
        self.arguments = {'entry': self.entry, 'project_id': project_id, 'out': self.out, 'project_root': self.root,
                          'config_path': config_path, 'annotations_path': annotations_path,
                          'catalog_dir': catalog_dir, 'strict': strict, 'incremental': True}
        self.debounce, self.retry_interval = debounce, retry_interval
        self.accepted = self.pending = None
        self.pending_since = 0.0
        self.last_attempt = float('-inf')
        self.last_error = None
        self.build_count = 0
        self.last_result = None

    def signature(self):
        files, _ = input_inventory(self.root, exclude=[self.out], ignore_temporary=True)
        # Explicitly tracked assets still count if their real filename happens
        # to look like an editor temporary file.
        plan_path = self.out / 'cache/incremental-state.json'
        if plan_path.exists():
            try:
                plan = read_json(plan_path)
                for relative in plan.get('dependencies', {}).get('resources', []):
                    if relative:
                        path = safe_relative(self.root, relative)
                        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass  # The next build conservatively reparses invalid cache state.
        external = {}
        for name in ('config_path', 'annotations_path'):
            location = self.arguments[name]
            if location:
                path = Path(location).resolve()
                external[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
        if self.arguments['catalog_dir']:
            catalog = Path(self.arguments['catalog_dir']).resolve()
            external['catalog'] = {str(path.relative_to(catalog)): hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in sorted(catalog.rglob('*.json'))}
        return hash_text(canonical({'files': files, 'external': external}))

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
        try:
            signature = self.signature()
        except OSError as exc:
            error = str(exc)
            if error == self.last_error:
                return None
            self.last_error = error
            return {'event': 'input_unavailable', 'error': error, 'accepted_signature': self.accepted}
        if signature == self.accepted:
            self.pending = None
            if self.last_error:
                self.last_error = None
                return {'event': 'reconciled', 'signature': signature, 'note': 'Inputs again match the accepted content'}
            return None
        if signature != self.pending:
            self.pending, self.pending_since = signature, now
        if now - self.pending_since < self.debounce or now - self.last_attempt < self.retry_interval:
            return None
        self.last_attempt = now
        try:
            result = ingest(**self.arguments)
            after = self.signature()
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            error = str(exc)
            if error == self.last_error:
                return None
            self.last_error = error
            return {'event': 'build_failed', 'signature': signature, 'error': error,
                    'accepted_signature': self.accepted, 'retry': 'pending; accepted input is unchanged'}
        self.build_count += 1
        self.last_result = result
        self.last_error = None
        if after != signature:
            self.pending, self.pending_since = after, now
            return {'event': 'superseded', 'signature': signature, 'result': result,
                    'retry': 'inputs changed again; full content reconciliation is pending'}
        self.accepted = signature
        self.pending = None
        return {'event': 'built', 'signature': signature, 'result': result}


def run(watcher, *, interval=0.5, max_polls=None, emit=None):
    if not math.isfinite(interval) or interval <= 0 or max_polls is not None and max_polls < 1:
        raise ValueError('Watch interval must be positive and max_polls >= 1')
    polls = 0
    try:
        while max_polls is None or polls < max_polls:
            phase('Checking source changes')
            event = watcher.poll()
            polls += 1
            if event:
                if emit:
                    emit(event)
            if max_polls is None or polls < max_polls:
                phase('Watching for source changes', detail='Idle; Ctrl+C to stop')
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
    failed = watcher.last_error is not None
    partial = watcher.last_result and watcher.last_result.get('extraction_status') == 'partial'
    return {'event': 'stopped', 'polls': polls, 'build_count': watcher.build_count,
            'accepted_signature': watcher.accepted, 'pending_signature': watcher.pending,
            'suggested_exit_code': 1 if failed else 2 if partial or watcher.pending is not None else 0}
