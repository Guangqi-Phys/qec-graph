import ast
import os
import subprocess
import sys
import unittest


from tests.support import ROOT
PACKAGE = ROOT / 'qecgraph'
FORBIDDEN_PREFIXES = ('tests', 'tools', 'legacy', 'validation')


def module_imports(path):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.col_offset, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, node.col_offset, node.lineno


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_kernel_and_shared_services_do_not_import_higher_layers(self):
        shared = ('core/fs.py', 'core/errors.py', 'knowledge.py', 'knowledge_context.py', 'retrieval.py')
        boundaries = dict.fromkeys(shared, {'mcp.ai_tools', 'workspace'})
        boundaries['retrieval.py'] = boundaries['retrieval.py'] | {'workspace_query'}
        boundaries.update({'core/graph.py': {'validators'}, 'core/relations.py': {'validators'}})
        for name, forbidden in boundaries.items():
            for module, _, line in module_imports(PACKAGE / name):
                self.assertNotIn(module.removeprefix('qecgraph.'), forbidden, f'{name}:{line}')

    def test_runtime_package_does_not_import_development_layers(self):
        for path in PACKAGE.rglob('*.py'):
            for module, _, lineno in module_imports(path):
                with self.subTest(path=str(path.relative_to(ROOT)), module=module):
                    self.assertFalse(module.split('.')[0] in FORBIDDEN_PREFIXES,
                                     f'{path.relative_to(ROOT)}:{lineno} imports {module}')

    def test_only_cli_modules_import_cli_at_module_scope(self):
        for path in PACKAGE.rglob('*.py'):
            if 'cli' in path.relative_to(PACKAGE).parts or path.name == '__main__.py':
                continue
            for module, column, lineno in module_imports(path):
                if module == 'qecgraph.cli' or module.startswith('qecgraph.cli.'):
                    with self.subTest(path=str(path.relative_to(ROOT))):
                        self.assertGreater(column, 0,
                                           f'{path.relative_to(ROOT)}:{lineno} imports CLI at module scope')

    def test_importing_read_surfaces_does_not_load_cli_or_lean(self):
        code = (
            'import qecgraph, qecgraph.mcp.server, qecgraph.source.splitter, qecgraph.store, qecgraph.workspace\n'
            'assert "qecgraph.cli" not in __import__("sys").modules\n'
            'assert not any(name.startswith("qecgraph.lean") for name in __import__("sys").modules)\n'
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_entrypoints_are_callable(self):
        from qecgraph.mcp.ai_tools import TOOL_NAMES
        from qecgraph.cli import main as cli_main
        from qecgraph.mcp.server import main as mcp_main
        from qecgraph.source.splitter import main as splitter_main
        from qecgraph.store import ingest
        from qecgraph.workspace import Workspace

        self.assertTrue(callable(cli_main))
        self.assertTrue(callable(mcp_main))
        self.assertTrue(callable(splitter_main))
        self.assertTrue(callable(ingest))
        self.assertTrue(Workspace)
        self.assertEqual(TOOL_NAMES, (
            'qecgraph_search', 'qecgraph_show', 'qecgraph_context',
            'qecgraph_deps', 'qecgraph_impact',
        ))

    def test_default_discovery_collects_query_and_assembly_regressions(self):
        def ids(suite):
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    yield from ids(item)
                else:
                    yield item.id()

        suite = unittest.TestLoader().discover(str(ROOT / 'tests'), top_level_dir=str(ROOT))
        discovered = set(ids(suite))
        for identifier in (
            'tests.unit.query.test_lexical.LexicalTests.test_natural_queries_rank_all_terms_before_partial',
            'tests.unit.query.test_lexical.LexicalTests.test_qec_brackets_and_whitespace_share_terms',
            'tests.unit.parsing.test_assembly.AssembleTests.test_missing_preamble_include_is_a_dependency_not_content_loss',
        ):
            self.assertIn(identifier, discovered)

    def test_test_suite_is_layered_by_scope(self):
        tests_root = ROOT / 'tests'
        modules = list(tests_root.rglob('test_*.py'))
        self.assertGreater(len(modules), 20)
        for module in modules:
            layer = module.relative_to(tests_root).parts[0]
            with self.subTest(module=str(module.relative_to(ROOT))):
                self.assertIn(layer, {'unit', 'integration', 'contracts'})
                self.assertNotEqual(module.parent, tests_root,
                                    f'{module.relative_to(ROOT)} is not in a layer')

if __name__ == '__main__':
    unittest.main()

