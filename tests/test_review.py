import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qecgraph.registry import Registry
from qecgraph.review import SCOPES, create_proposal, decide, final_records
from qecgraph.corpus import execute


def claim(identifier='claim:review'):
    return {'schema_version': 'qecgraph.record.v3', 'id': identifier, 'kind': 'claim', 'revision': '1',
            'title': 'Review fixture', 'data': {'statement': 'Original statement', 'hypotheses': ['H'], 'quantifiers': ['for all x']}}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = Registry(self.root / 'corpus')
        self.original = self.registry.add_record(claim())['record']

    def proposal(self):
        after = claim()
        after['revision'] = '2'
        after['data']['statement'] = 'Revised statement'
        after['data']['hypotheses'] = ['H', 'Additional explicit assumption']
        return create_proposal(self.registry.root, [{'record': after, 'expected_revision': '1',
                               'expected_content_sha256': self.original['content_sha256']}],
                               actor={'id': 'fixture:ai', 'kind': 'ai'}, rationale='Contract test change')

    def test_proposal_is_inspectable_bound_and_does_not_apply(self):
        proposal = self.proposal()
        paths = {x['path'] for x in proposal['changes'][0]['diff']}
        self.assertIn('/data/statement', paths)
        self.assertIn('/data/hypotheses', paths)
        self.assertEqual(self.registry.record(self.original['id'])['revision'], '1')
        self.assertEqual(proposal['input_bindings']['records'][0]['content_sha256'], self.original['content_sha256'])
        decision = decide(self.registry.root, proposal['id'], actor={'id': 'fixture:program', 'kind': 'program'},
                          decision='approve', rationale='Structural acceptance, no human review')
        self.assertEqual(decision['status'], 'machine_accepted')
        self.assertEqual(final_records(proposal, decision)[0]['review']['status'], 'proposed')

    def test_human_scopes_are_required_and_copied_review_is_not_valid(self):
        proposal = self.proposal()
        actor = {'id': 'fixture:human', 'kind': 'human'}
        with self.assertRaisesRegex(ValueError, 'statement, hypotheses and dependencies'):
            decide(self.registry.root, proposal['id'], actor=actor, decision='approve', rationale='Incomplete fixture', checked_scopes=['statement'])
        review = decide(self.registry.root, proposal['id'], actor=actor, decision='approve',
                        rationale='Isolated fixture approval; no real person is being asserted', checked_scopes=SCOPES)
        final = final_records(proposal, review)[0]
        self.assertEqual(final['review']['status'], 'reviewed')
        # A legitimate bound decision cannot be reused for a different statement/revision.
        final.pop('content_sha256')
        final['revision'] = '3'
        final['data']['statement'] = 'Different, unreviewed statement'
        with self.assertRaisesRegex(ValueError, 'does not bind'):
            self.registry.add_record(final)

    def test_corrupt_legacy_proposal_and_review_report_managed_paths(self):
        proposal = self.proposal()
        decision = decide(self.registry.root, proposal['id'], actor={'id': 'fixture:program', 'kind': 'program'},
                          decision='approve', rationale='Fixture decision')
        scope = ['--corpus', str(self.registry.root), '--json']
        pointer = (self.registry.root / 'CURRENT.json').read_bytes()
        for directory, obj, args, corrupt in (
            ('proposals', proposal, ['review', 'show', proposal['id']], '['),
            ('reviews', decision, ['review', 'apply', proposal['id'], '--review-id', decision['id']], '[]'),
        ):
            with self.subTest(directory=directory):
                digest = hashlib.sha256(obj['id'].encode()).hexdigest()
                path = self.registry.root / directory / f'{digest}.json'
                original = path.read_bytes()
                path.write_text(corrupt, encoding='utf-8')
                try:
                    result = subprocess.run([sys.executable, '-m', 'qecgraph', *args, *scope],
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual((result.returncode, result.stderr), (1, ''))
                    error = json.loads(result.stdout)['error']
                    self.assertEqual(error['code'], 'STORAGE_ERROR')
                    self.assertEqual(error['details']['path'], str(path.resolve()))
                    self.assertEqual((self.registry.root / 'CURRENT.json').read_bytes(), pointer)
                finally:
                    path.write_bytes(original)

    def test_stale_hash_and_revision_are_rejected(self):
        changed = claim()
        changed['revision'] = '2'
        with self.assertRaisesRegex(ValueError, 'revision/hash conflict'):
            create_proposal(self.registry.root, [{'record': changed, 'expected_revision': '1', 'expected_content_sha256': '0' * 64}],
                            actor={'id': 'fixture:ai', 'kind': 'ai'}, rationale='Stale binding')
        proposal = self.proposal()
        self.registry.add_record(claim('claim:another'))
        with self.assertRaisesRegex(ValueError, 'stale registry'):
            decide(self.registry.root, proposal['id'], actor={'id': 'fixture:ai', 'kind': 'ai'}, decision='approve', rationale='Must fail')

    def test_unbound_reviewed_dependency_cannot_enter_context(self):
        self.registry.add_record(claim('claim:target'))
        proposed = claim('claim:dependency')
        proposed['refs'] = [{'relation': 'depends_on_reviewed', 'target': 'claim:target', 'status': 'declared'}]
        self.registry.add_record(proposed)
        shown = execute(self.registry.root, 'show', 'claim:dependency')
        self.assertEqual(shown['outgoing'][0]['status'], 'unbound_review')
        for candidates in (False, True):
            context = execute(self.registry.root, 'context', 'claim:dependency', include_candidates=candidates)
            self.assertFalse(context['edges'])

    def test_another_corpus_and_changed_assets_cannot_reuse_decision(self):
        raw = b'bound review input'
        digest = hashlib.sha256(raw).hexdigest()
        asset_claim = claim('claim:asset')
        asset_claim['assets'] = [{'asset_id': 'asset:sha256:' + digest, 'uri': 'qecasset:sha256:' + digest,
                                 'path': 'assets/' + digest, 'sha256': digest, 'size_bytes': len(raw), 'media_type': 'text/plain'}]
        self.registry.add_record(asset_claim)
        asset_path = self.registry.root / 'assets' / digest
        asset_path.parent.mkdir()
        asset_path.write_bytes(raw)
        proposal = self.proposal()
        another = Registry(self.root / 'another')
        another.add_record(claim())
        shutil.copytree(self.registry.root / 'proposals', another.root / 'proposals')
        with self.assertRaisesRegex(ValueError, 'another corpus'):
            decide(another.root, proposal['id'], actor={'id': 'fixture:ai', 'kind': 'ai'}, decision='approve', rationale='Wrong corpus')
        asset_path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'asset content changed'):
            decide(self.registry.root, proposal['id'], actor={'id': 'fixture:ai', 'kind': 'ai'}, decision='approve', rationale='Changed asset')


if __name__ == '__main__':
    unittest.main()
