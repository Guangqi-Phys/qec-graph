"""Guard preparation dependency direction and its explicit preparation-only scope."""

import ast
import unittest

from tests.support import ROOT


class PreparationArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.paths = sorted((ROOT / "qecgraph/preparation").glob("*.py"))
        self.imports = {
            path.stem: [
                node
                for node in ast.walk(ast.parse(path.read_text()))
                if isinstance(node, ast.ImportFrom)
            ]
            for path in self.paths
        }
        self.graph = {
            name: {
                dependency
                for node in nodes
                if node.level == 1
                for dependency in (
                    [node.module.split(".")[0]]
                    if node.module
                    else [item.name for item in node.names]
                )
                if dependency in self.imports
            }
            for name, nodes in self.imports.items()
        }

    def test_preparation_imports_are_acyclic_including_deferred_imports(self):
        pending = {name: set(edges) for name, edges in self.graph.items()}
        while pending:
            leaves = {name for name, edges in pending.items() if not edges}
            self.assertTrue(leaves, f"Preparation import cycle: {pending}")
            pending = {
                name: edges - leaves
                for name, edges in pending.items()
                if name not in leaves
            }

    def test_shared_material_rules_do_not_depend_on_compilation_or_publication(self):
        pure = {
            "__init__",
            "artifacts",
            "reference_syntax",
            "options",
            "branches",
            "conditions",
            "capabilities",
            "crossrefs",
            "material",
        }
        for name in pure:
            with self.subTest(module=name):
                self.assertLessEqual(self.graph[name], pure)

    def test_only_orchestration_and_acceptance_import_the_handoff_validator(self):
        callers = {name for name, edges in self.graph.items() if "contract" in edges}
        self.assertEqual(callers, {"pipeline", "acceptance"})

    def test_preparation_does_not_import_models_or_scientific_extraction(self):
        for name, nodes in self.imports.items():
            for node in nodes:
                module = node.module or ""
                with self.subTest(module=name, dependency=module):
                    self.assertFalse(module.startswith(("llm", "workspace", "domain")))
                    self.assertNotEqual(module, "source.parser")
                    self.assertFalse(
                        module.startswith(
                            (
                                "qecgraph.llm",
                                "qecgraph.workspace",
                                "qecgraph.domain",
                                "qecgraph.source.parser",
                            )
                        )
                    )
