from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.cli import main
from qecgraph.corpus import execute
from qecgraph.source_package import unpack
from qecgraph.store import extraction_tool_identity, ingest
from qecgraph.transactions import writer_lock
from qecgraph.workspace import Workspace
from test_source_package import TEX, tar_bytes


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
        first = self.ws.init()
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

    def test_kill_after_pointer_before_cleanup_recovers_exact_claim(self):
        self.ws.init(no_ingest=True)
        (self.inbox / 'good').write_bytes(TEX)
        with patch('qecgraph.workspace.atomic_json', side_effect=RuntimeError('simulated termination')) as write:
            from qecgraph.transactions import atomic_json
            def interrupt(path, value):
                if path.name == 'commit.json':
                    raise RuntimeError('simulated termination')
                return atomic_json(path, value)
            write.side_effect = interrupt
            with self.assertRaisesRegex(RuntimeError, 'simulated termination'):
                self.ws.sync()
        fixed = self.ws.status()
        self.assertEqual(fixed['pending_claims'], 1)
        self.assertTrue(fixed['materials'][0]['processing_completed'])
        resumed = self.ws.sync()
        self.assertTrue(resumed['inputs'][0]['input_consumed'])
        self.assertEqual(resumed['release_id'], fixed['release_id'])
        self.assertEqual(len(list((self.root / 'archive/receipts').glob('*.json'))), 1)

    def test_writer_lock_prevents_second_ingest(self):
        self.ws.init(no_ingest=True)
        (self.inbox / 'good').write_bytes(TEX)
        with writer_lock(self.root / '.qecgraph'), self.assertRaisesRegex(ValueError, 'Another writer'):
            self.ws.sync()
        self.assertEqual((self.inbox / 'good').read_bytes(), TEX)

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
        from qecgraph.research_store import load_records
        raw = TEX.replace(b'Hello', b'\nA CSS code has $[[13,1,3]]$.\n\nA classical seed appears near $[[7,1,3]]$.\n')
        (self.inbox / 'example').write_bytes(raw)
        result = self.ws.init()
        self.assertEqual(result['counts']['code_mention_proposals'], 2)
        state, _ = self.ws.registry.read()
        mentions = [r for r in load_records(self.ws.registry, state) if r['kind'] == 'code_mention']
        self.assertEqual({r['data']['n_data'] for r in mentions}, {13, None})
        self.assertTrue(all(r['data']['code_ref'] is None and r['data']['distance_interpretation'] is None for r in mentions))
        for mention in mentions:
            loc = mention['field_evidence']['/data/reported_notation']['source_locator']
            self.assertEqual(raw.decode()[loc['char_start']:loc['char_end']], mention['data']['reported_notation'])

    def test_nonadditive_dimension_is_not_a_logical_qubit_count(self):
        from qecgraph.research_store import load_records
        raw = TEX.replace(b'Hello', b'\nA nonadditive quantum code has $((9,12,3))$.\n')
        (self.inbox / 'example').write_bytes(raw)
        self.ws.init()
        state, _ = self.ws.registry.read()
        row, = [r for r in load_records(self.ws.registry, state) if r['kind'] == 'code_mention']
        self.assertEqual(row['data']['K'], 12)
        self.assertIsNone(row['data']['k_logical'])
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
