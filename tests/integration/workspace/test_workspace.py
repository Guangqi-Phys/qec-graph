from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from qecgraph.cli import main
from qecgraph.corpus import execute
from qecgraph.domain.research_store import stage_records
from qecgraph.source.package import unpack
from qecgraph.store import extraction_tool_identity, ingest
from qecgraph.core.transactions import ManagedDataError, writer_lock
from qecgraph.workspace import Workspace
from tests.unit.parsing.test_source_package import TEX, tar_bytes


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.inbox = self.root / 'inputs'
        self.inbox.mkdir()
        self.ws = Workspace(self.root)

    def test_daily_cli_uses_default_workspace_and_consumes_only_successful_inputs(self):
        self.ws.init(no_ingest=True)
        package = self.inbox / 'paper.tex'
        package.write_bytes(TEX)

        def invoke(*args):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(args)
            return code, stdout.getvalue(), stderr.getvalue()

        with tempfile.TemporaryDirectory() as outside, \
                patch('qecgraph.workspace.Path.cwd', return_value=Path(outside)), \
                patch.dict('os.environ', {'QECGRAPH_WORKSPACE': str(self.root)}):
            for action in ('sync', 'status', 'validate'):
                with self.subTest(action=action):
                    code, stdout, stderr = invoke(action)
                    self.assertEqual((code, stderr), (0, ''))
                    self.assertEqual(len(stdout.splitlines()), 1)
                    self.assertIn(f'{action}: OK', stdout)
            archived = self.root / 'archive/blobs/sha256' / sha256(TEX).hexdigest()
            self.assertFalse(package.exists())
            self.assertEqual(archived.read_bytes(), TEX)
            self.assertEqual(self.ws.sync(dry_run=True)['pending_claims'], 0)

            package.write_bytes(TEX)
            code, stdout, stderr = invoke('sync', '--json')
            self.assertEqual((code, stderr), (0, ''))
            self.assertTrue(json.loads(stdout)['inputs'][0]['input_consumed'])
            self.assertFalse(package.exists())

            package.write_bytes(TEX)
            broken = self.inbox / 'broken.zip'
            broken.write_bytes(b'PK\x03\x04broken')
            code, stdout, stderr = invoke('sync')
            self.assertEqual((code, stdout), (2, ''))
            self.assertEqual(len(stderr.splitlines()), 1)
            self.assertIn('sync: ERROR: broken.zip', stderr)
            self.assertFalse(package.exists())
            self.assertEqual(broken.read_bytes(), b'PK\x03\x04broken')
            self.assertEqual(archived.read_bytes(), TEX)
            code, stdout, stderr = invoke('status')
            self.assertEqual((code, stdout), (2, ''))
            self.assertIn('status: ERROR: 1/2 packages indexed', stderr)
            self.assertEqual(invoke('status', '--workspace', str(self.root)), (code, stdout, stderr))
            for options in (('--json',), ('--workspace', str(self.root), '--json')):
                code, stdout, stderr = invoke('status', *options)
                self.assertEqual((code, stderr), (2, ''))
                self.assertEqual(json.loads(stdout)['status'], 'partial_batch')
            code, stdout, stderr = invoke('sync', '--dry-run', '--workspace', str(self.root))
            self.assertEqual((code, stderr), (0, ''))
            self.assertIn('1 inbox files, 0 pending claims', stdout)

    def test_partial_batch_dedup_and_rebuild_from_full_inventory(self):
        (self.inbox / 'good.zip').write_bytes(TEX)
        (self.inbox / 'broken').write_bytes(b'PK\x03\x04broken')
        out = self.ws.init()
        self.assertEqual(out['status'], 'partial_batch')
        self.assertFalse((self.inbox / 'good.zip').exists())
        self.assertTrue((self.inbox / 'broken').exists())
        self.assertEqual(self.ws.init()['status'], 'already_initialized')
        self.assertTrue(self.ws.validate()['valid'])
        query = execute(self.ws.registry.root, 'search', text='Hello')
        self.assertTrue(query['results'])
        (self.inbox / 'broken').unlink()
        (self.inbox / 'renamed').write_bytes(TEX)
        duplicate = self.ws.sync()
        self.assertEqual(duplicate['counts']['registered'], 2)
        self.assertEqual(duplicate['counts']['processed'], 1)
        self.assertEqual(len(list((self.root / 'archive/receipts').glob('*.json'))), 3)
        rebuilt = self.ws.rebuild()
        self.assertEqual(rebuilt['status'], 'partial_batch')
        self.assertEqual({r['status'] for r in rebuilt['inputs']}, {'processing_completed', 'damaged_archive'})
        self.assertEqual(rebuilt['release_id'], duplicate['release_id'])

    def test_successful_claims_and_empty_claim_directories_are_cleaned(self):
        self.ws.init(no_ingest=True)
        processing = self.root / 'inputs/.processing'
        (processing / ('a' * 32)).mkdir()
        (self.inbox / 'paper.tex').write_bytes(TEX)
        result = self.ws.sync()
        self.assertEqual(result['status'], 'published')
        self.assertEqual(list(processing.iterdir()), [])

    def test_quarantine_rejects_links_and_status_tolerates_foreign_entries(self):
        self.ws.init(no_ingest=True)
        target = self.root / 'payload.bin'
        target.write_bytes(b'payload')
        link = self.inbox / 'linked.bin'
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            self.ws.move_quarantine('linked.bin')
        self.assertTrue(link.is_symlink())
        quarantine = self.root / 'inputs/.quarantine'
        quarantine.mkdir()
        foreign = quarantine / 'foreign.bin'
        foreign.symlink_to(target)
        result = self.ws.status()
        row = next(item for item in result['quarantined_inputs'] if item['name'] == 'foreign.bin')
        self.assertIsNone(row['archive_sha256'])
        self.assertIn('error', row)

    def test_operational_status_failure_does_not_hide_a_published_release(self):
        self.ws.init(no_ingest=True)
        (self.inbox / 'paper.tex').write_bytes(TEX)
        with patch.object(Workspace, '_write_operational_status', side_effect=OSError('read-only status directory')):
            result = self.ws.sync()
        self.assertEqual(result['status'], 'published')
        self.assertIn('operational status', result['warning'])
        self.assertFalse((self.inbox / 'paper.tex').exists())

    def test_validate_reports_a_damaged_research_revision_instead_of_raising(self):
        from qecgraph.core.graph import hash_text
        from qecgraph.domain.research import make_record
        from qecgraph.domain.research_store import publish_records

        self.ws.init(no_ingest=True)
        record = make_record('algorithm', 'algo:test', 'one', {}, method='fixture')
        publish_records(self.ws.registry, [record])
        path = (self.ws.registry.root / 'research' / hash_text(record['id'])
                / (hash_text(record['revision']) + '.json'))
        path.write_text('{}', encoding='utf-8')
        result = self.ws.validate()
        self.assertFalse(result['valid'])
        self.assertTrue(any(issue['code'] == 'research_invalid' for issue in result['issues']), result)

    def test_quarantine_acknowledges_the_exact_failed_archive_and_restores_without_clobbering(self):
        name = 'broken.zip'
        raw = b'PK\x03\x04broken'
        package = self.inbox / name
        package.write_bytes(raw)
        first = self.ws.init()
        self.assertEqual(first['status'], 'partial_batch')
        digest = sha256(raw).hexdigest()
        receipt = self.root / 'archive/receipts' / (first['inputs'][0]['receipt_id'] + '.json')
        original_receipt = receipt.read_bytes()

        def inputs(*arguments):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(['inputs', *arguments, '--workspace', str(self.root)]), 0)
            return json.loads(output.getvalue())

        def failed_input(arguments, expected):
            output, diagnostics = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(diagnostics):
                self.assertEqual(main(['inputs', *arguments, '--workspace', str(self.root), '--json']), expected)
            self.assertEqual(diagnostics.getvalue(), '')
            return json.loads(output.getvalue())['error']

        self.assertEqual(inputs('quarantine', name)['status'], 'quarantined')
        held = self.inbox / '.quarantine' / name
        self.assertFalse(package.exists())
        self.assertEqual(held.read_bytes(), raw)
        missing = failed_input(('quarantine', name), 4)
        self.assertEqual(missing['code'], 'NOT_FOUND')
        self.assertEqual(missing['details']['path'], str(package.parent.resolve() / name))
        self.assertEqual(inputs('list')['quarantined_inputs'], [{'name': name, 'archive_sha256': digest}])
        self.assertEqual(self.ws.status()['status'], 'ok')
        self.assertTrue(self.ws.status()['materials'][0]['quarantined'])
        self.assertEqual(self.ws.sync()['inputs'], [])
        self.assertEqual(receipt.read_bytes(), original_receipt)
        self.assertEqual((self.root / 'archive/blobs/sha256' / digest).read_bytes(), raw)
        self.assertTrue(self.ws.validate()['valid'])

        package.write_bytes(TEX)
        conflict = failed_input(('restore', name), 5)
        self.assertEqual(conflict['code'], 'CONFLICT')
        self.assertIn('existing file', conflict['hint'])
        self.assertEqual(conflict['details']['source'], str(held.parent.resolve() / name))
        self.assertEqual(package.read_bytes(), TEX)
        self.assertEqual(held.read_bytes(), raw)
        package.unlink()
        self.assertEqual(inputs('restore', name)['status'], 'restored')
        self.assertEqual(package.read_bytes(), raw)
        self.assertEqual(self.ws.status()['status'], 'partial_batch')
        self.assertEqual(self.ws.sync()['status'], 'partial_batch')

    def test_entrypoint_override_retries_archived_failure_without_inbox(self):
        bundle = tar_bytes({'a.tex': TEX, 'b.tex': TEX})
        (self.inbox / 'two').write_bytes(bundle)
        first = self.ws.init()
        self.assertEqual(first['inputs'][0]['status'], 'needs_entrypoint')
        (self.inbox / 'two').unlink()
        with (self.root / 'qecgraph.toml').open('a') as config:
            config.write(f'\n[entrypoints]\n"{unpack(bundle).digest}" = "b.tex"\n')
        rebuilt = self.ws.rebuild()
        self.assertEqual(rebuilt['counts']['processed'], 1)
        self.assertEqual(rebuilt['inputs'][0]['entrypoint'], 'b.tex')

    def test_rebuild_reuses_exact_extractions_and_reparses_after_processor_changes(self):
        (self.inbox / 'paper.tex').write_bytes(TEX)
        with patch('qecgraph.store.extraction_tool_identity', wraps=extraction_tool_identity) as standalone_identity:
            first = self.ws.init()
            standalone_identity.assert_not_called()
        with patch('qecgraph.workspace.ingest', wraps=ingest) as extract:
            reused = self.ws.rebuild()
            self.assertEqual(reused['release_id'], first['release_id'])
            extract.assert_not_called()
            previous_tool = extraction_tool_identity()
            changed_tool = {**previous_tool, 'tool_version': 'changed-processor-fixture'}
            with patch('qecgraph.workspace.extraction_tool_identity', return_value=changed_tool):
                rebuilt = self.ws.rebuild()
            self.assertEqual(rebuilt['counts']['processed'], 1)
            extract.assert_called_once()

    def test_sync_reselects_a_projection_when_an_older_entrypoint_returns(self):
        files = {'a.tex': TEX, 'b.tex': TEX.replace(b'Hello', b'Alternate source')}
        first = tar_bytes(files, mtime=1)
        second = tar_bytes(files, mtime=2)
        tree = unpack(first).digest
        self.ws.init(no_ingest=True)
        config = self.root / 'qecgraph.toml'
        initial = config.read_text()
        entrypoints = f'\n[entrypoints]\n"{tree}" = '

        for raw, entry in ((first, 'a.tex'), (second, 'b.tex'), (first, 'a.tex')):
            with self.subTest(entry=entry):
                config.write_text(initial + entrypoints + f'"{entry}"\n')
                (self.inbox / 'paper').write_bytes(raw)
                result = self.ws.sync()
                self.assertTrue(result['inputs'][0]['input_consumed'])
                state, fixed = self.ws.registry.read()
                identifier, = state['versions']
                graph, _, version = self.ws.registry.source_graph(identifier, fixed)
                self.assertEqual(graph['entry'], entry)
                self.assertEqual(version['snapshot_id'], result['inputs'][0]['source_snapshot_id'])

    def test_rewrapped_archive_does_not_consume_input_when_prior_snapshot_is_damaged(self):
        (self.inbox / 'first.tar').write_bytes(tar_bytes({'paper.tex': TEX}, mtime=1))
        self.assertEqual(self.ws.init()['counts']['processed'], 1)
        state, fixed = self.ws.registry.read()
        identifier, = state['versions']
        _, snapshot, _ = self.ws.registry.source_graph(identifier)
        with (snapshot / 'graph.json').open('ab') as output:
            output.write(b' ')
        rewrapped = tar_bytes({'paper.tex': TEX}, mtime=2)
        path = self.inbox / 'rewrapped.tar'
        path.write_bytes(rewrapped)

        with self.assertRaisesRegex(ValueError, 'Snapshot file changed: graph.json'):
            self.ws.sync()
        self.assertEqual(self.ws.registry.read()[1], fixed)
        payload, = (self.inbox / '.processing').glob('*/payload')
        self.assertEqual(payload.read_bytes(), rewrapped)

    def test_rebuild_detects_a_changed_preserved_archive_member(self):
        raw = tar_bytes({'paper.tex': TEX, 'unused.bin': b'original'})
        (self.inbox / 'paper.tar').write_bytes(raw)
        first = self.ws.init()
        self.assertEqual(first['counts']['processed'], 1)
        preserved = self.root / 'sources' / unpack(raw).digest
        (preserved / 'unused.bin').write_bytes(b'modified')

        result = self.ws.rebuild()
        self.assertEqual(result['status'], 'partial_batch')
        material, = result['inputs']
        self.assertIn('Preserved source tree does not match archive', material['reason'])
        self.assertTrue(material['retained_prior_extraction'])
        self.assertEqual(material['source_snapshot_id'], first['inputs'][0]['source_snapshot_id'])

    def test_sync_rejects_a_snapshot_rewritten_after_generating_proposals(self):
        first = self.ws.init(no_ingest=True)
        (self.inbox / 'paper.tex').write_bytes(TEX)

        def rewrite_after_staging(registry, state, records, **verification):
            count = stage_records(registry, state, records, **verification)
            version, = state['versions'].values()
            snapshot = registry.root / version['snapshot_path']
            graph_path = snapshot / 'graph.json'
            graph = json.loads(graph_path.read_text())
            graph['semantic_status'] = 'changed_after_proposal_capture'
            graph_path.write_text(json.dumps(graph))
            manifest_path = snapshot / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            next(row for row in manifest['outputs'] if row['path'] == 'graph.json')['sha256'] = (
                sha256(graph_path.read_bytes()).hexdigest())
            manifest_path.write_text(json.dumps(manifest))
            return count

        with patch('qecgraph.workspace.stage_records', side_effect=rewrite_after_staging):
            with self.assertRaisesRegex(ValueError, 'Snapshot manifest changed'):
                self.ws.sync()
        self.assertEqual(self.ws.status()['release_id'], first['release_id'])
        payload, = (self.inbox / '.processing').glob('*/payload')
        self.assertEqual(payload.read_bytes(), TEX)

    def test_kill_after_pointer_before_cleanup_recovers_exact_claim(self):
        before = self.ws.init(no_ingest=True)['release_id']
        (self.inbox / 'good').write_bytes(TEX)
        child = dedent('''
            import os
            import signal
            import sys
            from qecgraph import workspace
            from qecgraph.cli import main

            atomic_json = workspace.atomic_json

            def kill_before_cleanup(path, value):
                if path.name == 'commit.json':
                    os.kill(os.getpid(), signal.SIGKILL)
                return atomic_json(path, value)

            workspace.atomic_json = kill_before_cleanup
            raise SystemExit(main(['sync', '--workspace', sys.argv[1], '--json']))
        ''')
        killed = subprocess.run([sys.executable, '-c', child, str(self.root)], capture_output=True, timeout=15)
        self.assertEqual(killed.returncode, -signal.SIGKILL, killed.stderr.decode())
        fixed = self.ws.status()
        self.assertNotEqual(fixed['release_id'], before)
        self.assertEqual(fixed['pending_claims'], 1)
        self.assertTrue(fixed['materials'][0]['processing_completed'])
        payload, = (self.inbox / '.processing').glob('*/payload')
        self.assertEqual(payload.read_bytes(), TEX)
        self.assertFalse((payload.parent / 'commit.json').exists())
        resumed = self.ws.sync()
        self.assertTrue(resumed['inputs'][0]['input_consumed'])
        self.assertEqual(resumed['release_id'], fixed['release_id'])
        self.assertEqual(len(list((self.root / 'archive/receipts').glob('*.json'))), 1)

    def test_init_retries_an_interruption_before_the_first_publication(self):
        package = self.inbox / 'paper.tex'
        package.write_bytes(TEX)
        with patch.object(self.ws.registry, 'publish_prepared', side_effect=RuntimeError('interrupted init')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted init'):
                self.ws.init()
        config_path = self.root / 'qecgraph.toml'
        original_config = config_path.read_bytes()
        self.assertFalse((self.root / 'machine/CURRENT.json').exists())
        self.assertEqual(self.ws.sync(dry_run=True)['pending_claims'], 1)

        result = self.ws.init()
        self.assertEqual(config_path.read_bytes(), original_config)
        self.assertEqual(result['counts']['processed'], 1)
        self.assertTrue(result['inputs'][0]['input_consumed'])
        self.assertTrue(self.ws.validate()['valid'])
        self.assertEqual(self.ws.init()['status'], 'already_initialized')

    def test_missing_pointer_does_not_reset_a_published_workspace(self):
        (self.inbox / 'original.tex').write_bytes(TEX)
        release = self.ws.init()['release_id']
        pointer = self.root / 'machine/CURRENT.json'
        previous = pointer.read_bytes()
        pointer.unlink()
        new_input = self.inbox / 'new.tex'
        new_input.write_bytes(TEX)

        for action in (self.ws.init, self.ws.sync, self.ws.rebuild):
            with self.subTest(action=action.__name__):
                with self.assertRaisesRegex(ValueError, 'Published workspace is missing its release pointer'):
                    action()
                self.assertFalse(pointer.exists())
                self.assertEqual(new_input.read_bytes(), TEX)
        pointer.write_bytes(previous)
        self.assertEqual(self.ws.status()['release_id'], release)
        self.assertTrue(self.ws.validate()['valid'])

    def test_writer_lock_prevents_second_ingest(self):
        self.ws.init(no_ingest=True)
        (self.inbox / 'good').write_bytes(TEX)
        with writer_lock(self.root / '.qecgraph'), self.assertRaisesRegex(ValueError, 'Another writer'):
            self.ws.sync()
        self.assertEqual((self.inbox / 'good').read_bytes(), TEX)

    def test_writer_lock_rejects_linked_and_special_files_before_ingest(self):
        release = self.ws.init(no_ingest=True)['release_id']
        package = self.inbox / 'pending.tex'
        package.write_bytes(TEX)
        target = self.root / 'unmanaged.txt'
        target.write_bytes(b'keep my data')
        lock_path = self.ws.root / '.qecgraph/.writer.lock'
        lock_path.unlink()
        for create in (lambda: lock_path.symlink_to(target), lambda: lock_path.hardlink_to(target),
                       lambda: os.mkfifo(lock_path)):
            create()
            try:
                with self.assertRaises(ManagedDataError) as error:
                    self.ws.sync()
                self.assertEqual(error.exception.path, lock_path)
                self.assertEqual(self.ws.registry.read()[1], release)
                self.assertEqual(package.read_bytes(), TEX)
                self.assertEqual(target.read_bytes(), b'keep my data')
            finally:
                lock_path.unlink()
        self.assertNotEqual(self.ws.sync()['release_id'], release)

    def test_explicit_same_version_conflict_preserves_both(self):
        self.ws.init(no_ingest=True)
        second = TEX.replace(b'Hello', b'Different text')
        with (self.root / 'qecgraph.toml').open('a') as config:
            for raw in (TEX, second):
                config.write(f'\n[sources."{unpack(raw).digest}"]\nwork_id = "work:verified"\nupstream_version = "v3"\n')
        (self.inbox / 'a').write_bytes(TEX)
        (self.inbox / 'b').write_bytes(second)
        result = self.ws.sync()
        self.assertEqual(result['counts']['conflicting'], 2)
        self.assertEqual(len(self.ws.registry.read()[0]['versions']), 2)
        self.assertTrue(all(row['source_version_conflict'] for row in result['inputs']))
        self.assertTrue(all(not row['input_consumed'] for row in result['inputs']))
        self.assertEqual((self.inbox / 'a').read_bytes(), TEX)
        self.assertEqual((self.inbox / 'b').read_bytes(), second)


    def test_extraction_keeps_mentions_separate_and_pins_verbatim_source(self):
        from qecgraph.domain.research_store import load_records
        raw = TEX.replace(b'Hello', b'\nA CSS code has $[[13,1,3]]$.\n\nA classical seed appears near $[[7,1,3]]$.\n')
        (self.inbox / 'example').write_bytes(raw)
        result = self.ws.init()
        self.assertEqual(result['counts']['code_mention_proposals'], 2)
        state, _ = self.ws.registry.read()
        mentions = [r for r in load_records(self.ws.registry, state) if r['kind'] == 'code_parameters_mention']
        self.assertEqual({r['data']['n'] for r in mentions}, {13, None})
        self.assertTrue(all(r['data']['code_ref'] is None and r['data']['distance_interpretation'] is None for r in mentions))
        for mention in mentions:
            loc = mention['field_evidence']['/data/reported_notation']['source_locator']
            self.assertEqual(raw.decode()[loc['char_start']:loc['char_end']], mention['data']['reported_notation'])

    def test_nonadditive_dimension_is_not_a_logical_qubit_count(self):
        from qecgraph.domain.research_store import load_records
        raw = TEX.replace(b'Hello', b'\nA nonadditive quantum code has $((9,12,3))$.\n')
        (self.inbox / 'example').write_bytes(raw)
        self.ws.init()
        state, _ = self.ws.registry.read()
        row, = [r for r in load_records(self.ws.registry, state) if r['kind'] == 'code_parameters_mention']
        self.assertEqual(row['data']['K'], 12)
        self.assertIsNone(row['data']['k'])
        self.assertIsNone(row['data']['distance_interpretation'])

    def test_candidate_failure_leaves_old_release_and_claim_for_retry(self):
        self.ws.init(no_ingest=True)
        release = self.ws.status()['release_id']
        (self.inbox / 'first').write_bytes(TEX)
        with patch.object(self.ws.registry, 'validate', return_value={'passed': False}):
            with self.assertRaisesRegex(ValueError, 'Candidate machine release failed validation'):
                self.ws.sync()
        self.assertEqual(self.ws.status()['release_id'], release)
        self.assertEqual(self.ws.status()['pending_claims'], 1)
        self.assertEqual(len(list((self.root / 'archive/receipts').glob('*.json'))), 1)
        result = self.ws.sync()
        self.assertTrue(result['inputs'][0]['input_consumed'])
        self.assertEqual(result['counts']['processed'], 1)
        self.assertEqual(len(list((self.root / 'archive/receipts').glob('*.json'))), 1)

    def test_archive_write_failure_leaves_the_claim_for_retry(self):
        self.ws.init(no_ingest=True)
        package = self.inbox / 'paper.tex'
        package.write_bytes(TEX)
        job, meta = self.ws._claim(package, False)
        with patch('qecgraph.workspace.os.fsync', side_effect=OSError('archive disk error')):
            with self.assertRaisesRegex(OSError, 'archive disk error'):
                self.ws._archive(job, meta, len(TEX))
        self.assertEqual((job / 'payload').read_bytes(), TEX)
        self.assertEqual(list((self.root / 'archive/blobs/sha256').iterdir()), [])
        self.assertEqual(list((self.root / 'archive/receipts').iterdir()), [])
        self.assertTrue(self.ws.sync()['inputs'][0]['input_consumed'])
