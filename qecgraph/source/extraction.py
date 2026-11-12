"""Conservative, offline research proposals from exact TeX source spans."""
from __future__ import annotations

import re

from ..core.graph import canonical, hash_text
from ..domain.research import make_record

RULE_VERSION = 'code-mention-rules-v3'
TOKEN = r'(?:\d{1,8}|[nkdKrR](?:\s*>\s*0)?)'
TUPLE = rf'{TOKEN}(?:\s*,\s*{TOKEN}){{2,3}}'
NOTATION = re.compile(rf'\[\[\s*(?P<sq>{TUPLE})\s*\]\]|\(\(\s*(?P<round>{TUPLE})\s*\)\)'
                      rf'|(?<!\[)\[\s*(?P<single>{TUPLE})\s*\](?!\])')
QUANTUM_CONTEXT = re.compile(r'\b(?:CSS|quantum|stabili[sz]er)\s+codes?\b', re.I)
SUBSYSTEM = re.compile(r'\bsubsystem\s+codes?\b', re.I)
NONADDITIVE = re.compile(r'\bnon[- ]?additive\b', re.I)
CLASSICAL_CONTEXT = re.compile(r'\b(?:classical|BCH)\s+(?:seed|codes?)\b', re.I)
FRAGMENTS = {'paragraph', 'definition', 'lemma', 'theorem', 'proposition', 'corollary', 'remark', 'table'}
FIELDS = ('reported_notation', 'code_type', 'parameter_kind', 'n', 'k', 'K', 'r', 'R')


class NotationMatch:
    """A normalized match whose whole-span coordinates address original TeX."""

    def __init__(self, match, text, positions):
        self.match, self.text, self.positions = match, text, positions
        self.lastgroup = match.lastgroup

    def start(self):
        return self.positions[self.match.start()][0]

    def end(self):
        return self.positions[self.match.end() - 1][1]

    def __getitem__(self, group):
        return self.text[self.start():self.end()] if group == 0 else self.match[group]


def notation_matches(text):
    """Normalize bracket/spacing syntax for matching only, preserving source offsets."""
    replacements = {r'\llbracket': '[[', r'\rrbracket': ']]', r'[\![': '[[', r']\!]': ']]',
                    r'\,': '', r'\;': '', '~': ' '}
    pattern = '|'.join(re.escape(key) for key in replacements)
    normalized, positions, pos = [], [], 0
    for token in re.finditer(pattern, text):
        for index in range(pos, token.start()):
            normalized.append(text[index])
            positions.append((index, index + 1))
        for char in replacements[token[0]]:
            normalized.append(char)
            positions.append(token.span())
        pos = token.end()
    for index in range(pos, len(text)):
        normalized.append(text[index])
        positions.append((index, index + 1))
    for match in NOTATION.finditer(''.join(normalized)):
        yield NotationMatch(match, text, positions)


def _tuple_kind(node, match, arity):
    body = node['latex']
    line_start = body.rfind('\n', 0, match.start()) + 1
    line_end = body.find('\n', match.end())
    context = body[line_start:line_end if line_end != -1 else len(body)]
    if node['kind'] == 'table':
        # Narrow labeled-column rule. An unrelated table or ambiguous column is left untyped.
        if all(re.search(cue, body, re.I) for cue in (r'Subsystem Code', r'Parent', r'BCH Code')):
            col = body[line_start:match.start()].count('&')
            if col == 0 and match.lastgroup in ('sq', 'round') and arity == 4:
                return 'quantum', 'subsystem_log_dimensions' if match.lastgroup == 'sq' else 'subsystem_dimensions'
            if col == 1 and match.lastgroup == 'single' and arity == 3:
                return 'classical', 'classical_seed_parameters'
        return None, None
    if len(list(notation_matches(context))) != 1:
        return None, None
    classical = CLASSICAL_CONTEXT.search(context)
    subsystem = SUBSYSTEM.search(context)
    nonadditive = NONADDITIVE.search(context)
    quantum = QUANTUM_CONTEXT.search(context) or subsystem or nonadditive
    if classical and not quantum and match.lastgroup == 'single' and arity == 3:
        return 'classical', 'classical_seed_parameters'
    if not quantum or classical:
        return None, None
    if subsystem and arity == 4 and match.lastgroup != 'single':
        return 'quantum', 'subsystem_log_dimensions' if match.lastgroup == 'sq' else 'subsystem_dimensions'
    if nonadditive and arity == 3 and match.lastgroup == 'round':
        return 'quantum', 'nonadditive_dimension'
    if QUANTUM_CONTEXT.search(context) and arity == 3 and match.lastgroup == 'sq' and not nonadditive:
        return 'quantum', 'quantum_logical_count'
    return None, None


def _locator(node, source_id, snapshot, start, end):
    return {'source_version_id': source_id, 'snapshot_id': snapshot, 'node_id': node['id'],
            'node_content_sha256': node['content_sha256'], 'path': node['source']['path'],
            'char_start': start, 'char_end': end}


def proposals(graph, version):
    """Pass 1 locates tuples; pass 2 applies local wording or labeled column rules."""
    source_id, snapshot = version['id'], version['snapshot_id']
    origin = {'id': source_id, 'revision': snapshot}
    source = make_record('paper_version', source_id, snapshot,
                         {'work_id': version['work_id'], 'upstream_version': version['upstream_version'],
                          'source_snapshot_id': snapshot}, source=origin, method='workspace_source_registry')
    if graph.get('structure_recovery'):
        return [source]
    candidates = {}
    for node in graph['nodes']:
        span = node.get('source')
        if node['kind'] not in FRAGMENTS or not span or node['origin'] != 'parser':
            continue
        for match in notation_matches(node['latex']):
            if match.lastgroup == 'single' and node['kind'] != 'table' and not CLASSICAL_CONTEXT.search(node['latex']):
                continue  # Bracketed citations and optional TeX arguments are common.
            start = span['char_start'] + match.start()
            location = (span['path'], start, start + len(match[0]))
            rank = (node['kind'] != 'table', len(node['latex']), node['id'])
            previous = candidates.get(location)
            if previous is None or rank < previous[0]:
                candidates[location] = (rank, node, match)
    records = [source]
    for (path, start, end), (_, node, match) in sorted(candidates.items()):
        terms = [v.strip() for v in match[match.lastgroup].split(',')]
        domain, semantics = _tuple_kind(node, match, len(terms))
        data = {'source_ref': origin, 'code_ref': None, 'reported_notation': match[0],
                'code_type': domain, 'parameter_kind': semantics, 'n': None,
                'k': None, 'K': None, 'r': None, 'R': None,
                'distance_interpretation': None, 'review_status': 'proposed'}
        if semantics:
            roles = {
                'quantum_logical_count': ('n', 'k'),
                'subsystem_log_dimensions': ('n', 'k', 'r'),
                'subsystem_dimensions': ('n', 'K', 'R'),
                'nonadditive_dimension': ('n', 'K'),
                'classical_seed_parameters': ('n', 'k_classical'),
            }[semantics]
            if 'k_classical' in roles:
                data['k_classical'] = None
            for role, value in zip(roles, terms):
                if value.isdecimal():
                    data[role] = int(value)
            n, k = data['n'], data['k']
            if n is not None and (n < 1 or (k is not None and k + (data['r'] or 0) > n)):
                for role in roles:
                    data[role] = None
        locator = _locator(node, source_id, snapshot, start, end)
        context = _locator(node, source_id, snapshot, node['source']['char_start'], node['source']['char_end'])
        evidence = {f'/data/{field}': {'status': 'known', 'source_ref': origin,
                                      'source_locator': locator if field == 'reported_notation' else context,
                                      'method': RULE_VERSION}
                    for field in (*FIELDS, 'k_classical') if data.get(field) is not None}
        identifier = 'mention:' + hash_text(canonical([source_id, path, start, end]))
        revision = hash_text(canonical([snapshot, RULE_VERSION, data, locator, context]))
        records.append(make_record('code_parameters_mention', identifier, revision, data, source=origin,
                                   method=RULE_VERSION, evidence=evidence))
    return records
