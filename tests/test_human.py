import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.human import build_human
from qecgraph.transactions import atomic_bytes
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from test_source_package import TEX


class HumanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ws = Workspace(self.root)
        self.ws.init(no_ingest=True)
        self.notes = self.root / 'human/notes'
        self.notes.mkdir(parents=True)
        self.note = self.notes / 'personal.md'
        self.note.write_bytes(b'private\x00note')
        (self.root / 'inputs/first').write_bytes(TEX)

    def test_deterministic_render_and_stable_pages_with_notes(self):
        release = self.ws.sync()['release_id']
        first = build_human(self.root, release)
        self.assertEqual(first['status'], 'current')
        vault = self.root / 'human'
        def generated():
            return {p.relative_to(vault): p.read_bytes() for p in (vault / 'generated').rglob('*.md')}
        before = generated()
        self.assertTrue(before)
        build_human(self.root, release)
        self.assertEqual(generated(), before)
        (self.root / 'inputs/second').write_bytes(TEX.replace(b'Hello', b'Another article'))
        next_release = self.ws.sync()['release_id']
        self.assertEqual(build_human(self.root, release)['status'], 'superseded')
        self.assertEqual(generated(), before)
        self.assertEqual(build_human(self.root, next_release)['status'], 'current')
        self.assertTrue(before.keys() <= generated().keys())
        self.assertEqual(self.note.read_bytes(), b'private\x00note')

    def test_failure_during_page_publication_does_not_change_machine_or_notes(self):
        release = self.ws.sync()['release_id']
        build_human(self.root, release)
        (self.root / 'inputs/second').write_bytes(TEX.replace(b'Hello', b'Another article'))
        next_release = self.ws.sync()['release_id']
        written = []
        def interrupted(path, raw):
            if written:
                raise OSError('simulated interrupted page publication')
            atomic_bytes(path, raw)
            written.append(path)
        with patch('qecgraph.human.atomic_bytes', side_effect=interrupted):
            self.assertEqual(build_human(self.root, next_release)['status'], 'human_stale')
        self.assertEqual(len(written), 1)
        self.assertEqual(self.ws.status()['release_id'], next_release)
        status = WorkspaceSession(self.ws.registry.root).invoke('qec_workspace_status', {})['data']
        self.assertEqual(status['operational_status']['human']['status'], 'human_stale')
        self.assertEqual(self.note.read_bytes(), b'private\x00note')
        self.assertEqual(build_human(self.root, next_release)['status'], 'current')

    def test_renderer_does_not_follow_generated_symlink_to_note(self):
        release = self.ws.sync()['release_id']
        build_human(self.root, release)
        page = next((self.root / 'human/generated').rglob('source-artifact--*.md'))
        page.unlink()
        page.symlink_to(self.note)
        self.assertEqual(build_human(self.root, release)['status'], 'human_stale')
        self.assertEqual(self.note.read_bytes(), b'private\x00note')
