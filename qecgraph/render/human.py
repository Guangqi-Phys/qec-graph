"""Publish one Obsidian thoughts note per paper from a pinned machine release."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import tempfile

from ..core.progress import phase, track
from ..core.transactions import atomic_bytes, atomic_json, writer_lock
from ..workspace import HEX, Workspace, _read_regular, now, read_operational_status
from ..workspace_query import WorkspaceSession
from .thoughts import render_pages

FORMAT = 'qecgraph.human.thoughts'
LEGACY_FORMAT = 'qecgraph.human'
NOTE = re.compile(r'(?:[0-9]{4}|unknown)/(?:0[1-9]|1[0-2]|unknown)/[\w-]+_thoughts\.md')


def _operational(ws, release, human_status, last_release):
    path = ws.path('machine/operational/status.json')
    existing = read_operational_status(path)
    counts = existing.get('counts')
    atomic_json(path, {'observed_at': now(), 'release_id': release,
                       'counts': counts if isinstance(counts, dict) and existing.get('release_id') == release else {},
                       'human': {'status': human_status, 'target_release_id': release,
                                 'rendered_release_id': last_release}})



def _history(ws, name):
    path = ws.path('.qecgraph/' + name + '.json')
    if not path.exists():
        return {'release_id': None, 'pages': [], 'retired': []}
    data = json.loads(_read_regular(path, 20 << 20))
    if (not isinstance(data, dict) or data.get('format') not in {FORMAT, LEGACY_FORMAT}
            or not isinstance(data.get('release_id'), str) or not HEX.fullmatch(data['release_id'])):
        raise ValueError('Invalid renderer history')
    if data['format'] == LEGACY_FORMAT:
        # Legacy paths are never followed. The whole old human tree is removed
        # during migration, including notes/, without reading private contents.
        return data
    for field in ('pages', 'retired'):
        paths = data.get(field, [])
        if not isinstance(paths, list) or any(not isinstance(p, str) or not NOTE.fullmatch(p) for p in paths):
            raise ValueError('Renderer history has an unowned path')
    bindings = data.get('work_pages')
    if (not isinstance(bindings, dict) or set(bindings.values()) != set(data['pages'])
            or len(bindings) != len(data['pages']) or not all(isinstance(k, str) and k for k in bindings)):
        raise ValueError('Invalid renderer paper bindings')
    return data


def _prune_note(ws, relative):
    path = ws.path('human/' + relative)
    if path.exists() and not path.is_file():
        raise ValueError('An obsolete note is not a regular file')
    path.unlink(missing_ok=True)
    # Prune only the known month/year directories, never unrelated contents.
    for parent in (path.parent, path.parent.parent):
        try:
            parent.rmdir()
        except (FileNotFoundError, OSError):
            break


def build_human(workspace=None, release=None):
    ws = Workspace(workspace)
    ws.config()
    with writer_lock(ws.path('.qecgraph')), writer_lock(ws.registry.root):
        _, latest = ws.registry.read()
        if release is not None and release != latest:
            return {'status': 'superseded', 'target_release_id': release, 'current_release_id': latest}
        last_release = None
        try:
            past = _history(ws, 'human-published')
            interrupted = _history(ws, 'human-pending')
            last_release = past['release_id']
            _operational(ws, latest, 'human_stale', last_release)
            histories = (past, interrupted)
            current = [h for h in histories if h.get('format') == FORMAT]
            legacy = not current and any(h.get('format') == LEGACY_FORMAT for h in histories)
            previous = {p for h in current for p in [*h['pages'], *h.get('retired', [])]}
            vault = ws.path('human')
            if not current and not legacy and vault.exists() and any(vault.iterdir()):
                raise ValueError('human/ contains files outside the renderer history')
            session = WorkspaceSession(ws.registry.root, latest)
            phase('Preparing Obsidian thoughts notes')
            pages, targets = render_pages(session)
            if any(not NOTE.fullmatch(p) for p in pages):
                raise ValueError('Renderer produced an invalid note path')
            state = {'format': FORMAT, 'release_id': latest, 'pages': sorted(pages),
                     'work_pages': dict(sorted(targets.items()))}
            retired = sorted(previous - pages.keys())
            staging_root = ws.path('.qecgraph/human-staging')
            staging_root.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='render-', dir=staging_root) as staging:
                stage = Path(staging)
                changed = set()
                for relative, raw in track(pages.items(), 'Staging Obsidian notes', unit='notes'):
                    if not legacy:
                        destination = ws.path('human/' + relative)
                        if relative not in previous and destination.exists():
                            raise ValueError('A thought note would overwrite a file outside the renderer history')
                        try:
                            if _read_regular(destination, len(raw)) == raw:
                                continue
                        except (OSError, ValueError):
                            pass
                    target = stage / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    changed.add(relative)
                if legacy and vault.exists():
                    # User-requested migration: delete the old tree, no backup.
                    # rmtree unlinks child symlinks; ws.path rejects a linked root.
                    phase('Removing the managed legacy view')
                    shutil.rmtree(vault)
                vault.mkdir(parents=True, exist_ok=True)
                # A new-format pending state also marks legacy deletion complete.
                # Until it exists, an interrupted deletion is safe to retry.
                atomic_json(ws.path('.qecgraph/human-pending.json'), {**state, 'retired': retired})
                for relative in track(sorted(changed), 'Publishing Obsidian notes', unit='notes'):
                    atomic_bytes(ws.path('human/' + relative), (stage / relative).read_bytes())
                for relative in track(retired, 'Removing obsolete managed notes', unit='notes'):
                    _prune_note(ws, relative)
                phase('Recording human view publication')
                atomic_json(ws.path('.qecgraph/human-published.json'), state)
                ws.path('.qecgraph/human-pending.json').unlink(missing_ok=True)
            _operational(ws, latest, 'current', latest)
            return {'status': 'current', 'release_id': latest, 'generated_pages': len(pages)}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            message = str(exc).replace(str(ws.root), '<workspace>')
            return {'status': 'human_stale', 'release_id': latest, 'rendered_release_id': last_release,
                    'error': f'{type(exc).__name__}: {message}'}
