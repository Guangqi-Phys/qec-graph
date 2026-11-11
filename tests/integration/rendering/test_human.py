import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.render.human import build_human
from qecgraph.render.thoughts import QUESTIONS
from qecgraph.source.package import unpack
from qecgraph.core.transactions import atomic_bytes, atomic_json
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from tests.unit.parsing.test_source_package import TEX, tar_bytes

PAPER = br'''\documentclass{article}
\title{Surface codes under erasure}
\author{Ada Lovelace \and Grace Hopper}
\date{June 2025}
\keywords{surface codes, erasure, quantum error correction}
\begin{document}
We study erasure errors.
\end{document}
'''


class HumanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ws = Workspace(self.root)
        self.ws.init(no_ingest=True)
        self.note = self.root / 'personal.md'
        self.note.write_bytes(b'private\x00note')
        (self.root / 'inputs/first').write_bytes(PAPER)

    def generated(self):
        vault = self.root / 'human'
        return {p.relative_to(vault).as_posix(): p.read_bytes() for p in vault.rglob('*') if p.is_file()}

    def test_one_note_front_matter_questions_and_idempotent_rebuild(self):
        release = self.ws.sync()['release_id']
        result = build_human(self.root, release)
        self.assertEqual(result['status'], 'current', result)
        self.assertEqual(result['generated_pages'], 1)
        before = self.generated()
        self.assertEqual(list(before), ['2025/06/Ada_Lovelace_Surface_codes_thoughts.md'])
        raw, = before.values()
        text = raw.decode()
        self.assertTrue(text.startswith('---\ntags:\n  - "surface-codes"\n  - "erasure"\n  - "quantum-error-correction"\n'
                                       'link: null\ntitle: "Surface codes under erasure"\nauthor:\n'
                                       '  - "Ada Lovelace"\n  - "Grace Hopper"\n---\n'))
        self.assertEqual(re.findall(r'^## [0-9]+\. (.*)$', text, re.MULTILINE), [q for q, _ in QUESTIONS])
        self.assertEqual(text.count('尚无可用回答'), 9)
        with patch('qecgraph.render.human.atomic_bytes', wraps=atomic_bytes) as writes:
            self.assertEqual(build_human(self.root, release)['status'], 'current')
            writes.assert_not_called()
        self.assertEqual(self.generated(), before)
        page = self.root / 'human' / next(iter(before))
        page.write_bytes(b'manually modified')
        self.assertEqual(build_human(self.root, release)['status'], 'current')
        self.assertEqual(self.generated(), before)
        self.assertEqual(self.note.read_bytes(), b'private\x00note')

    def test_unknown_metadata_does_not_use_ingestion_date(self):
        (self.root / 'inputs/first').write_bytes(TEX)
        result = build_human(self.root, self.ws.sync()['release_id'])
        self.assertEqual(result['status'], 'current', result)
        self.assertEqual(list(self.generated()), ['unknown/unknown/UnknownAuthor_Untitled_Paper_thoughts.md'])
        text = next(iter(self.generated().values())).decode()
        self.assertIn('tags: []\nlink: null\ntitle: null\nauthor: []\n', text)

    def test_revtex_title_block_after_document_and_author_decorations(self):
        source = br'''\documentclass{revtex4-2}
\begin{document}
\title{Surface codes under erasure}
\author{Ada Lovelace\,\orcidlink{0000-0000-0000-0000}\thanks{Correspondence}}
\affiliation{An institution}
\author{Grace Hopper}
\date{\today}
\maketitle
\section{Example}
\title{This is not the paper title}
\end{document}
'''
        (self.root / 'inputs/first').write_bytes(source)
        result = build_human(self.root, self.ws.sync()['release_id'])
        self.assertEqual(result['status'], 'current', result)
        self.assertEqual(list(self.generated()), ['unknown/unknown/Ada_Lovelace_Surface_codes_thoughts.md'])
        text = next(iter(self.generated().values())).decode()
        self.assertIn('author:\n  - "Ada Lovelace"\n  - "Grace Hopper"', text)
        self.assertIn('  - "Surface-codes"', text)
        self.assertNotIn('0000-0000', text)

    def test_same_filename_papers_remain_separate_and_old_release_is_superseded(self):
        release = self.ws.sync()['release_id']
        build_human(self.root, release)
        before = self.generated()
        (self.root / 'inputs/second').write_bytes(PAPER.replace(b'We study', b'We further study'))
        newest = self.ws.sync()['release_id']
        self.assertEqual(build_human(self.root, release)['status'], 'superseded')
        self.assertEqual(self.generated(), before)
        result = build_human(self.root, newest)
        self.assertEqual(result['status'], 'current', result)
        self.assertEqual(len(self.generated()), 2)
        self.assertEqual(len({p.casefold() for p in self.generated()}), 2)
        self.assertTrue(all(re.fullmatch(r'2025/06/Ada_Lovelace_Surface_codes(?:_[0-9a-f]{12})?_thoughts.md', p)
                            for p in self.generated()))

    def test_two_registered_versions_share_one_paper_note(self):
        second = PAPER.replace(b'We study', b'We further study')
        config = self.root / 'qecgraph.toml'
        text = config.read_text()
        for version, raw in (('v1', PAPER), ('v2', second)):
            text += f'\n[sources."{unpack(raw).digest}"]\nwork_id = "work:same-paper"\nupstream_version = "{version}"\n'
        config.write_text(text)
        (self.root / 'inputs/second').write_bytes(second)
        result = build_human(self.root, self.ws.sync()['release_id'])
        self.assertEqual(result['status'], 'current', result)
        self.assertEqual(len(self.generated()), 1)
        self.assertIn('多个登记版本', next(iter(self.generated().values())).decode())

    def test_metadata_rename_removes_old_note_and_retry_removes_retired_paths(self):
        archive = tar_bytes({'first.tex': PAPER, 'renamed.tex': PAPER.replace(
            b'Surface codes under erasure', b'Renamed paper: conclusions').replace(b'June 2025', b'July 2026')})
        (self.root / 'inputs/first').write_bytes(archive)
        config = self.root / 'qecgraph.toml'
        base = config.read_text() + f'\n[sources."{unpack(archive).digest}"]\nwork_id = "work:paper"\n' \
               'canonical_url = "https://example.org/paper"\n'
        def choose(name):
            config.write_text(base + f'\n[entrypoints]\n"{unpack(archive).digest}" = "{name}"\n')
        choose('first.tex')
        release = self.ws.sync()['release_id']
        build_human(self.root, release)
        old = next(iter(self.generated()))
        choose('renamed.tex')
        newest = self.ws.rebuild()['release_id']
        with patch('qecgraph.render.human._prune_note', side_effect=OSError('interrupted deletion')):
            result = build_human(self.root, newest)
        self.assertEqual(result['status'], 'human_stale', result)
        self.assertIn(old, self.generated())
        result = build_human(self.root, newest)
        self.assertEqual(result['status'], 'current', result)
        self.assertEqual(list(self.generated()), ['2026/07/Ada_Lovelace_Renamed_paper_thoughts.md'])
        self.assertFalse((self.root / 'human/2025').exists())
        self.assertIn('link: "https://example.org/paper"', next(iter(self.generated().values())).decode())
        self.assertFalse((self.root / '.qecgraph/human-pending.json').exists())

    def test_legacy_tree_deleted_without_reading_notes_or_creating_backup(self):
        release = self.ws.sync()['release_id']
        vault = self.root / 'human'
        (vault / 'notes').mkdir(parents=True)
        (vault / 'notes/private.md').write_bytes(b'never read this content')
        (vault / 'notes/linked').symlink_to(self.note)
        (vault / 'Index.md').write_text('old index')
        atomic_json(self.root / '.qecgraph/human-published.json',
                    {'format': 'qecgraph.human', 'release_id': release, 'pages': [], 'entity_pages': {}})
        from qecgraph.render.human import _read_regular
        def read(path, limit):
            self.assertFalse(Path(path).is_relative_to(vault))
            return _read_regular(path, limit)
        with patch('qecgraph.render.human._read_regular', side_effect=read):
            result = build_human(self.root, release)
        self.assertEqual(result['status'], 'current', result)
        self.assertEqual(list(self.generated()), ['2025/06/Ada_Lovelace_Surface_codes_thoughts.md'])
        self.assertFalse((vault / 'notes').exists())
        self.assertFalse(any('backup' in p.name for p in self.root.iterdir()))
        self.assertEqual(self.note.read_bytes(), b'private\x00note')

    def test_legacy_migration_survives_failure_after_deletion(self):
        release = self.ws.sync()['release_id']
        vault = self.root / 'human'
        vault.mkdir()
        (vault / 'Index.md').write_text('old index')
        atomic_json(self.root / '.qecgraph/human-published.json',
                    {'format': 'qecgraph.human', 'release_id': release, 'pages': [], 'entity_pages': {}})
        with patch('qecgraph.render.human.atomic_bytes', side_effect=OSError('interrupted publication')):
            self.assertEqual(build_human(self.root, release)['status'], 'human_stale')
        with patch('qecgraph.render.human.shutil.rmtree', wraps=__import__('shutil').rmtree) as remove:
            result = build_human(self.root, release)
            self.assertEqual(result['status'], 'current', result)
            self.assertFalse(any(args[0][0] == vault for args in remove.call_args_list))
        self.assertEqual(len(self.generated()), 1)

    def test_unowned_vault_and_new_note_collision_are_not_overwritten(self):
        release = self.ws.sync()['release_id']
        vault = self.root / 'human'
        vault.mkdir()
        index = vault / 'Index.md'
        index.write_text('unowned content')
        self.assertEqual(build_human(self.root, release)['status'], 'human_stale')
        self.assertEqual(index.read_text(), 'unowned content')
        index.unlink()
        self.assertEqual(build_human(self.root, release)['status'], 'current')
        conflict = vault / 'unknown/unknown/UnknownAuthor_Untitled_Paper_thoughts.md'
        conflict.parent.mkdir(parents=True)
        conflict.write_text('unowned content')
        (self.root / 'inputs/second').write_bytes(TEX)
        result = build_human(self.root, self.ws.sync()['release_id'])
        self.assertEqual(result['status'], 'human_stale', result)
        self.assertEqual(conflict.read_text(), 'unowned content')

    def test_interrupted_publication_does_not_change_machine_or_private_files(self):
        release = self.ws.sync()['release_id']
        build_human(self.root, release)
        (self.root / 'inputs/second').write_bytes(TEX)
        newest = self.ws.sync()['release_id']
        written = []
        def interrupted(path, raw):
            if written:
                raise OSError('simulated interrupted page publication')
            atomic_bytes(path, raw)
            written.append(path)
        with patch('qecgraph.render.human.atomic_bytes', side_effect=interrupted):
            self.assertEqual(build_human(self.root, newest)['status'], 'human_stale')
        self.assertEqual(len(written), 1)
        self.assertEqual(self.ws.registry.read()[1], newest)
        status = WorkspaceSession(self.ws.registry.root).invoke('qec_workspace_status', {})['data']
        self.assertEqual(status['operational_status']['human']['status'], 'human_stale')
        self.assertEqual(self.note.read_bytes(), b'private\x00note')
        self.assertEqual(build_human(self.root, newest)['status'], 'current')
        self.assertEqual(len(self.generated()), 2)

    def test_corrupt_operational_report_and_current_release_status(self):
        status = self.ws.registry.root / 'operational/status.json'
        status.write_text('{"human": [1]}')
        release = self.ws.sync()['release_id']
        self.assertEqual(json.loads(status.read_bytes())['human']['status'], 'human_stale')
        status.write_text('{')
        self.assertEqual(build_human(self.root, release)['status'], 'current')
        observed = json.loads(status.read_bytes())
        self.assertEqual(observed['release_id'], release)
        self.assertEqual(observed['human']['rendered_release_id'], release)
        self.assertEqual(self.ws.registry.read()[1], release)

    def test_render_failure_returns_a_sanitized_reason(self):
        release = self.ws.sync()['release_id']
        result = build_human(self.root, release)
        self.assertEqual(result['status'], 'current', result)
        page = self.root / 'human' / next(iter(self.generated()))
        page.unlink()
        page.mkdir()
        result = build_human(self.root, release)
        self.assertEqual(result['status'], 'human_stale')
        self.assertIn('IsADirectoryError', result['error'])
        self.assertNotIn(str(self.root), result['error'])
        self.assertIn('<workspace>', result['error'])

    def test_renderer_does_not_follow_note_symlink(self):
        release = self.ws.sync()['release_id']
        build_human(self.root, release)
        page = self.root / 'human' / next(iter(self.generated()))
        page.unlink()
        page.symlink_to(self.note)
        self.assertEqual(build_human(self.root, release)['status'], 'human_stale')
        self.assertEqual(self.note.read_bytes(), b'private\x00note')

    def test_invalid_history_cannot_delete_unowned_files(self):
        release = self.ws.sync()['release_id']
        build_human(self.root, release)
        history = self.root / '.qecgraph/human-pending.json'
        atomic_json(history, {'format': 'qecgraph.human.thoughts', 'release_id': release,
                             'pages': [], 'work_pages': {}, 'retired': ['../personal.md']})
        self.assertEqual(build_human(self.root, release)['status'], 'human_stale')
        self.assertEqual(self.note.read_bytes(), b'private\x00note')
