import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qecgraph.graph import build_graph, read_json
from qecgraph.query import context
from qecgraph.store import SnapshotReference, current_snapshot, ingest


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.paper = self.root / 'paper'
        self.paper.mkdir()
        self.entry = self.paper / 'main.tex'
        self.entry.write_text(r'\newtheorem{lemma}{Lemma}\input{a}\input{b}')
        (self.paper / 'a.tex').write_text(r'\begin{lemma}\label{a}Alpha.\end{lemma}')
        (self.paper / 'b.tex').write_text(r'\begin{lemma}\label{b}Beta.\end{lemma}\includegraphics{figure.svg}')
        (self.paper / 'figure.svg').write_text('<svg>one</svg>')
        self.incremental = self.root / 'incremental'
        self.full = self.root / 'full'

    def equivalent(self, **kwargs):
        incremental = ingest(self.entry, 'incremental', self.incremental, incremental=True, **kwargs)
        full = ingest(self.entry, 'incremental', self.full, **kwargs)
        self.assertEqual(incremental['snapshot_id'], full['snapshot_id'])
        left, right = Path(incremental['snapshot']), Path(full['snapshot'])
        for name in ('graph.json', 'sourcegraph.json', 'lemmagraph.json', 'datagraph.json'):
            self.assertEqual(read_json(left / name), read_json(right / name))
        a = SnapshotReference(left, incremental['snapshot_id'])
        b = SnapshotReference(right, full['snapshot_id'])
        self.assertEqual(context(a, 'a', include_candidates=True), context(b, 'a', include_candidates=True))
        return incremental

    def test_changed_leaf_reuses_other_asts_and_detects_same_mtime_same_size(self):
        first = self.equivalent()
        unchanged = self.equivalent()
        self.assertEqual(unchanged['incremental']['ast_misses'], 0)
        leaf = self.paper / 'a.tex'
        stat = leaf.stat()
        leaf.write_text(leaf.read_text().replace('Alpha', 'Omega'))
        os.utime(leaf, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(leaf.stat().st_size, stat.st_size)
        changed = self.equivalent()
        self.assertNotEqual(first['snapshot_id'], changed['snapshot_id'])
        self.assertGreater(changed['incremental']['ast_hits'], 0)
        self.assertGreater(changed['incremental']['ast_misses'], 0)

    def test_learned_theorem_context_cannot_reuse_a_discovery_ast(self):
        self.entry.write_text(r'\newtheorem{custom}{Theorem}\input{a}')
        (self.paper / 'a.tex').write_text(r'\begin{custom}[An explicit title]\label{a}Alpha.\end{custom}')
        result = self.equivalent()
        graph = read_json(Path(result['snapshot']) / 'graph.json')
        theorem = next(node for node in graph['nodes'] if 'a' in node['labels'])
        self.assertEqual((theorem['kind'], theorem['title']), ('theorem', 'An explicit title'))
        self.assertEqual(self.equivalent()['incremental']['ast_misses'], 0)

    def test_macro_config_include_add_delete_and_move_fall_back_safely(self):
        self.equivalent()
        self.entry.write_text(self.entry.read_text().replace('{Lemma}', '{Theorem}'))
        changed = self.equivalent()
        self.assertIn('structural_inputs_changed', changed['incremental']['fallback_reasons'])
        config = self.root / 'config.json'
        config.write_text(json.dumps({'environment_map': {'lemma': 'lemma'}}))
        configured = self.equivalent(config_path=config)
        self.assertIn('config_changed', configured['incremental']['fallback_reasons'])
        (self.paper / 'a.tex').rename(self.paper / 'moved.tex')
        self.entry.write_text(self.entry.read_text().replace('{a}', '{moved}'))
        moved = self.equivalent()
        self.assertIn('source_topology_changed', moved['incremental']['fallback_reasons'])
        (self.paper / 'c.tex').write_text(r'\begin{lemma}\label{c}C.\end{lemma}')
        self.entry.write_text(self.entry.read_text() + r'\input{c}')
        self.equivalent()
        original_current = current_snapshot(self.incremental)
        (self.paper / 'c.tex').unlink()
        deleted = self.equivalent(strict=True)
        self.assertEqual(deleted['extraction_status'], 'partial')
        self.assertEqual(current_snapshot(self.incremental), original_current)
        repeated = self.equivalent(strict=True)
        self.assertIn('previous_unresolved_dependencies', repeated['incremental']['fallback_reasons'])

    def test_asset_change_invalidates_review_even_with_all_asts_reused(self):
        initial = self.equivalent()
        graph = read_json(Path(initial['snapshot']) / 'graph.json')
        hashes = {node['id']: node['content_sha256'] for node in graph['nodes']}
        sidecar = self.root / 'sidecar.json'
        sidecar.write_text(json.dumps({'schema_version': 'qecgraph.annotations.v1', 'edges': [
            {'source': 'label:a', 'target': 'label:b', 'relation': 'depends_on_reviewed',
             'expected_project_source_hash': graph['project_source_hash'],
             'expected_hashes': {graph['labels'][label][0]: hashes[graph['labels'][label][0]] for label in ('a', 'b')}}]}))
        reviewed = self.equivalent(annotations_path=sidecar)
        (self.paper / 'figure.svg').write_text('<svg>two</svg>')
        changed = self.equivalent(annotations_path=sidecar)
        self.assertEqual(changed['incremental']['ast_misses'], 0)
        graph = read_json(Path(changed['snapshot']) / 'graph.json')
        reviewed_edges = [e for e in graph['edges'] if e['relation'] == 'depends_on_reviewed']
        self.assertEqual(reviewed_edges[0]['status'], 'stale')
        self.assertNotEqual(reviewed['snapshot_id'], changed['snapshot_id'])

    def test_corrupt_cache_is_reparsed_and_does_not_change_semantics(self):
        original = self.equivalent()
        for path in (self.incremental / 'cache/ast').glob('*.json'):
            path.write_text('{}')
        rebuilt = self.equivalent()
        self.assertEqual(original['snapshot_id'], rebuilt['snapshot_id'])
        self.assertGreater(rebuilt['incremental']['invalid_cache_entries'], 0)
        (self.incremental / 'cache/incremental-state.json').write_text('{"broken":true}')
        recovered = self.equivalent()
        self.assertIn('invalid_incremental_state', recovered['incremental']['fallback_reasons'])

    def test_repeated_resource_edit_cannot_publish_mixed_input_state(self):
        ingest(self.entry, 'incremental', self.full)
        previous = current_snapshot(self.full)
        leaf = self.paper / 'b.tex'
        leaf.write_text(leaf.read_text() + r'\includegraphics{figure.svg}')
        resource = self.paper / 'figure.svg'
        read_bytes = Path.read_bytes
        edited = False

        def edit_after_capture(path):
            nonlocal edited
            raw = read_bytes(path)
            if path == resource and not edited:
                resource.write_text('<svg>changed</svg>')
                edited = True
            return raw

        with patch.object(Path, 'read_bytes', edit_after_capture):
            with self.assertRaisesRegex(ValueError, 'Input changed during build: figure.svg'):
                ingest(self.entry, 'incremental', self.full)
        self.assertEqual(current_snapshot(self.full), previous)
        self.assertTrue(ingest(self.entry, 'incremental', self.full)['published'])

    def test_edit_during_build_cannot_publish_mixed_input_state(self):
        self.equivalent()
        previous = current_snapshot(self.incremental)

        def edit_after_parse(*args, **kwargs):
            graph = build_graph(*args, **kwargs)
            leaf = self.paper / 'a.tex'
            leaf.write_text(leaf.read_text().replace('Alpha', 'Omega'))
            return graph

        with patch('qecgraph.store.build_graph', side_effect=edit_after_parse):
            with self.assertRaisesRegex(ValueError, 'Input changed during build'):
                ingest(self.entry, 'incremental', self.incremental, incremental=True)
        self.assertEqual(current_snapshot(self.incremental), previous)
        self.equivalent()


if __name__ == '__main__':
    unittest.main()
