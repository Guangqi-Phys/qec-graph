"""One source-bound research-question note per registered paper."""
from __future__ import annotations

from ..core.progress import track

import json
import re
import unicodedata


from ..core.graph import hash_text
from ..core.language import require_english
from ..llm.extract import validate_extraction
from ..llm.review import proposal_bindings, read_bound_proposal

QUESTIONS = (
    ('What problem does the paper aim to solve?', ('problem',)),
    ('Why is this problem important?', ('motivation',)),
    ('Was the problem solved, and how?', ('approach', 'conclusion')),
    ('What intuitions or ideas underlie the approach?', ('intuition',)),
    ('What are the key assumptions?', ('assumption',)),
    ('What are the conclusions, and do they extend, strengthen or overturn prior results?', ('conclusion',)),
    ('What remains unresolved, and what follow-up questions arise?', ('open_question',)),
    ('What unusual or counterintuitive findings are reported?', ('surprising_result',)),
    ('What interesting secondary results are reported?', ('side_result',)),
)


def inline(value):
    return re.sub(r'([\\`*_{}\[\]()#+.!|<>])', r'\\\1', ' '.join(str(value).split()))


def quote_block(text):
    size = max((len(m[0]) for m in re.finditer(r'`+', text)), default=2)
    fence = '`' * max(3, size + 1)
    return f'{fence}latex\n{text}\n{fence}'


def yaml_value(value):
    return json.dumps(value, ensure_ascii=False).replace('\u0085', '\\u0085').replace(
        '\u2028', '\\u2028').replace('\u2029', '\\u2029')


def _component(value, fallback, limit=60):
    value = unicodedata.normalize('NFC', value or '')
    value = re.sub(r'[^\w-]+', '_', value, flags=re.UNICODE).strip('_-') or fallback
    while len(value.encode('utf-8')) > limit:
        value = value[:-1]
    return value.rstrip('_-') or fallback


def _surname(name):
    # Preserve an explicitly surname-first form. Otherwise keep the final
    # name, its conventional particles and hyphens, excluding generational suffixes.
    if ',' in name:
        return name.split(',', 1)[0].strip()
    parts = name.split()
    while len(parts) > 1 and parts[-1].rstrip('.').casefold() in {'jr', 'sr', 'ii', 'iii', 'iv'}:
        parts.pop()
    start = len(parts) - 1
    particles = {'da', 'das', 'de', 'del', 'della', 'den', 'der', 'di', 'dos', 'du', 'la', 'le', 'van', 'von'}
    while start > 0 and parts[start - 1].casefold() in particles:
        start -= 1
    return ' '.join(parts[start:])


def _arxiv_months(names):
    """Recognize modern arXiv YYMM identifiers in archived package names."""
    pattern = re.compile(r'(?<![A-Za-z0-9.])([0-9]{2})(0[1-9]|1[0-2])\.([0-9]{4,5})'
                         r'(?:v[1-9][0-9]*)?(?=$|[.\s_-])', re.IGNORECASE)
    months = set()
    for name in names:
        for match in pattern.finditer(name):
            yymm = int(match[1] + match[2])
            if yymm >= 704 and len(match[3]) == (5 if yymm >= 1501 else 4):
                months.add(f'20{match[1]}-{match[2]}')
    return months


def _tag(value):
    value = re.sub(r'[^\w/-]+', '-', unicodedata.normalize('NFC', value), flags=re.UNICODE).strip('-/')
    return ('topic-' + value if value.isdecimal() else value) if value else None


def _metadata(session, version, proposals):
    paper = session.knowledge.papers[version['id']]
    result = {field: paper[field] for field in ('title', 'authors', 'published_date', 'topics', 'link')}
    if 'title' not in paper['field_evidence']:
        result['title'] = None
    names = [name for m in session.state.get('materials', {}).values()
             if m.get('source_version_id') == version['id'] for name in m.get('original_names', [])]
    months = _arxiv_months(names)
    # An arXiv month identifies the initial submission, including for v2+.
    # Conflicting package months are unknown, not resolved by filename order.
    result['folder_date'] = next(iter(months)) if len(months) == 1 else (
        None if months else result['published_date'])
    if not result['topics'] and result['title']:
        # Only literal title topics are used without AI; do not infer a paper's
        # main subject from arbitrary mentions in its references or full text.
        topics = ('quantum error correction', 'surface codes?', 'color codes?', 'subsystem codes?',
                  'LDPC', 'decod(?:er|ers|ing)', 'fault[- ]toleran(?:t|ce)', 'hypergraph product', 'erasure', 'loss')
        result['topics'] = [m[0] for term in topics if (m := re.search(term, result['title'], re.IGNORECASE))]
    return result


def _version_order(version):
    match = re.fullmatch(r'v?([0-9]+)', version.get('upstream_version') or '')
    return (0, int(match[1]), version['id']) if match else (1, 0, version['id'])


def render_pages(session):
    proposals = []
    for binding, material in proposal_bindings(session.state).values():
        if binding['skill'] == 'extract_thoughts':
            proposal = read_bound_proposal(session.registry, binding, material)
            validate_extraction('extract_thoughts', {k: proposal[k] for k in ('items', 'unresolved', 'paper') if k in proposal})
            proposals.append(proposal)
    proposals.sort(key=lambda row: (row['source_version_id'], row['provenance']['run_id']))
    works = {}
    for version in session.state['versions'].values():
        works.setdefault(version['work_id'], []).append(version)
    records = [r for r in session.visible_research() if r['kind'] == 'research_thought']
    pages, targets, used = {}, {}, set()
    for work_id, versions in track(sorted(works.items()), 'Rendering paper thoughts', unit='papers'):
        versions.sort(key=_version_order)
        metadata = _metadata(session, versions[0], proposals)
        title = metadata['title'] or 'Untitled Paper'
        author = _surname(metadata['authors'][0]) if metadata['authors'] else 'UnknownAuthor'
        words = title.split()[:2]
        stem = '_'.join([_component(author, 'UnknownAuthor'), *(_component(w, 'Untitled', 45) for w in words)])
        date = metadata['folder_date'] or ''
        year, month = (date[:4] or 'unknown'), (date[5:7] or 'unknown')
        path = f'{year}/{month}/{stem}_thoughts.md'
        if path.casefold() in used:
            path = f'{year}/{month}/{stem}_{hash_text(work_id)[:12]}_thoughts.md'
        if path.casefold() in used:
            raise ValueError('Thought note filename collision')
        used.add(path.casefold())
        targets[work_id] = path
        tags = list(dict.fromkeys(tag for topic in metadata['topics'] if (tag := _tag(topic))))
        front = ['---', 'tags:' + ('' if tags else ' []')]
        front += ['  - ' + yaml_value(tag) for tag in tags]
        front += ['link: ' + yaml_value(metadata['link']), 'title: ' + yaml_value(metadata['title']),
                  'author:' + ('' if metadata['authors'] else ' []')]
        front += ['  - ' + yaml_value(name) for name in metadata['authors']]
        front += ['---', '', '# ' + inline(title), '', '> AI answers are proposals awaiting review. Read them alongside the cited source evidence.']
        if not metadata['title'] or not metadata['authors'] or not date or len(date) < 7:
            front += ['', '> Some bibliographic metadata is missing or submission dates conflict. Unknown fields use placeholders; ingestion dates are not paper dates.']
        if len(versions) > 1:
            front += ['', '> This paper has multiple registered versions. Each answer identifies its source version; conclusions are not merged.']
        sections = ['\n'.join(front)]
        for number, (question, categories) in enumerate(QUESTIONS, 1):
            sections.append(f'## {number}. {question}')
            answers = []
            missing = []
            for version in versions:
                version_label = version.get('upstream_version') or version['id']
                for proposal in proposals:
                    if proposal['source_version_id'] != version['id']:
                        continue
                    missing += [s for s in proposal['unresolved'] if any(s.startswith(c + ':') for c in categories)]
                    for item in proposal['items']:
                        if item['category'] in categories:
                            label = 'AI answer' if item['attribution'] == 'editorial_inference' else 'AI excerpt (author wording)'
                            answers.append(f'**{label} · proposed**\n\n{inline(item["statement"])}\n\n'
                                           f'Source evidence ({inline(", ".join(item["source_refs"]))}; version {inline(version_label)}):\n\n'
                                           + quote_block(item['source_quote']))
                for record in records:
                    data = record['data']
                    source = data.get('source_ref') or {}
                    if source.get('id') != version['id'] or source.get('revision') != version['snapshot_id'] or data['category'] not in categories:
                        continue
                    status = record.get('effective_review', {}).get('status') or record.get('review_status', 'proposed')
                    answers.append(f'**Research record · {inline(status)}**\n\n{inline(data["statement"])}\n\n'
                                   f'Source evidence (version {inline(version_label)}; {inline(data["attribution"])}):\n\n'
                                   + quote_block(data['source_quote']))
            sections.extend(answers or ['No answer available: not extracted or insufficient source evidence.'])
            if missing:
                sections.append('Unresolved:\n\n' + '\n'.join('- ' + inline(s) for s in sorted(set(missing))))
        sections.append(f'<!-- qecgraph work_sha256={hash_text(work_id)} release={session.release} -->')
        rendered = '\n\n'.join(sections) + '\n'
        require_english(path, 'note path')
        require_english(rendered, 'human note; run sync to refresh legacy AI proposals')
        pages[path] = rendered.encode('utf-8')
    return pages, targets
