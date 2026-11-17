import unittest

from qecgraph.preparation.convert import convert_source
from qecgraph.preparation.contract import SCHEMA, digest, json_bytes, validate_material
from qecgraph.source.package import SourceTree


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
        files = {
            "entry.tex": assembly.data,
            "content.json": json_bytes(doc),
            **{"sources/" + p: raw for p, raw in tree.files.items()},
        }
        files["manifest.json"] = json_bytes(
            {
                "schema": SCHEMA,
                "status": "partial",
                "artifacts": {p: digest(raw) for p, raw in files.items()},
            }
        )
        with self.assertRaisesRegex(ValueError, "source grammar"):
            validate_material(files)
