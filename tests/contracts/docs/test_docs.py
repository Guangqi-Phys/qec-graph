import io
import re
import shlex
import unittest
from contextlib import redirect_stdout
from urllib.parse import unquote, urlsplit

from qecgraph.cli.parser import _build_parser, parse_command


from tests.support import ROOT
CURRENT_DOCS = ('docs/README.md', 'docs/user/README.md', 'docs/user/quickstart.md',
                'docs/user/advanced-usage.md', 'docs/user/data-and-search.md',
                'docs/user/workspace.md', 'docs/user/splitter.md', 'docs/design/DESIGN.md',
                'docs/operations/README.md', 'docs/operations/maintenance.md',
                'docs/operations/corpus.md', 'docs/operations/review.md')
USER_DOCS = ('README.md', 'README.zh-CN.md', *CURRENT_DOCS,
             'docs/README.zh-CN.md', 'docs/user/README.zh-CN.md',
             'docs/user/quickstart.zh-CN.md', 'docs/user/advanced-usage.zh-CN.md',
             'docs/user/data-and-search.zh-CN.md', 'docs/user/workspace.zh-CN.md',
             'docs/user/splitter.zh-CN.md', 'docs/design/DESIGN.zh-CN.md',
             'docs/operations/README.zh-CN.md', 'docs/operations/maintenance.zh-CN.md',
             'docs/operations/corpus.zh-CN.md', 'docs/operations/review.zh-CN.md',
             'validation/README.md', 'validation/README.zh-CN.md',
             'CONTRIBUTING.md', 'SECURITY.md')
LINK = re.compile(r'\[[^\]\n]+\]\(([^\s)]+)\)')
INLINE_COMMAND = re.compile(r'`qec-graph ([^`\n]+)`')
PUBLIC_REDIRECTS = set()


class DocumentationTests(unittest.TestCase):
    def test_every_command_help_path_has_a_parseable_example(self):
        _, topics = _build_parser()
        leaf_topics = {('inputs', action) for action in ('list', 'quarantine', 'restore')}
        leaf_topics |= {('snapshot', 'list'), ('maintain', 'snapshot', 'list')}
        self.assertLessEqual(leaf_topics, topics.keys())
        for topic in topics:
            with self.subTest(topic=topic):
                explicit, option = io.StringIO(), io.StringIO()
                with redirect_stdout(explicit):
                    self.assertIsNone(parse_command(['help', *topic]))
                with redirect_stdout(option), self.assertRaises(SystemExit) as requested:
                    parse_command([*topic, '--help'])
                self.assertEqual(requested.exception.code, 0)
                self.assertEqual(explicit.getvalue(), option.getvalue())
                help_text = explicit.getvalue()
                if topic in leaf_topics:
                    self.assertTrue(help_text.startswith(f'usage: qec-graph {" ".join(topic)} '))
                example = help_text.split('Example:\n  qec-graph ', 1)[1].splitlines()[0]
                with redirect_stdout(io.StringIO()):
                    parse_command(shlex.split(example))

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

    def test_shell_examples_use_current_command_options(self):
        commands = 0
        for name in USER_DOCS:
            text = (ROOT / name).read_text(encoding='utf-8').replace('\\\n', ' ')
            for line in text.splitlines():
                if not line.startswith('qec-graph '):
                    continue
                with self.subTest(page=name, line=line), redirect_stdout(io.StringIO()):
                    command = shlex.split(line.partition(' <<')[0], comments=True)
                    parse_command(command[1:])
                    commands += 1
        self.assertGreater(commands, 20)

    def test_inline_commands_and_help_topics_resolve(self):
        checked = 0
        for name in USER_DOCS:
            page = (ROOT / name).read_text(encoding='utf-8')
            for inline in INLINE_COMMAND.findall(page):
                arguments = shlex.split(inline)
                with self.subTest(page=name, command=inline), redirect_stdout(io.StringIO()):
                    if arguments[0] == 'help':
                        topic = [] if arguments[1:] == ['<command>'] else arguments[1:]
                        self.assertIsNone(parse_command(['help', *topic]))
                    else:
                        with self.assertRaises(SystemExit) as help_requested:
                            parse_command([*arguments, '--help'])
                        self.assertEqual(help_requested.exception.code, 0)
                    checked += 1
        self.assertGreater(checked, 20)

    def test_current_docs_have_a_status_marker(self):
        for name in CURRENT_DOCS:
            text = (ROOT / name).read_text(encoding='utf-8')
            head = '\n'.join(text.splitlines()[:20])
            with self.subTest(page=name):
                self.assertTrue('Status:' in head or '状态：' in head,
                                f'{name} has no Current/Historical status marker')

    def test_current_docs_are_reachable_from_the_index(self):
        graph = {}
        for name in CURRENT_DOCS:
            page = ROOT / name
            targets = set()
            for link in LINK.findall(page.read_text(encoding='utf-8')):
                url = urlsplit(link)
                if url.scheme or url.netloc or not url.path:
                    continue
                target = (page.parent / unquote(url.path)).resolve()
                if target.exists() and target.suffix == '.md':
                    try:
                        targets.add(str(target.relative_to(ROOT)))
                    except ValueError:
                        pass
            graph[name] = targets
        seen = {'docs/README.md'}
        pending = ['docs/README.md']
        while pending:
            current = pending.pop()
            for target in graph.get(current, ()):
                if target in graph and target not in seen:
                    seen.add(target)
                    pending.append(target)
        self.assertEqual(set(CURRENT_DOCS) - seen, set(),
                         'current docs are not reachable from docs/README.md')

    def test_indexes_never_link_to_public_redirects(self):
        for name in ('docs/README.md', 'docs/user/README.md', 'docs/operations/README.md',
                     'docs/operations/README.md'):
            page = ROOT / name
            for link in LINK.findall(page.read_text(encoding='utf-8')):
                url = urlsplit(link)
                if url.scheme or url.netloc or not url.path:
                    continue
                target = (page.parent / unquote(url.path)).resolve()
                try:
                    relative = str(target.relative_to(ROOT))
                except ValueError:
                    continue
                with self.subTest(page=name, target=relative):
                    self.assertNotIn(relative, PUBLIC_REDIRECTS)

    def test_docs_tree_has_one_current_location_per_page(self):
        root_docs = {p.name for p in (ROOT / 'docs').iterdir() if p.is_file() and p.suffix == '.md'}
        self.assertEqual(root_docs, {'README.md', 'README.zh-CN.md'})
        design = {p.name for p in (ROOT / 'docs/design').iterdir() if p.is_file() and p.suffix == '.md'}
        self.assertEqual(design, {'DESIGN.md', 'DESIGN.zh-CN.md'})
        self.assertFalse((ROOT / 'docs/rfc-002').exists())
        self.assertFalse((ROOT / 'docs/archive').exists())

    @staticmethod
    def _doc_slug(title):
        title = re.sub(r'`([^`]*)`', r'\1', title)
        title = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', title)
        title = title.lower()
        title = ''.join(ch for ch in title if ch.isalnum() or ch in ' _-')
        title = title.strip().replace(' ', '-')
        return title

    def test_long_current_documents_have_a_working_toc(self):
        for name in CURRENT_DOCS:
            text = (ROOT / name).read_text(encoding='utf-8')
            headings, fenced = [], False
            for line in text.splitlines():
                if line.strip().startswith('```'):
                    fenced = not fenced
                    continue
                if not fenced:
                    match = re.match(r'^##\s+(.+?)\s*$', line)
                    if match and match.group(1).strip() != 'On this page':
                        headings.append(match.group(1).strip())
            if len(headings) < 2:
                continue
            with self.subTest(page=name):
                self.assertIn('## On this page', text)
                toc = text.split('## On this page', 1)[1].split('\n## ', 1)[0]
                anchors = re.findall(r'\]\(#([^)]+)\)', toc)
                self.assertEqual(anchors, [self._doc_slug(h) for h in headings])

    def test_no_redirect_only_pages(self):
        for page in sorted((ROOT / 'docs').rglob('*.md')):
            self.assertGreaterEqual(len(page.read_text(encoding='utf-8').splitlines()), 10,
                                    f'{page.relative_to(ROOT)} is a redirect/stub, not a document')
