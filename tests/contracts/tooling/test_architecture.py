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
    def test_shared_services_do_not_depend_on_mcp_or_workspace_helpers(self):
        for name in ('core/fs.py', 'core/errors.py', 'knowledge.py', 'knowledge_context.py', 'retrieval.py'):
            for module, _, line in module_imports(PACKAGE / name):
                self.assertNotIn(module, {'mcp.ai_tools', 'workspace'}, f'{name}:{line}')

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
            'import qecgraph, qecgraph.mcp_server, qecgraph.splitter, qecgraph.store, qecgraph.workspace\n'
            'assert "qecgraph.cli" not in __import__("sys").modules\n'
            'assert not any(name.startswith("qecgraph.lean") for name in __import__("sys").modules)\n'
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_compatibility_names_remain_available(self):
        from qecgraph.mcp.ai_tools import TOOL_NAMES
        from qecgraph.cli import main as cli_main
        from qecgraph.mcp_server import main as mcp_main
        from qecgraph.splitter import main as splitter_main
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

