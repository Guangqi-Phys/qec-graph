import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.core.graph import canonical
from qecgraph.domain.records import prepare_record
from qecgraph.registry import Registry
from qecgraph.review import apply, create_proposal, decide
from qecgraph.core.transactions import writer_lock


def claim(identifier, revision='1'):
    return {'schema': 'qecgraph.record', 'id': identifier, 'revision': revision, 'kind': 'claim',
            'title': identifier, 'data': {'statement': 'Statement ' + revision, 'hypotheses': [], 'quantifiers': []}}


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = Registry(self.root / 'corpus')
        for identifier in ('claim:a', 'claim:b'):
            self.registry.add_record(claim(identifier))

    def proposal_and_review(self, *, invalid_reference=False):
        changes = []
        for identifier in ('claim:a', 'claim:b'):
            before = self.registry.record(identifier)
            after = claim(identifier, '2')
            if invalid_reference and identifier == 'claim:b':
                after['refs'] = [{'relation': 'depends_on_declared', 'target': 'claim:missing'}]
            changes.append({'record': after, 'expected_revision': before['revision'], 'expected_content_sha256': before['content_sha256']})
        proposal = create_proposal(self.registry.root, changes, actor={'id': 'fixture:ai', 'kind': 'ai'}, rationale='Atomic batch fixture')
        review = decide(self.registry.root, proposal['id'], actor={'id': 'fixture:program', 'kind': 'program'},
                        decision='approve', rationale='Program acceptance only')
        return proposal, review

    def test_apply_batch_is_atomic_and_repeated_apply_is_identical(self):
        proposal, review = self.proposal_and_review()
        selected = subprocess.check_output([sys.executable, '-m', 'qecgraph', 'review', 'show', proposal['id'],
                                            '--corpus', str(self.registry.root)], text=True, timeout=10)
        self.assertEqual(json.loads(selected), proposal)
        first = apply(self.registry.root, proposal['id'], review['id'])
        again = apply(self.registry.root, proposal['id'], review['id'])
        self.assertEqual(first, again)
        for identifier in ('claim:a', 'claim:b'):
            self.assertEqual(self.registry.record(identifier)['revision'], '2')
            self.assertEqual(self.registry.record(identifier)['review']['status'], 'proposed')
            self.assertEqual(self.registry.record(identifier, '1')['data']['statement'], 'Statement 1')
        self.assertEqual(self.registry.read()[1], first['receipt']['registry_revision'])

    def test_cross_record_failure_leaves_both_original_records_current(self):
        proposal, review = self.proposal_and_review(invalid_reference=True)
        before = self.registry.read()[1]
        with self.assertRaisesRegex(ValueError, 'cross-record validation failed'):
            apply(self.registry.root, proposal['id'], review['id'])
        self.assertEqual(self.registry.read()[1], before)
        self.assertEqual([self.registry.record(k)['revision'] for k in ('claim:a', 'claim:b')], ['1', '1'])

    def test_pointer_failure_retains_old_state_and_retry_recovers(self):
        proposal, review = self.proposal_and_review()
        before = self.registry.read()[1]
        original_replace = os.replace

        def fail_pointer(source, target):
            if Path(target) == self.registry.root / 'CURRENT.json':
                raise OSError('Injected pointer publication failure')
            return original_replace(source, target)

        with patch('qecgraph.core.transactions.os.replace', side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, 'Injected pointer'):
                apply(self.registry.root, proposal['id'], review['id'])
        self.assertEqual(self.registry.read()[1], before)
        self.assertEqual(self.registry.record('claim:a')['revision'], '1')
        receipt = apply(self.registry.root, proposal['id'], review['id'])
        self.assertEqual(self.registry.read()[1], receipt['receipt']['registry_revision'])

    def test_lock_refuses_apply_without_writing(self):
        proposal, review = self.proposal_and_review()
        before = self.registry.read()[1]
        with writer_lock(self.registry.root):
            with self.assertRaisesRegex(ValueError, 'Another writer'):
                apply(self.registry.root, proposal['id'], review['id'])
        self.assertEqual(self.registry.read()[1], before)

    def test_unrelated_record_does_not_stale_a_proposal(self):
        proposal, review = self.proposal_and_review()
        self.registry.add_record(claim('claim:unrelated'))
        result = apply(self.registry.root, proposal['id'], review['id'])
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(self.registry.record('claim:a')['revision'], '2')

    def test_referenced_dependency_change_stales_a_proposal(self):
        definition = {'schema': 'qecgraph.record', 'id': 'definition:x', 'revision': '1',
                      'kind': 'definition', 'title': 'Dependency', 'data': {'statement': 'Base', 'scope': 'all'}}
        self.registry.add_record(definition)
        before = self.registry.record('claim:a')
        after = claim('claim:a', '2')
        after['refs'] = [{'relation': 'depends_on_declared', 'target': 'definition:x'}]
        proposal = create_proposal(self.registry.root, [{
            'record': after, 'expected_revision': before['revision'],
            'expected_content_sha256': before['content_sha256']}],
            actor={'id': 'fixture:ai', 'kind': 'ai'}, rationale='Dependency fixture')
        revised = dict(definition)
        revised['revision'] = '2'
        revised['data'] = {'statement': 'Changed base', 'scope': 'all'}
        self.registry.add_record(revised)
        with self.assertRaisesRegex(ValueError, 'bindings changed'):
            decide(self.registry.root, proposal['id'], actor={'id': 'fixture:program', 'kind': 'program'},
                   decision='approve', rationale='Program acceptance only')

    def test_explicit_human_fixture_binds_only_the_exact_final_revision(self):
        proposal, _ = self.proposal_and_review()
        review = decide(self.registry.root, proposal['id'], actor={'id': 'fixture:human', 'kind': 'human'},
                        decision='approve', rationale='Isolated test fixture, not an actual human review',
                        checked_scopes=['statement', 'hypotheses', 'dependencies'])
        apply(self.registry.root, proposal['id'], review['id'])
        record = self.registry.record('claim:a')
        self.assertEqual(record['review']['status'], 'reviewed')
        self.assertEqual(record['review']['review_id'], review['id'])
        record.pop('content_sha256')
        record['revision'] = '3'
        with self.assertRaisesRegex(ValueError, 'does not bind'):
            self.registry.add_record(record)

    def test_batch_validation_rechecks_each_record_against_its_review(self):
        proposal, _ = self.proposal_and_review()
        review = decide(self.registry.root, proposal['id'], actor={'id': 'fixture:human', 'kind': 'human'},
                        decision='approve', rationale='Batch binding fixture',
                        checked_scopes=['statement', 'hypotheses', 'dependencies'])
        apply(self.registry.root, proposal['id'], review['id'])
        self.assertTrue(self.registry.validate()['passed'])
        state, _ = self.registry.read()
        record = self.registry.record('claim:b')
        record['data']['statement'] = 'A different statement.'
        record.pop('content_sha256')
        record = prepare_record(record)
        binding = state['records']['claim:b']['revisions']['2']
        (self.registry.root / binding['path']).write_text(canonical(record), encoding='utf-8')
        binding['content_sha256'] = record['content_sha256']
        fixed = self.registry._publish(state)
        with self.assertRaisesRegex(ValueError, 'does not bind'):
            self.registry.validate(fixed)


if __name__ == '__main__':
    unittest.main()
