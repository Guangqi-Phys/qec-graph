"""Literal source metadata; no TeX execution, identity inference or remote lookup."""
from datetime import datetime
import re
from pylatexenc.latex2text import LatexNodes2Text
from .reading import _group
from .contracts import PaperMetadata


def _plain(value: str) -> str:
    return ' '.join(LatexNodes2Text().latex_to_text(value).split())


def _date(value: str | None) -> str | None:
    if not value or '\\' in value:
        return None
    for pattern, output in (('%Y-%m-%d', '%Y-%m-%d'), ('%Y/%m/%d', '%Y-%m-%d'),
                            ('%B %d, %Y', '%Y-%m-%d'), ('%d %B %Y', '%Y-%m-%d'),
                            ('%B %Y', '%Y-%m'), ('%Y-%m', '%Y-%m'), ('%Y', '%Y')):
        try:
            return datetime.strptime(value.strip(), pattern).strftime(output)
        except ValueError:
            continue
    return None


def literal_metadata(text: str) -> PaperMetadata:
    """Read literal title-block commands; do not evaluate arbitrary TeX macros."""
    result: PaperMetadata = {'title': None, 'authors': [], 'published_date': None, 'topics': [], 'link': None}
    # RevTeX places title/author/date after begin{document}. Read the front
    # matter up to the first abstract, section or maketitle, not the whole paper.
    stop = re.search(r'(?m)^[ \t]*\\(?:maketitle\b|section\b|begin\s*\{abstract\})', text)
    preamble = text if stop is None else text[:stop.start()]
    for match in re.finditer(r'(?m)^[ \t]*\\(title|author|date|keywords)(?:\[[^\]\n]*\])?\s*(?=\{)', preamble):
        span = _group(preamble, match.end(), len(preamble))
        if span is None:
            continue
        raw = preamble[span[0]:span[1]]
        name = match[1]
        if name == 'title':
            result['title'] = _plain(raw) or None
        elif name == 'date':
            result['published_date'] = _date(raw)
        elif name == 'keywords':
            result['topics'] = [v.strip() for v in re.split(r'[,;]', _plain(raw)) if v.strip()]
        elif name == 'author':
            # Affiliation/correspondence commands are not names. Ambiguous comma
            # or line-break author lists require the quoted AI metadata instead.
            for drop in reversed(list(re.finditer(
                    r'\\(?:thanks|email|affiliation|altaffiliation|institute|orcidlink|footnote|textsuperscript)\s*(?=\{)', raw))):
                arg = _group(raw, drop.end(), len(raw))
                if arg is not None:
                    raw = raw[:drop.start()] + raw[arg[2]:]
            for part in re.split(r'\\and\b', raw):
                value = _plain(part)
                if value and ',' not in value and r'\\' not in part:
                    result['authors'].append(value)
    return result


