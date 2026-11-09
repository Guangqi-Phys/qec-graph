import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.corpus import execute
from qecgraph.source_package import unpack
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
