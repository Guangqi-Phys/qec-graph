"""Verify a proposed partition of a literal TeX body against the source bytes."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from ..core.coordinates import SourceLines
from .reading import reading_projection

STRUCTURE_SCHEMA = 'qecgraph.structure_recovery'
STRUCTURE_SKILL = 'recover_structure'
STRUCTURE_VERSION = 2
_KINDS = frozenset({'section', 'paragraph', 'definition', 'lemma', 'theorem', 'proposition',
                    'corollary', 'conjecture', 'proof', 'equation', 'table', 'figure',
                    'remark', 'example', 'bibliography', 'unknown'})
_LEVELS = {'part': -1, 'chapter': 0, 'section': 1, 'subsection': 2, 'subsubsection': 3,
           'paragraph': 4, 'subparagraph': 5}
_SECTION = re.compile(r'[ \t]*\\(' + '|'.join(_LEVELS) + r')\*?(?:\[[^\]\r\n]*\])?'
                      r'\{([^{}\r\n]+)\}[ \t]*(?:%[^\r\n]*)?[\r\n]*')
_BOUNDARY = re.compile(r'[ \t]*\\(begin|end)\s*\{(document|thebibliography)\}'
                       r'(?:\{[^{}\r\n]+\})?[ \t]*(?:%[^\r\n]*)?[\r\n]*')
_LITERAL = re.compile(r'(?m)^[ \t]*\\(begin|end)\s*\{(verbatim\*?|Verbatim|BVerbatim|LVerbatim|'
                      r'lstlisting|minted|comment|filecontents\*?)\}')
_EXTERNAL_BODY = re.compile(r'\\(?:input|include|subfile|import|subimport|includefrom|inputfrom|'
                            r'subincludefrom|subinputfrom|includeonly|endinput)(?![A-Za-z@])')
_DYNAMIC_BODY = re.compile(r'\\(?:def|gdef|edef|xdef|let|catcode|scantokens|csname|newcommand|'
                           r'providecommand|renewcommand|newenvironment|renewenvironment)(?![A-Za-z@])')
_HEX = re.compile(r'[0-9a-f]{64}')


class StructureError(ValueError):
    """The proposed structure cannot be safely applied."""


class StructureIneligible(StructureError):
    """No bounded literal source body is available for recovery."""


class StructureNeedsReview(StructureError):
    """A provider declined to classify this body."""


@dataclass(frozen=True)
class BodyEvidence:
    entry: str
    text: str
    sha256: str
    offsets: tuple[int, ...]
    first_line: int
    last_line: int
    sections: dict[int, tuple[str, int]]
    bibliographies: tuple[tuple[int, int], ...]

    def line(self, number):
        return self.text[self.offsets[number - 1]:self.offsets[number]]

    def request(self):
        return {'schema': 'qecgraph.numbered_tex_body', 'entry': self.entry, 'source_sha256': self.sha256,
                'first_line': self.first_line, 'last_line': self.last_line,
                'section_lines': sorted(self.sections),
                'bibliography_ranges': [list(bounds) for bounds in self.bibliographies],
                'lines': [[line, self.line(line)] for line in range(self.first_line, self.last_line + 1)]}


def body_evidence(entry, raw):
    text = raw.decode('utf-8')
    if _EXTERNAL_BODY.search(text):
        raise StructureIneligible('External TeX body inputs require local parsing')
    offsets = (0, *(match.end() for match in re.finditer(r'\n', text)), len(text))
    document = []
    bibliographies = []
    sections = {}
    literal = None
    bibliography = None
    for line, (a, b) in enumerate(zip(offsets, offsets[1:]), start=1):
        row = text[a:b]
        marker = _LITERAL.match(row)
        if literal:
            if marker and marker.groups() == ('end', literal):
                literal = None
            continue
        if marker and marker[1] == 'begin':
            literal = marker[2]
            continue
        match = _BOUNDARY.fullmatch(row)
        if match and match[2] == 'document':
            if bibliography is not None:
                raise StructureIneligible('The bibliography crosses a document boundary')
            document.append((match[1], line))
        elif match and match.groups() == ('begin', 'thebibliography') and bibliography is None:
            bibliography = line
        elif match and match.groups() == ('end', 'thebibliography') and bibliography is not None:
            bibliographies.append((bibliography, line))
            bibliography = None
        elif match:
            raise StructureIneligible('Ambiguous bibliography boundaries')
        elif bibliography is None and (section := _SECTION.fullmatch(row)):
            sections[line] = section[2], _LEVELS[section[1]]
    if literal or bibliography is not None or [kind for kind, _ in document] != ['begin', 'end']:
        raise StructureIneligible('A unique literal document body is required')
    first, last = document[0][1] + 1, document[1][1] - 1
    if first > last or not text[offsets[first - 1]:offsets[last]].strip():
        raise StructureIneligible('The document body is empty')
    if any(a < first or b > last for a, b in bibliographies):
        raise StructureIneligible('A bibliography lies outside the document body')
    # Skip literal bibliography shims while checking the prose for dynamic commands.
    start = first
    for a, b in [*bibliographies, (last + 1, last + 1)]:
        if _DYNAMIC_BODY.search(text[offsets[start - 1]:offsets[a - 1]]):
            raise StructureIneligible('Dynamic TeX declarations in the body require local parsing')
        start = b + 1
    return BodyEvidence(entry, text, hashlib.sha256(raw).hexdigest(), offsets, first, last,
                        {i: value for i, value in sections.items() if first <= i <= last},
                        tuple(bibliographies))


def validate_plan(evidence, plan):
    if not isinstance(plan, dict) or set(plan) != {'status', 'blocks'} or not isinstance(plan['blocks'], list):
        raise StructureError('Invalid structure plan fields')
    if plan['status'] == 'needs_review' and not plan['blocks']:
        raise StructureNeedsReview('The structure plan needs review')
    if plan['status'] != 'ready' or not 1 <= len(plan['blocks']) <= 512:
        raise StructureError('The structure plan is incomplete')
    cursor = evidence.first_line
    found_bibliographies = []
    found_sections = []
    ranges = []
    for block in plan['blocks']:
        if not isinstance(block, dict) or set(block) != {'kind', 'first_line', 'last_line'}:
            raise StructureError('Invalid structure block fields')
        kind, first, last = block['kind'], block['first_line'], block['last_line']
        if (not isinstance(kind, str) or kind not in _KINDS or type(first) is not int
                or type(last) is not int or not cursor == first <= last <= evidence.last_line):
            raise StructureError('Structure blocks must cover the body exactly once in source order')
        if kind == 'bibliography':
            found_bibliographies.append((first, last))
        if kind == 'section':
            if first != last or first not in evidence.sections:
                raise StructureError('A section requires a literal single-line heading')
            found_sections.append(first)
        cursor = last + 1
        ranges.append((kind, first, last))
    if cursor != evidence.last_line + 1:
        raise StructureError('Structure plan leaves body lines uncovered')
    if found_bibliographies != list(evidence.bibliographies):
        raise StructureError('Bibliography ranges must match literal source boundaries')
    if found_sections != sorted(evidence.sections):
        raise StructureError('Section ranges must cover the literal heading anchors')
    return ranges


def parsed_structure(evidence, binding):
    """Materialize the existing parse-result contract using original slices only."""
    if (not isinstance(binding, dict)
            or set(binding) != {'schema', 'entry', 'source_sha256', 'skill', 'skill_version',
                                'model', 'prompt_sha256', 'plan'}
            or binding['schema'] != STRUCTURE_SCHEMA or binding['entry'] != evidence.entry
            or binding['source_sha256'] != evidence.sha256 or binding['skill'] != STRUCTURE_SKILL
            or binding['skill_version'] not in {1, STRUCTURE_VERSION}
            or not isinstance(binding['model'], str) or not binding['model']
            or not isinstance(binding['prompt_sha256'], str) or not _HEX.fullmatch(binding['prompt_sha256'])):
        raise StructureError('Structure plan is not bound to this source and skill')
    ranges = validate_plan(evidence, binding['plan'])
    lines = SourceLines(evidence.text)
    blocks = []
    sections = []

    def span(a, b):
        return {'path': evidence.entry, 'char_start': a, 'char_end': b,
                'line_start': lines.line_at(a), 'line_end': lines.line_at(b - 1)}

    for index, (classification, first, last) in enumerate(ranges, start=1):
        a, b = evidence.offsets[first - 1], evidence.offsets[last]
        latex = evidence.text[a:b]
        bibliography = classification == 'bibliography'
        kind = 'paragraph' if classification in {'bibliography', 'unknown'} else classification
        _, citations = reading_projection(latex, kind=kind, bibliography=bibliography)
        title, level = evidence.sections[first] if kind == 'section' else ('', None)
        if level is not None:
            while sections and sections[-1][0] >= level:
                sections.pop()
        block = {'key': f'block-{index}', 'kind': kind, 'latex': latex, 'source': span(a, b), 'order': index,
                 'parent_key': sections[-1][1] if sections else None, 'title_tex': title, 'labels': [],
                 'source_role': 'bibliography' if bibliography else 'body',
                 'structure_classification': classification,
                 'references': [{'kind': 'cite', 'targets': keys, 'macro': macro,
                                 'source': span(a + start, a + end)}
                                for start, end, macro, keys in citations]}
        blocks.append(block)
        if level is not None:
            sections.append((level, block['key']))
    return {'entry': evidence.entry,
            'files': [{'path': evidence.entry, 'text': evidence.text, 'sha256': evidence.sha256, 'encoding': 'utf-8'}],
            'blocks': blocks, 'includes': [], 'resources': [], 'structure_recovery': binding,
            'diagnostics': [{'severity': 'warning', 'code': 'ai_structure_proposed', 'source': None,
                             'message': 'Source ranges were checked. AI block kinds are proposed; only literal citations and headings were recovered.'}]}
