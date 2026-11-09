"""Deterministic Obsidian view; its only knowledge input is a pinned machine release."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile

from .graph import hash_text, read_json
from .research import RELATIONS
from .status import eligible
from .transactions import atomic_bytes, atomic_json, writer_lock
from .workspace import HEX, Workspace, _read_regular, now
from .workspace_query import WorkspaceSession

FORMAT_V1 = 'qecgraph.human.v1'
FORMAT = 'qecgraph.human.v2'
LEGACY_PAGE = re.compile(r'generated/[a-z-]+/[a-z-]+--[0-9a-f]{64}\.md')
READABLE_PAGE = re.compile(r'generated/[a-z-]+/[a-z-]+--[a-z0-9-]+--([0-9a-f]{12,64})\.md')
GROUPS = {
    'source_artifact': 'sources', 'paper_version': 'sources', 'code_instance': 'codes',
    'code_mention': 'codes', 'code_presentation': 'codes', 'distance_claim': 'codes',
    'reported_experiment': 'experiments', 'performance_series': 'experiments', 'performance_point': 'experiments',
    'software_project': 'software', 'software_distribution': 'software', 'software_release': 'software',
    'algorithm': 'software', 'software_usage': 'software',
}


def _slug(value):
    return re.sub(r'[^a-z]+', '-', value.lower()).strip('-') or 'entity'


def _legacy_page(kind, identifier):
    return f'generated/{GROUPS.get(kind, "records")}/{_slug(kind)}--{hash_text(identifier)}.md'


def _entity_slug(identifier):
    # Use the stable ID or its embedded source label. Paper titles can change.
    if identifier.startswith('source-artifact:'):
        return 'package'
    text = identifier.rsplit(':label:', 1)[-1].lower()
    text = re.sub(r'[0-9a-f]{24,}', '', text)
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text[:40].rstrip('-') or 'entity'


def _assign_pages(entities, previous, bindings):
    targets = dict(bindings)
    used = set(previous) | set(bindings.values())
    for identifier, rows in sorted(entities.items()):
        if identifier in targets:
            continue
        kind = rows[0]['kind']
        base = f'generated/{GROUPS.get(kind, "records")}/{_slug(kind)}--{_entity_slug(identifier)}'
        identity = hash_text(identifier)
        for size in (12, 16, 24, 32, 64):
            path = f'{base}--{identity[:size]}.md'
            if path not in used:
                targets[identifier] = path
                used.add(path)
                break
        else:
            raise ValueError('Unable to allocate a unique generated page')
    return targets


def _owned_page(path):
    return LEGACY_PAGE.fullmatch(path) or READABLE_PAGE.fullmatch(path)


def _inline(value):
    return re.sub(r'([\\`*_{}\[\]()#+.!|<>])', r'\\\1', ' '.join(str(value).split()))


def _fenced(text, language='text'):
    size = max((len(m[0]) for m in re.finditer(r'`+', text)), default=2)
    fence = '`' * max(3, size + 1)
    return f'{fence}{language}\n{text}\n{fence}'


def _yaml_value(value):
    # JSON-quoted scalars and arrays avoid interpreting a paper title as YAML.
    return json.dumps(value, ensure_ascii=False).replace('\u0085', '\\u0085').replace(
        '\u2028', '\\u2028').replace('\u2029', '\\u2029')


def _heading(title, release, **metadata):
    fields = {'source_release': release, 'title': title, **metadata}
    front = '\n'.join(f'{key}: {_yaml_value(value)}' for key, value in fields.items())
    return f'---\n{front}\n---\n\n# {_inline(title)}\n\n' \
           '> Generated from a fixed QEC Graph release. Keep personal edits in `notes/`.'


def _link(path, label):
    display = re.sub(r'[\[\]|]', ' ', ' '.join(str(label).split())).strip()
    target = path.removesuffix('.md')
    return f'[[{target}|{display}]]' if display else f'[[{target}]]'


def _title(record):
    data = record.get('data', {})
    if record['kind'] == 'source_artifact':
        return record.get('work_id') or 'Source package ' + record['archive_sha256'][:12]
    title = ' '.join(str(record.get('title') or data.get('title') or data.get('name') or record['id']).split())
    return title if len(title) <= 160 else title[:159] + '…'


def _source_label(span):
    return f'{span["path"]}:{span["line_start"]}–{span["line_end"]}'


def _aliases(records):
    labels = set()
    for row in records:
        version = (row.get('source') or {}).get('source_version_id')
        prefix = f'{version}::' if version else ''
        labels.update(label.removeprefix(prefix) for label in row.get('labels', []))
    return sorted(labels)


def _review_status(record):
    return (record.get('effective_review', {}).get('status') or record.get('review_status')
            or record.get('data', {}).get('review_status') or 'unknown')


def _table(values):
    return '\n'.join(['| Field | Value |', '| --- | --- |',
                      *(f'| {_inline(name)} | {_inline(value)} |' for name, value in values)])


def _relation_index(edges):
    indexed = {}
    for edge in edges:
        if not eligible(edge):
            continue
        source, target = edge['source'], edge['target']
        if source == target:
            continue
        relation = edge['relation'].replace('_', ' ')
        forward = 'Proof text for' if edge['relation'] == 'proof_of' else relation.capitalize()
        reverse = 'Proof text' if edge['relation'] == 'proof_of' else 'Incoming ' + relation
        indexed.setdefault(source, []).append((forward, target, edge['status']))
        indexed.setdefault(target, []).append((reverse, source, edge['status']))
    return indexed


def _evidence_sections(record, session):
    from .corpus import occurrence_id

    sections = []
    for field, evidence in sorted(record.get('field_evidence', {}).items()):
        span = evidence.get('source_locator')
        if not span:
            continue
        if span['snapshot_id'] == session.source_snapshot_id(span['source_version_id']):
            try:
                exact = session.source_excerpt(occurrence_id(span['source_version_id'], span['node_id']),
                                               span['char_start'], span['char_end'])
            except ValueError:
                pass
            else:
                sections.append(f'**{_inline(field)}** — {_inline(_source_label(exact["source"]))}\n\n'
                                + _excerpt(exact['latex'], 400))
                continue
        sections.append(f'**{_inline(field)}** — bound to a historical source snapshot.')
    return sections


def _excerpt(text, limit):
    return _fenced(text[:limit] + ('\n[… excerpt]' if len(text) > limit else ''), 'latex')


def _record_sections(record, session, targets, titles, relations, visible_revisions, section_level):
    span = record.get('source')
    fields = [('Kind', record['kind']), ('Review', _review_status(record)),
              ('Verification', record.get('verification_status') or 'unknown')]
    if 'revision' in record:
        fields.append(('Revision', record['revision']))
    if span:
        fields.append(('Source', _source_label(span)))
    if record['kind'] == 'source_artifact':
        fields += [('Processing', record['status']), ('Semantic extraction', record['semantic_status']),
                   ('Original package SHA-256', record['archive_sha256'])]
    sections = [_table(fields)]
    if record['kind'] == 'source_artifact':
        source = record.get('source_version_id')
        if source in targets:
            sections.append('Parsed source: ' + _link(targets[source], titles[source]))
        return sections
    if span:
        sections += [f'{section_level} Source text', _excerpt(record.get('latex', ''), 800)]
    data = record.get('data', {})
    links = list(relations.get(record['id'], []))
    for relation in RELATIONS.get(record['kind'], {}):
        value = data.get(relation)
        for binding in value if isinstance(value, list) else [value] if value else []:
            if (binding['id'], binding['revision']) in visible_revisions:
                links.append((relation.replace('_', ' ').capitalize(), binding['id'], 'revision ' + binding['revision']))
    rows = [f'- {_inline(relation)} → {_link(targets[target], titles[target])} ({_inline(detail)})'
            for relation, target, detail in sorted(set(links)) if target in targets]
    if rows:
        sections += [f'{section_level} Relations', '\n'.join(rows)]
    evidence = _evidence_sections(record, session)
    if evidence:
        sections += [f'{section_level} Source evidence', *evidence]
    if data:
        raw = _fenced(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), 'json')
        sections.append(f'<details>\n<summary>Raw record data</summary>\n\n{raw}\n\n</details>')
    return sections


def _status_page(release, materials):
    rows = [('Registered packages', len(materials)),
            ('Structurally indexed', sum(bool(row['processing_completed']) for row in materials)),
            ('Source version conflicts', sum(bool(row['source_version_conflict']) for row in materials))]
    return '\n\n'.join([_heading('Status', release), _table(rows),
                        '## Reading the graph',
                        '- **Extracted**: syntax located in a source; claims still require review.\n'
                        '- **Proposed**: a candidate record that has not been reviewed.\n'
                        '- **Reviewed**: an explicit decision is bound to the record and source revision.\n'
                        '- A proof link identifies its target; it is not a verification result.']) + '\n'


def _render(session, previous, bindings):
    materials = session.material_records()
    research = session.visible_research()
    visible_revisions = {(record['id'], record['revision']) for record in research}
    entities = {}
    for row in [*materials, *research]:
        entities.setdefault(row['id'], []).append(row)
    nodes, edges = session.projected_graph(parser_kinds={'theorem', 'lemma', 'definition', 'proposition',
                                                        'corollary', 'proof'})
    for node in nodes:
        entities.setdefault(node['id'], []).append(node)
    all_targets = _assign_pages(entities, previous, bindings)
    targets = {identifier: all_targets[identifier] for identifier in entities}
    titles = {identifier: _title(rows[0]) for identifier, rows in entities.items()}
    relations = _relation_index(edges)
    pages, index = {}, {}
    for identifier, records in sorted(entities.items()):
        path, title, first = targets[identifier], titles[identifier], records[0]
        kind = first['kind']
        index.setdefault(path.split('/')[1], {}).setdefault(kind, []).append((title, path))
        metadata = {'kind': kind, 'entity_id': identifier, 'aliases': _aliases(records),
                    'tags': ['qec/' + _slug(kind), 'qec/review/' + _slug(_review_status(first)),
                             'qec/release/' + session.release[:12]]}
        if first.get('source'):
            metadata['source'] = _source_label(first['source'])
        sections = [_heading(title, session.release, **metadata)]
        for record in records:
            if 'revision' in record and len(records) > 1:
                sections.append(f'## Revision {_inline(record["revision"])}')
            level = '###' if len(records) > 1 else '##'
            sections.extend(_record_sections(record, session, targets, titles, relations, visible_revisions, level))
        pages[path] = ('\n\n'.join(sections) + '\n').encode()
        old = _legacy_page(kind, identifier)
        if old in previous:
            pages[old] = (_heading(title, session.release) + '\n\nThis page moved to '
                          + _link(path, title) + '.\n').encode()
    for path in sorted(previous - pages.keys()):
        index.setdefault(path.split('/')[1], {}).setdefault('archived', []).append(('Archived entity', path))
        pages[path] = (_heading('Archived entity', session.release)
                       + '\n\nThis stable page is retained for existing links. The entity is absent from this release.\n').encode()
    pages['generated/Status.md'] = _status_page(session.release, materials).encode()
    root = [_heading('QEC Graph', session.release), 'Open a category below. Personal notes live in `notes/`.',
            f'- {_link("generated/Status.md", "Release status and legend")}']
    for group, by_kind in sorted(index.items()):
        path = f'generated/{group}/Index.md'
        body = [_heading(group.title(), session.release)]
        for kind, rows in sorted(by_kind.items()):
            body.append(f'## {_inline(kind.replace("_", " ").capitalize())} ({len(rows)})\n')
            for title, target in sorted(rows, key=lambda r: (r[0].casefold(), r[1])):
                if target not in pages:
                    raise ValueError('Renderer generated a missing internal target')
                body.append(f'- {_link(target, title)}')
        pages[path] = ('\n'.join(body) + '\n').encode()
        root.append(f'- {_link(path, group.title())} ({sum(map(len, by_kind.values()))})')
    return pages, ('\n'.join(root) + '\n').encode(), all_targets


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
        return {'release_id': None, 'pages': [], 'entity_pages': {}}
    data = read_json(path)
    if (not isinstance(data, dict) or data.get('format') not in (FORMAT_V1, FORMAT)
            or not isinstance(data.get('release_id'), str) or not HEX.fullmatch(data['release_id'])):
        raise ValueError('Invalid renderer history')
    owned = LEGACY_PAGE.fullmatch if data['format'] == FORMAT_V1 else _owned_page
    if not isinstance(data.get('pages'), list) or any(not isinstance(x, str) or not owned(x) for x in data['pages']):
        raise ValueError('Renderer history has an unowned path')
    if data['format'] == FORMAT_V1:
        return {**data, 'entity_pages': {}}
    bindings = data.get('entity_pages')
    if not isinstance(bindings, dict):
        raise ValueError('Invalid renderer page bindings')
    seen, paths = set(), set(data['pages'])
    for identifier, relative in bindings.items():
        match = READABLE_PAGE.fullmatch(relative) if isinstance(relative, str) else None
        if (not identifier or not match or relative in seen or relative not in paths
                or not hash_text(identifier).startswith(match[1])):
            raise ValueError('Invalid renderer page binding')
        seen.add(relative)
    return data


def _merge_bindings(published, pending):
    result = dict(published)
    reverse = {path: identifier for identifier, path in result.items()}
    for identifier, path in pending.items():
        if result.get(identifier, path) != path or reverse.get(path, identifier) != identifier:
            raise ValueError('Conflicting renderer histories')
        result[identifier] = path
        reverse[path] = identifier
    return result


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
            bindings = _merge_bindings(past['entity_pages'], interrupted['entity_pages'])
            previous = set(past['pages']) | set(interrupted['pages'])
            pages, index, targets = _render(session, previous, bindings)
            state = {'format': FORMAT, 'release_id': latest, 'pages': sorted(p for p in pages if _owned_page(p)),
                     'entity_pages': dict(sorted(targets.items()))}
            staging_root = ws.path('.qecgraph/human-staging')
            staging_root.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='render-', dir=staging_root) as staging:
                stage = Path(staging)
                changed = set()
                for relative, raw in {**pages, 'Index.md': index}.items():
                    destination = ws.path('human/' + relative)
                    if _owned_page(relative) and relative not in previous and destination.exists():
                        raise ValueError('A generated page would overwrite a file outside the renderer history')
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
                # Publish readable targets before redirect pages and indexes.
                for relative in sorted(changed - {'Index.md'}, key=lambda path: (not READABLE_PAGE.fullmatch(path), path)):
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
