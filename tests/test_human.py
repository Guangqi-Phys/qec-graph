import json
import re
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from qecgraph.human import _assign_pages, build_human
from qecgraph.source_package import unpack
from qecgraph.transactions import atomic_bytes
from qecgraph.workspace import Workspace
from qecgraph.workspace_query import WorkspaceSession
from test_source_package import TEX, tar_bytes


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
        with patch('qecgraph.human.atomic_bytes', wraps=atomic_bytes) as writes:
            self.assertEqual(build_human(self.root, release)['status'], 'current')
            writes.assert_not_called()
        self.assertEqual(generated(), before)
        page = next(iter(before))
        (vault / page).write_bytes(b'manually modified')
        self.assertEqual(build_human(self.root, release)['status'], 'current')
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

    def test_generated_pages_show_sources_labels_and_eligible_proof_links(self):
        (self.root / 'inputs/first').write_text(r'''
\documentclass{article}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}[Commutation of checks]\label{thm:commute}
The two check types commute.
\end{theorem}
\begin{proof}[Proof of Theorem~\ref{thm:commute}]
\proves{thm:commute}
Compute the commutator.
\end{proof}
\end{document}
'''.lstrip(), encoding='utf-8')
        release = self.ws.sync()['release_id']
        self.assertEqual(build_human(self.root, release)['status'], 'current')
        vault = self.root / 'human'
        theorem, = (vault / 'generated').rglob('theorem--*.md')
        text = theorem.read_text(encoding='utf-8')
        normalized = text.replace(release, '<RELEASE>').replace(release[:12], '<RELEASE_PREFIX>')
        fixture = Path(__file__).with_name('fixtures') / 'obsidian-theorem.md'
        self.assertEqual(normalized, fixture.read_text(encoding='utf-8'))
        front = {line.split(': ', 1)[0]: json.loads(line.split(': ', 1)[1]) for line in text.split('---', 2)[1].strip().splitlines()}
        self.assertEqual(front['title'], 'Commutation of checks')
        self.assertEqual(front['aliases'], ['thm:commute'])
        self.assertEqual(front['source_release'], release)
        self.assertIn('qec/theorem', front['tags'])
        self.assertIn('| Verification | not\\_verified |', text)
        self.assertIn('## Source text\n\n```latex', text)
        proof = re.search(r'Proof text → \[\[([^|]+)\|([^\]]+)\]\]', text)
        self.assertIsNotNone(proof, text)
        self.assertIn(']] (declared)', text)
        self.assertIn('Incoming references', text)
        self.assertIn('Compute the commutator.', (vault / (proof[1] + '.md')).read_text(encoding='utf-8'))
        index = (vault / 'generated/records/Index.md').read_text(encoding='utf-8')
        self.assertIn('## Theorem (1)', index)
        self.assertIn('|Commutation of checks]]', index)
        self.assertIn('[[generated/Status|Release status and legend]]', (vault / 'Index.md').read_text(encoding='utf-8'))
        self.assertEqual(self.note.read_bytes(), b'private\x00note')

    def test_legacy_vault_keeps_existing_links_after_readable_filename_migration(self):
        release = self.ws.sync()['release_id']
        identifier = 'source-artifact:' + sha256(TEX).hexdigest()
        relative = 'generated/sources/source-artifact--' + sha256(identifier.encode()).hexdigest() + '.md'
        vault = self.root / 'human'
        legacy = vault / relative
        legacy.parent.mkdir(parents=True)
        legacy.write_text('# An old generated page\n', encoding='utf-8')
        history = self.root / '.qecgraph/human-published.json'
        history.write_text(json.dumps({'format': 'qecgraph.human.v1', 'release_id': release,
                                       'pages': [relative]}), encoding='utf-8')

        expected = vault / ('generated/sources/source-artifact--package--' + sha256(identifier.encode()).hexdigest()[:12] + '.md')
        expected.write_text('An unrelated file at the prospective path', encoding='utf-8')
        self.assertEqual(build_human(self.root, release)['status'], 'human_stale')
        self.assertEqual(expected.read_text(), 'An unrelated file at the prospective path')
        self.assertEqual(json.loads(history.read_text())['format'], 'qecgraph.human.v1')
        expected.unlink()

        self.assertEqual(build_human(self.root, release)['status'], 'current')
        migrated = json.loads(history.read_text())
        target = migrated['entity_pages'][identifier]
        self.assertRegex(target, r'^generated/sources/source-artifact--package--[0-9a-f]{12}\.md$')
        self.assertIn(f'[[{target.removesuffix(".md")}|', legacy.read_text(encoding='utf-8'))
        self.assertIn(identifier, (vault / target).read_text(encoding='utf-8'))
        self.assertEqual(build_human(self.root, release)['status'], 'current')
        self.assertEqual(json.loads(history.read_text())['entity_pages'][identifier], target)
        self.assertEqual(self.note.read_bytes(), b'private\x00note')

    def test_page_collisions_do_not_change_existing_bindings(self):
        rows = [{'kind': 'code_instance'}]
        existing_id, new_id = 'code:test_x', 'code:test-x'

        def collision(value):
            return '0' * 12 + sha256(value.encode()).hexdigest()[12:]

        with patch('qecgraph.human.hash_text', side_effect=collision):
            old = _assign_pages({existing_id: rows}, set(), {})
            bindings = _assign_pages({existing_id: rows, new_id: rows}, set(old.values()), old)
        self.assertEqual(bindings[existing_id], old[existing_id])
        self.assertNotEqual(bindings[existing_id], bindings[new_id])

    def test_recent_changes_stays_bound_to_the_previous_rendered_release(self):
        baseline = self.ws.sync()['release_id']
        build_human(self.root, baseline)
        vault = self.root / 'human'
        changes = vault / 'generated/Changes.md'
        self.assertIn('first generated baseline', changes.read_text(encoding='utf-8'))

        (self.root / 'inputs/second').write_bytes(TEX.replace(b'Hello', b'Another article'))
        newest = self.ws.sync()['release_id']
        self.assertNotEqual(newest, baseline)
        self.assertEqual(build_human(self.root, newest)['status'], 'current')
        report = changes.read_text(encoding='utf-8')
        self.assertIn(f'Compared with rendered release `{baseline}`.', report)
        self.assertIn('## Added (2)', report)
        self.assertIn('## Archived (0)', report)
        for target in re.findall(r'\[\[([^|]+)\|', report):
            self.assertTrue((vault / (target + '.md')).is_file(), target)
        with patch('qecgraph.human.atomic_bytes', wraps=atomic_bytes) as writes:
            self.assertEqual(build_human(self.root, newest)['status'], 'current')
            writes.assert_not_called()
        self.assertEqual(changes.read_text(encoding='utf-8'), report)

    def test_removed_source_occurrence_keeps_its_page_until_restored(self):
        lemma = br'\begin{lemma}[Temporary lemma]\label{lem:temporary}An original statement.\end{lemma}'
        archive = tar_bytes({'first.tex': TEX.replace(b'Hello', lemma), 'alternate.tex': TEX})
        (self.root / 'inputs/first').write_bytes(archive)
        config = self.root / 'qecgraph.toml'
        original_config = config.read_text(encoding='utf-8')

        def choose(entrypoint):
            config.write_text(original_config + f'\n[entrypoints]\n"{unpack(archive).digest}" = "{entrypoint}"\n',
                              encoding='utf-8')

        choose('first.tex')
        original = self.ws.sync()['release_id']
        self.assertEqual(build_human(self.root, original)['status'], 'current')
        vault = self.root / 'human'
        page, = (vault / 'generated/records').glob('lemma--*.md')
        target = page.relative_to(vault).with_suffix('').as_posix()
        self.assertIn('An original statement.', page.read_text(encoding='utf-8'))

        choose('alternate.tex')
        archived = self.ws.rebuild()['release_id']
        self.assertEqual(build_human(self.root, archived)['status'], 'current')
        self.assertIn('# Archived entity', page.read_text(encoding='utf-8'))
        self.assertNotIn('An original statement.', page.read_text(encoding='utf-8'))
        changes = (vault / 'generated/Changes.md').read_text(encoding='utf-8')
        self.assertIn('## Archived (1)', changes)
        self.assertIn(f'[[{target}|Temporary lemma]]', changes)

        choose('first.tex')
        restored = self.ws.rebuild()['release_id']
        self.assertEqual(build_human(self.root, restored)['status'], 'current')
        self.assertEqual(list((vault / 'generated/records').glob('lemma--*.md')), [page])
        self.assertIn('An original statement.', page.read_text(encoding='utf-8'))
        self.assertEqual(self.note.read_bytes(), b'private\x00note')
