import io
import re
import shlex
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import unquote, urlsplit

from qecgraph.cli.parser import parse_command


ROOT = Path(__file__).resolve().parents[1]
USER_DOCS = ('README.md', 'docs/README.md', 'docs/ADVANCED_USAGE.md',
             'docs/DATA_AND_SEARCH.md', 'docs/rfc-002/WORKSPACE.md',
             'docs/user/README.md', 'docs/user/quickstart.zh-CN.md', 'docs/design/README.md',
             'docs/operations/README.md', 'docs/archive/README.md', 'CONTRIBUTING.md', 'SECURITY.md')
LINK = re.compile(r'\[[^\]\n]+\]\(([^\s)]+)\)')
INLINE_COMMAND = re.compile(r'`qec-graph ([^`\n]+)`')


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
