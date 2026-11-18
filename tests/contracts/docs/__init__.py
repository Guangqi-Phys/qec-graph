import re
from urllib.parse import unquote, urlsplit


_LINK = re.compile(r'\[[^\]\n]+\]\(([^\s)]+)\)')


def local_link_targets(page):
    for link in _LINK.findall(page.read_text(encoding='utf-8')):
        url = urlsplit(link)
        if url.path and not (url.scheme or url.netloc):
            yield url, (page.parent / unquote(url.path)).resolve()
