import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
USER_DOCS = ('README.md', 'docs/README.md', 'docs/ADVANCED_USAGE.md',
             'docs/DATA_AND_SEARCH.md', 'docs/rfc-002/WORKSPACE.md')
LINK = re.compile(r'\[[^\]\n]+\]\(([^\s)]+)\)')


class DocumentationTests(unittest.TestCase):
    def test_current_documentation_links_resolve_in_the_source_distribution(self):
        for name in USER_DOCS:
            page = ROOT / name
            for link in LINK.findall(page.read_text(encoding='utf-8')):
                url = urlsplit(link)
                if url.scheme or url.netloc or not url.path:
                    continue
                target = (page.parent / unquote(url.path)).resolve()
                with self.subTest(page=name, target=url.path):
                    self.assertTrue(target.is_relative_to(ROOT))
                    self.assertTrue(target.exists(), f'{name} links to missing {url.path}')
