import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from qecgraph.ai_tools import ReadOnlySession, TOOL_NAMES
from qecgraph.query import context, search
from qecgraph.registry import Registry
from qecgraph.store import ingest


class AIToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.paper = self.root / 'paper'
        self.paper.mkdir()
        self.entry = self.paper / 'main.tex'
        self.entry.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{a}Assuming H, full conclusion.\end{lemma}'
                              r'\begin{lemma}\label{b}B.\uses{a}\end{lemma}')
        self.store = self.root / 'store'
        self.result = ingest(self.entry, 'ai', self.store)

    def hashes(self):
        return {str(p.relative_to(self.store)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.store.rglob('*') if p.is_file()}

    def test_read_only_outputs_reuse_query_and_validate_contract(self):
        before = self.hashes()
        session = ReadOnlySession(store=self.store)
        self.assertEqual(tuple(tool['name'] for tool in session.tools()), TOOL_NAMES)
        for tool in session.tools():
            arguments = {'query': 'full'} if tool['name'] == 'qecgraph_search' else {'identifier': 'b'}
            envelope = session.invoke(tool['name'], arguments)
            self.assertTrue(envelope['ok'], envelope)
            Draft202012Validator(tool['outputSchema']).validate(envelope)
            self.assertTrue(tool['annotations']['readOnlyHint'])
            self.assertEqual(envelope['data']['scope']['snapshot_id'], self.result['snapshot_id'])
        via_tool = session.invoke('qecgraph_context', {'identifier': 'b'})['data']
        direct = context(self.store, 'b')
        self.assertEqual(via_tool['nodes'], direct['nodes'])
        self.assertEqual(via_tool['edges'], direct['edges'])
        self.assertEqual(self.hashes(), before)
        via_tool['nodes'][0]['latex'] = 'caller mutation'
        self.assertNotEqual(session.invoke('qecgraph_context', {'identifier': 'b'})['data']['nodes'][0]['latex'], 'caller mutation')

    def test_session_stays_on_old_snapshot_and_detects_tampering(self):
        session = ReadOnlySession(store=self.store)
        self.entry.write_text(self.entry.read_text().replace('full conclusion', 'new conclusion'))
        ingest(self.entry, 'ai', self.store)
        old = session.invoke('qecgraph_show', {'identifier': 'a'})
        self.assertIn('full conclusion', old['data']['node']['latex'])
        self.assertEqual(old['data']['scope']['snapshot_id'], self.result['snapshot_id'])
        source = Path(self.result['snapshot']) / 'sources/main.tex'
        source.write_text('tampered')
        self.assertFalse(session.invoke('qecgraph_show', {'identifier': 'a'})['ok'])

    def test_pinned_sessions_refuse_a_replaced_graph_with_rewritten_checksums(self):
        registry = Registry(self.root / 'corpus')
        registry.register_source('work:ai', 'version:ai:1', self.store)
        _, archive, _ = registry.source_graph('version:ai:1')
        for session, snapshot, selector in (
            (ReadOnlySession(store=self.store), Path(self.result['snapshot']), 'a'),
            (ReadOnlySession(corpus=registry.root), archive, 'version:ai:1::a'),
        ):
            with self.subTest(selector=selector):
                args = {'identifier': selector}
                self.assertTrue(session.invoke('qecgraph_show', args)['ok'])
                graph_path = snapshot / 'graph.json'
                graph = json.loads(graph_path.read_text())
                node = next(n for n in graph['nodes'] if 'a' in n['labels'])
                node['title'] = 'A rewritten title'
                raw = json.dumps(graph).encode()
                graph_path.write_bytes(raw)
                manifest_path = snapshot / 'manifest.json'
                manifest = json.loads(manifest_path.read_text())
                checksum = next(o for o in manifest['outputs'] if o['path'] == 'graph.json')
                checksum['sha256'] = hashlib.sha256(raw).hexdigest()
                manifest_path.write_text(json.dumps(manifest))
                result = session.invoke('qecgraph_show', args)
                self.assertFalse(result['ok'])
                self.assertIn('Snapshot manifest changed', result['error']['message'])

    def test_snapshot_queries_refuse_unbound_sqlite_journal_content(self):
        snapshot = Path(self.result['snapshot'])
        database = snapshot / 'graph.sqlite'
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(connection.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            connection.execute('PRAGMA wal_autocheckpoint=0')
            main_bytes = database.read_bytes()
            manifest_path = snapshot / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            checksum = next(o for o in manifest['outputs'] if o['path'] == 'graph.sqlite')
            checksum['sha256'] = hashlib.sha256(main_bytes).hexdigest()
            manifest_path.write_text(json.dumps(manifest))

            connection.execute("UPDATE nodes SET title='Unbound SQLite title'")
            connection.commit()
            self.assertEqual(database.read_bytes(), main_bytes)
            self.assertGreater((snapshot / 'graph.sqlite-wal').stat().st_size, 0)
            with self.assertRaisesRegex(ValueError, 'Unbound SQLite sidecar'):
                ReadOnlySession(store=self.store)
            with self.assertRaisesRegex(ValueError, 'Unbound SQLite sidecar'):
                search(self.store, 'full')
        finally:
            connection.close()

    def test_explicit_snapshot_cannot_follow_a_link_outside_its_store(self):
        snapshot = Path(self.result['snapshot'])
        outside = self.root / 'detached' / snapshot.name
        outside.parent.mkdir()
        snapshot.rename(outside)
        snapshot.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Path escapes root'):
            ReadOnlySession(store=self.store, snapshot_id=self.result['snapshot_id'])

    def test_budget_refuses_partial_root_and_marks_missing_dependencies(self):
        huge = 'Assumption H. ' * 1000
        self.entry.write_text(r'\newtheorem{lemma}{Lemma}\begin{lemma}\label{huge}' + huge + r'\end{lemma}'
                              r'\begin{lemma}\label{small}Small complete statement.\uses{huge}\end{lemma}')
        ingest(self.entry, 'ai', self.store)
        session = ReadOnlySession(store=self.store)
        refused = session.invoke('qecgraph_context', {'identifier': 'huge', 'max_chars': 3000})
        self.assertFalse(refused['ok'])
        self.assertEqual(refused['error']['code'], 'BUDGET_ROOT_TOO_LARGE')
        limited = session.invoke('qecgraph_context', {'identifier': 'small', 'max_chars': 4000})
        self.assertTrue(limited['ok'], limited)
        data = limited['data']
        self.assertTrue(data['truncated'])
        self.assertFalse(data['context_complete'])
        self.assertIn('Small complete statement.', data['nodes'][0]['latex'])
        self.assertGreater(data['budget']['omitted_nodes'], 0)
        self.assertLessEqual(len(json.dumps(data, ensure_ascii=False, separators=(',', ':'))), 4000)

    def test_scope_budget_schema_ambiguity_and_empty_results(self):
        session = ReadOnlySession(store=self.store, max_nodes=5)
        context_tool = next(tool for tool in session.tools() if tool['name'] == 'qecgraph_context')
        context_tool['inputSchema']['properties']['max_nodes']['maximum'] = 100
        for arguments in ({'identifier': 'a', 'max_nodes': 6}, {'identifier': 'a', 'store': '/tmp/another'}, {'identifier': 'a', 'depth': -1}):
            self.assertEqual(session.invoke('qecgraph_context', arguments)['error']['code'], 'INVALID_ARGUMENT')
        self.assertEqual(session.invoke('qecgraph_search', {'query': 'no such text'})['data']['results'], [])
        self.assertTrue(session.invoke('qecgraph_search', {'query': 'lemma', 'limit': 1})['data']['truncated'])
        self.assertTrue(session.invoke('qecgraph_deps', {'identifier': 'b', 'depth': 0})['data']['truncated'])
        self.assertEqual(session.invoke('qecgraph_show', {'identifier': 'missing'})['error']['code'], 'NOT_FOUND')
        self.entry.write_text(self.entry.read_text() + r'\begin{lemma}\label{a}Other occurrence.\end{lemma}')
        ingest(self.entry, 'ai', self.store)
        ambiguous = ReadOnlySession(store=self.store).invoke('qecgraph_show', {'identifier': 'a'})
        self.assertEqual(ambiguous['error']['code'], 'AMBIGUOUS_SELECTOR')

    def test_corpus_fixed_scope_and_cli_python_are_identical(self):
        registry = Registry(self.root / 'corpus')
        registered = registry.register_source('work:ai', 'version:ai:1', self.store)
        session = ReadOnlySession(corpus=registry.root)
        args = {'identifier': 'version:ai:1::a'}
        expected = session.invoke('qecgraph_show', args)
        self.assertTrue(expected['ok'])
        self.assertEqual(expected['data']['node']['source']['source_version_id'], 'version:ai:1')
        arguments = self.root / 'arguments.json'
        arguments.write_text(json.dumps(args))
        result = subprocess.run([sys.executable, '-m', 'qecgraph', 'query-tool', 'qecgraph_show', '--arguments', str(arguments),
                                 '--corpus', str(registry.root), '--registry-revision', registered['registry_revision']],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(session.invoke('qecgraph_show', {'identifier': 'a'})['error']['code'], 'SCOPE_REQUIRED')
        _, archive, _ = registry.source_graph('version:ai:1')
        (archive / 'sources/main.tex').write_text('tampered archived corpus source')
        self.assertFalse(session.invoke('qecgraph_show', args)['ok'])


if __name__ == '__main__':
    unittest.main()
