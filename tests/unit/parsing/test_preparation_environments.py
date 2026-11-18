import unittest
from unittest.mock import patch

from qecgraph.preparation.convert import convert_source
from qecgraph.preparation.environments import (
    _source_declarations,
    label_declarations,
)
from qecgraph.preparation.contract import validate_material
from qecgraph.source.package import SourceTree
from tests.unit.parsing.material_fixture import partial_material


class EnvironmentDeclarationTests(unittest.TestCase):
    def convert(self, declaration=b"", option=b"label={key}", **files):
        main = (
            b"\\documentclass{article}"
            + declaration
            + b"\\begin{document}\\begin{box}["
            + option
            + b"]{Title}Body.\\end{box}\\ref{key}\\end{document}"
        )
        tree = SourceTree("tex", {"main.tex": main, **files})
        refs = {"bindings": [], "observed_labels": [{"key": "key"}]}
        return tree, refs, convert_source(tree, "main.tex", refs)

    def test_undeclared_environment_or_nested_option_never_inherits_aux_label(self):
        cases = [
            (b"", b"label={key}"),
            (rb"\newtcolorbox{box}[2][]{title={#1}}", b"label={key}"),
            (rb"\newtcolorbox{box}[2][]{#1}", b"title={a,label={key}}"),
            (rb"\newtcolorbox{box}[2][]{#1}", b"label={key},label={ignored}"),
            (
                rb"\newtcolorbox{box}[2][]{#1}\renewtcolorbox{box}[2][]{#1}",
                b"label={key}",
            ),
        ]
        for declaration, option in cases:
            with self.subTest(declaration=declaration, option=option):
                _, _, (_, doc, coverage) = self.convert(declaration, option)
                self.assertFalse(coverage["complete"])
                self.assertEqual(doc["labels"], [])

    def test_unused_class_declaration_is_not_evidence(self):
        _, _, (_, doc, coverage) = self.convert(
            **{"unused.cls": rb"\newtcolorbox{box}[2][]{#1}"}
        )
        self.assertFalse(coverage["complete"])
        self.assertEqual(doc["environment_label_declarations"], [])

    def test_declared_option_label_has_exact_declaration_origin(self):
        declaration = rb"\newtcolorbox{box}[2][]{colback=red,#1,title=#2}"
        tree, _, (assembly, doc, coverage) = self.convert(declaration)
        self.assertTrue(coverage["complete"], coverage)
        record = doc["environment_label_declarations"][0]
        a, b = record["origin"]["bytes"]
        self.assertEqual(tree.files["main.tex"][a:b], declaration)
        self.assertEqual(doc["labels"][0]["declaration"], record["origin"])
        start, stop = doc["labels"][0]["label_chars"]
        self.assertEqual(assembly.text[start:stop], "label={key}")

    def test_forged_declaration_cannot_pass_source_grammar_validation(self):
        tree, _, (assembly, doc, _) = self.convert(rb"\newtcolorbox{box}[2][]{#1}")
        doc["environment_label_declarations"][0]["supports_label_option"] = False
        files = partial_material(tree, "main.tex", assembly.data, doc)
        with self.assertRaisesRegex(ValueError, "source grammar"):
            validate_material(files)

    def test_declaration_scan_parses_only_sources_with_candidate_command(self):
        tree = SourceTree(
            "tex",
            {
                "main.tex": b"\\documentclass{article}\\begin{document}Body.\\end{document}",
                "plain.sty": b"\\ProvidesPackage{plain}\n\\newcommand{\\x}{X}\n",
                "boxes.cls": b"\\newtcolorbox{box}[2][]{#1}",
            },
        )
        with patch(
            "qecgraph.preparation.environments._source_declarations",
            wraps=_source_declarations,
        ) as scan:
            records = label_declarations(tree, ["main.tex", "plain.sty", "boxes.cls"])
        self.assertEqual([call.args[0] for call in scan.call_args_list], ["boxes.cls"])
        self.assertEqual([record["environment"] for record in records], ["box"])

    def test_command_redefinitions_shadow_declaration_evidence(self):
        for prefix in (
            rb"\renewcommand{\newtcolorbox}[2][]{#2}",
            rb"\DeclareRobustCommand{\newtcolorbox}[2][]{#2}",
            rb"\NewDocumentCommand{\newtcolorbox}{mm}{#2}",
            rb"\RenewDocumentCommand{\newtcolorbox}{mm}{#2}",
        ):
            with self.subTest(prefix=prefix):
                tree = SourceTree(
                    "tex", {"main.tex": prefix + rb"\newtcolorbox{box}[2][]{#1}"}
                )
                self.assertEqual(label_declarations(tree, ["main.tex"]), [])

    def test_environment_redefinition_removes_previously_declared_label_capability(
        self,
    ):
        tree = SourceTree(
            "tex",
            {
                "main.tex": (
                    rb"\newtcolorbox{box}[2][]{#1}"
                    rb"\renewcommand{\box}{\relax}"
                )
            },
        )
        self.assertEqual(label_declarations(tree, ["main.tex"]), [])

    def test_provide_command_after_known_definition_keeps_environment_labels(self):
        load = rb"\usepackage{tcolorbox}"
        provide = rb"\providecommand{\newtcolorbox}[1]{}"
        declaration = rb"\newtcolorbox{box}[2][]{#1}"
        late = load + provide + declaration + rb"\ProvideDocumentCommand{\box}{m}{}"
        _, _, (_, doc, coverage) = self.convert(late)
        self.assertTrue(coverage["complete"], coverage)
        self.assertEqual(doc["labels"][0]["keys"], ["key"])
        for early in (provide + load, rb"\iffalse" + load + rb"\fi" + provide):
            with self.subTest(early=early):
                _, _, (_, doc, coverage) = self.convert(early + declaration)
                self.assertFalse(coverage["complete"])
                self.assertEqual(doc["environment_label_declarations"], [])
