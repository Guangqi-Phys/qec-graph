import re
import unicodedata
import unittest
from urllib.parse import unquote, urlsplit


from tests.support import ROOT
PAIRS = (
    ('README.md', 'README.zh-CN.md'),
    ('docs/README.md', 'docs/README.zh-CN.md'),
    ('docs/user/README.md', 'docs/user/README.zh-CN.md'),
    ('docs/user/quickstart.md', 'docs/user/quickstart.zh-CN.md'),
    ('docs/user/advanced-usage.md', 'docs/user/advanced-usage.zh-CN.md'),
    ('docs/user/data-and-search.md', 'docs/user/data-and-search.zh-CN.md'),
    ('docs/user/workspace.md', 'docs/user/workspace.zh-CN.md'),
    ('docs/user/splitter.md', 'docs/user/splitter.zh-CN.md'),
    ('docs/design/DESIGN.md', 'docs/design/DESIGN.zh-CN.md'),
    ('docs/operations/README.md', 'docs/operations/README.zh-CN.md'),
    ('docs/operations/maintenance.md', 'docs/operations/maintenance.zh-CN.md'),
    ('docs/operations/corpus.md', 'docs/operations/corpus.zh-CN.md'),
    ('docs/operations/review.md', 'docs/operations/review.zh-CN.md'),
    ('validation/README.md', 'validation/README.zh-CN.md'),
    ('tools/README.md', 'tools/README.zh-CN.md'),
    ('tests/README.md', 'tests/README.zh-CN.md'),
    ('tests/golden/README.md', 'tests/golden/README.zh-CN.md'),
)
LINK = re.compile(r'\[[^\]\n]+\]\(([^\s)]+)\)')


def _github_slug(text):
    """Approximate GitHub's heading anchor algorithm, including Unicode text."""
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text).strip().lower()
    kept = []
    for character in text:
        category = unicodedata.category(character)
        if character in ' -_' or category[0] in 'LMN' or category == 'Pc':
            kept.append(character)
    return ''.join(kept).replace(' ', '-')


def _anchors(path):
    seen, result = {}, set()
    fenced = False
    for line in (ROOT / path).read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('```'):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = re.match(r'^(#{1,6})\s+(.*?)\s*$', line)
        if not match:
            continue
        slug = _github_slug(match.group(2))
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f'{slug}-{count}')
    return result


def headings(text):
    levels, fenced = [], False
    for line in text.splitlines():
        if line.strip().startswith('```'):
            fenced = not fenced
            continue
        if not fenced:
            match = re.match(r'^(#{1,3})\s+', line)
            if match:
                levels.append(len(match.group(1)))
    return levels


def code_blocks(text):
    blocks = re.findall(r'^```([^\n]*)\n(.*?)^```\s*$', text, re.M | re.S)
    return [(language, body) for language, body in blocks
            if language.strip() in {'bash', 'sh', 'python', 'json', 'toml'}]


class BilingualDocumentationTests(unittest.TestCase):
    def test_every_current_page_has_a_language_pair_and_switcher(self):
        for english, chinese in PAIRS:
            with self.subTest(english=english, chinese=chinese):
                en = ROOT / english
                zh = ROOT / chinese
                self.assertTrue(en.exists(), english)
                self.assertTrue(zh.exists(), chinese)
                en_head = '\n'.join(en.read_text(encoding='utf-8').splitlines()[:30])
                zh_head = '\n'.join(zh.read_text(encoding='utf-8').splitlines()[:30])
                self.assertIn(zh.name, en_head, f'{english} has no Chinese switch')
                self.assertIn(en.name, zh_head, f'{chinese} has no English switch')

    def test_pairs_have_the_same_heading_shape(self):
        for english, chinese in PAIRS:
            with self.subTest(english=english, chinese=chinese):
                en = headings((ROOT / english).read_text(encoding='utf-8'))
                zh = headings((ROOT / chinese).read_text(encoding='utf-8'))
                self.assertEqual(zh, en, f'{english} and {chinese} heading levels differ')

    def test_pairs_have_identical_code_blocks(self):
        for english, chinese in PAIRS:
            with self.subTest(english=english, chinese=chinese):
                en = code_blocks((ROOT / english).read_text(encoding='utf-8'))
                zh = code_blocks((ROOT / chinese).read_text(encoding='utf-8'))
                self.assertEqual(zh, en, f'{english} and {chinese} code blocks differ')

    def test_pairs_have_the_same_table_shape(self):
        for english, chinese in PAIRS:
            with self.subTest(english=english, chinese=chinese):
                def rows(path):
                    text = (ROOT / path).read_text(encoding='utf-8')
                    text = re.sub(r'^```.*?^```\s*$', '', text, flags=re.M | re.S)
                    return [line for line in text.splitlines() if line.startswith('|')]
                self.assertEqual(len(rows(chinese)), len(rows(english)),
                                 f'{english} and {chinese} table rows differ')

    def test_internal_link_labels_are_not_stale_sequence_numbers(self):
        label_pattern = re.compile(r'\[([^\]\n]+)\]\(([^\s)]+)\)')
        for pair in PAIRS:
            for name in pair:
                for label, link in label_pattern.findall((ROOT / name).read_text(encoding='utf-8')):
                    url = urlsplit(link)
                    if url.scheme or url.netloc or not url.path:
                        continue
                    with self.subTest(page=name, label=label, target=link):
                        self.assertFalse(label.strip().isdigit(),
                                         f'{name} uses the bare sequence number {label!r} as link text')

    def test_links_in_both_languages_resolve(self):
        for pair in PAIRS:
            for name in pair:
                page = ROOT / name
                for link in LINK.findall(page.read_text(encoding='utf-8')):
                    url = urlsplit(link)
                    if url.scheme or url.netloc or not url.path:
                        continue
                    target = (page.parent / unquote(url.path)).resolve()
                    with self.subTest(page=name, target=url.path):
                        self.assertTrue(target.is_relative_to(ROOT))
                        self.assertTrue(target.exists(), f'{name} links to missing {url.path}')
                        if url.fragment and target.suffix == '.md':
                            fragment = unquote(url.fragment).lower()
                            self.assertIn(fragment, {anchor.lower() for anchor in _anchors(target.relative_to(ROOT))},
                                          f'{name} links to a missing heading #{url.fragment} in {target.relative_to(ROOT)}')


if __name__ == '__main__':
    unittest.main()
