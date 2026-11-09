"""Deterministic Obsidian view; its only knowledge input is a pinned machine release."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile

from .graph import hash_text, read_json
from .research import RELATIONS
from .transactions import atomic_bytes, atomic_json, writer_lock
from .workspace import HEX, Workspace, _read_regular, now
from .workspace_query import WorkspaceSession

FORMAT = 'qecgraph.human.v1'
PAGE = re.compile(r'generated/[a-z-]+/[a-z-]+--[0-9a-f]{64}\.md')
GROUPS = {
    'source_artifact': 'sources', 'paper_version': 'sources', 'code_instance': 'codes',
    'code_mention': 'codes', 'code_presentation': 'codes', 'distance_claim': 'codes',
    'reported_experiment': 'experiments', 'performance_series': 'experiments', 'performance_point': 'experiments',
    'software_project': 'software', 'software_distribution': 'software', 'software_release': 'software',
    'algorithm': 'software', 'software_usage': 'software',
}


def _slug(value):
    return re.sub(r'[^a-z]+', '-', value.lower()).strip('-') or 'entity'


def _page(kind, identifier):
    return f'generated/{GROUPS.get(kind, "records")}/{_slug(kind)}--{hash_text(identifier)}.md'


def _inline(value):
    return re.sub(r'([\\`*_{}\[\]()#+.!|<>])', r'\\\1', ' '.join(str(value).split()))


def _fenced(text, language='text'):
    size = max((len(m[0]) for m in re.finditer(r'`+', text)), default=2)
    fence = '`' * max(3, size + 1)
    return f'{fence}{language}\n{text}\n{fence}'


def _heading(title, release):
    return f'---\nsource_release: "{release}"\n---\n\n# {_inline(title)}\n\n' \
           '> Generated from a fixed QEC Graph release. Keep personal edits in `notes/`.\n'


def _link(path):
    return f'[[{path.removesuffix(".md")}]]'


def _render(session, previous):
    entities = {}
    for row in [*session._materials.values(), *session.visible.values()]:
        entities.setdefault(row['id'], []).append(row)
    for node in session.graph.source.graph['nodes']:
        if node['origin'] == 'registry' or node['kind'] in {'theorem', 'lemma', 'definition', 'proposition', 'corollary'}:
            entities.setdefault(node['id'], []).append(node)
    targets = {identifier: _page(rows[0]['kind'], identifier) for identifier, rows in entities.items()}
    pages, index = {}, {}
    for identifier, records in sorted(entities.items()):
        path = targets[identifier]
        row = records[0]
        title = row.get('title') or row.get('data', {}).get('name') or identifier
        index.setdefault(path.split('/')[1], []).append((title, path))
        sections = [_heading(title, session.release), f'Kind: **{_inline(row["kind"])}**\n']
        for record in records:
            if 'revision' in record:
                sections.append(f'## Revision {_inline(record["revision"])}\n')
            if record['kind'] == 'source_artifact':
                sections.append(f'Processing status: **{_inline(record["status"])}**  \n'
                                f'Semantic status: **{_inline(record["semantic_status"])}**  \n'
                                f'Original package SHA-256: {_inline(record["archive_sha256"])}\n')
                source = targets.get(record.get('source_version_id'))
                if source:
                    sections.append('Parsed source: ' + _link(source) + '\n')
                continue
            if record.get('source'):
                span = record['source']
                sections.append(f'TeX: {_inline(span["path"])}:{span["line_start"]}–{span["line_end"]}\n')
                latex = record.get('latex', '')
                sections.append(_fenced(latex[:800] + ('\n[… excerpt]' if len(latex) > 800 else ''), 'latex'))
            data = record.get('data', {})
            if data:
                sections.append(_fenced(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), 'json'))
            for relation in RELATIONS.get(record['kind'], {}):
                value = data.get(relation)
                for binding in value if isinstance(value, list) else [value] if value else []:
                    target = targets.get(binding['id'])
                    if target:
                        sections.append(f'{_inline(relation)}: {_link(target)} (revision {_inline(binding["revision"])})\n')
            for field, evidence in sorted(record.get('field_evidence', {}).items()):
                span = evidence.get('source_locator')
                if span:
                    if span['snapshot_id'] != session.state['versions'].get(span['source_version_id'], {}).get('snapshot_id'):
                        sections.append(f'{_inline(field)}: bound to a historical source snapshot.\n')
                        continue
                    from .corpus import occurrence_id
                    try:
                        exact = session._source(occurrence_id(span['source_version_id'], span['node_id']),
                                                span['char_start'], span['char_end'])
                    except ValueError:
                        sections.append(f'{_inline(field)}: bound to a historical source snapshot.\n')
                    else:
                        sections.append(f'{_inline(field)}: {_inline(span["path"])}:{exact["source"]["line_start"]}\n'
                                        + _fenced(exact['latex'][:400], 'latex'))
        pages[path] = '\n'.join(sections).encode()
    for path in sorted(previous - pages.keys()):
        index.setdefault(path.split('/')[1], []).append(('Archived entity', path))
        pages[path] = (_heading('Archived entity', session.release)
                       + '\nThis stable page is retained for existing links. The entity is absent from this release.\n').encode()
    root = [_heading('QEC Graph', session.release), 'Open a category below. Personal notes live in `notes/`.\n']
    for group, rows in sorted(index.items()):
        path = f'generated/{group}/Index.md'
        body = [_heading(group.title(), session.release)]
        for title, target in sorted(rows, key=lambda r: (str(r[0]).casefold(), r[1])):
            if target not in pages:
                raise ValueError('Renderer generated a missing internal target')
            body.append(f'- {_link(target)} — {_inline(title)}')
        pages[path] = ('\n'.join(body) + '\n').encode()
        root.append(f'- {_link(path)} ({len(rows)})')
    return pages, ('\n'.join(root) + '\n').encode()


def _operational(ws, release, human_status, last_release):
    path = ws.path('machine/operational/status.json')
    existing = read_json(path) if path.is_file() else {}
    atomic_json(path, {'observed_at': now(), 'release_id': release,
                       'counts': existing.get('counts', {}) if existing.get('release_id') == release else {},
                       'human': {'status': human_status, 'target_release_id': release,
                                 'rendered_release_id': last_release}})


def _history(ws, name):
    path = ws.path('.qecgraph/' + name + '.json')
    if not path.exists():
        return {'release_id': None, 'pages': []}
    data = read_json(path)
    if data.get('format') != FORMAT or not isinstance(data.get('release_id'), str) or not HEX.fullmatch(data['release_id']):
        raise ValueError('Invalid renderer history')
    if not isinstance(data.get('pages'), list) or any(not isinstance(x, str) or not PAGE.fullmatch(x) for x in data['pages']):
        raise ValueError('Renderer history has an unowned path')
    return data


def build_human(workspace=None, release=None):
    ws = Workspace(workspace)
    ws.config()
    with writer_lock(ws.path('.qecgraph')), writer_lock(ws.registry.root):
        _, latest = ws.registry.read()
        if release is not None and release != latest:
            return {'status': 'superseded', 'target_release_id': release, 'current_release_id': latest}
        past = _history(ws, 'human-published')
        interrupted = _history(ws, 'human-pending')
        try:
            _operational(ws, latest, 'human_stale', past['release_id'])
            session = WorkspaceSession(ws.registry.root, latest)
            pages, index = _render(session, set(past['pages']) | set(interrupted['pages']))
            state = {'format': FORMAT, 'release_id': latest, 'pages': sorted(p for p in pages if PAGE.fullmatch(p))}
            staging_root = ws.path('.qecgraph/human-staging')
            staging_root.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='render-', dir=staging_root) as staging:
                stage = Path(staging)
                changed = set()
                for relative, raw in {**pages, 'Index.md': index}.items():
                    destination = ws.path('human/' + relative)
                    try:
                        if _read_regular(destination, len(raw)) == raw:
                            continue
                    except (OSError, ValueError):
                        pass
                    target = stage / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    changed.add(relative)
                ws.path('human/generated/.qecgraph-manifest.json')
                notes = ws.path('human/notes')
                notes.mkdir(parents=True, exist_ok=True)
                manifest = {**state, 'outputs': {name: hash_text(raw.decode('utf-8')) for name, raw in sorted(pages.items())}}
                atomic_json(ws.path('.qecgraph/human-pending.json'), state)
                for relative in sorted(changed - {'Index.md'}):
                    atomic_bytes(ws.path('human/' + relative), (stage / relative).read_bytes())
                atomic_json(ws.path('human/generated/.qecgraph-manifest.json'), manifest)
                if 'Index.md' in changed:
                    atomic_bytes(ws.path('human/Index.md'), (stage / 'Index.md').read_bytes())
                atomic_json(ws.path('.qecgraph/human-published.json'), state)
                ws.path('.qecgraph/human-pending.json').unlink(missing_ok=True)
            _operational(ws, latest, 'current', latest)
            return {'status': 'current', 'release_id': latest, 'generated_pages': len(pages)}
        except (OSError, ValueError, KeyError, TypeError):
            # Only fixed counts/status cross the worker boundary; no private path, content or traceback.
            return {'status': 'human_stale', 'release_id': latest, 'rendered_release_id': past['release_id']}
