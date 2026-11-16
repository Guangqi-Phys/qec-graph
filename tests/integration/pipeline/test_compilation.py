"""Explicit local compiler checks; ordinary tests never execute untrusted TeX."""
import os
from pathlib import Path
import tempfile
import unittest

from qecgraph.preparation import sandbox
from qecgraph.preparation.build import compile_tree
from qecgraph.source.package import SourceTree


@unittest.skipUnless(os.environ.get("QECGRAPH_TEST_TEX") == "1", "Set QECGRAPH_TEST_TEX=1 for isolated local TeX checks")
class LocalCompilerTests(unittest.TestCase):
    def test_custom_citation_and_bibtex_are_resolved_without_source_edits(self):
        original = br"""\documentclass{article}
\newcommand{\citeRef}[1]{\cite{ref:#1}}
\begin{document}An upper bound $d\leq12$. See \citeRef0.
\bibliographystyle{plain}\bibliography{references}\end{document}
"""
        tree = SourceTree("tex", {"main.tex": original, "references.bib":
            b'@article{ref:0,author={Ada Example},title={A compiler fixture},journal={Test},year={2020}}'})
        with tempfile.TemporaryDirectory() as temp:
            build = compile_tree(tree, "main.tex", Path(temp))
            self.assertTrue(build.success, build.steps)
            aux = build.artifacts["files/main.aux"]
            self.assertIn(br"\citation{ref:0}", aux)
            self.assertIn(br"\bibcite{ref:0}", aux)
            self.assertEqual(tree.files["main.tex"], original)

    def test_sandbox_denies_external_files_network_and_inherited_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            secret = parent / "sentinel.txt"
            secret.write_text("test sentinel")
            work = parent / "allowed"
            work.mkdir()
            command = ["/bin/sh", "-c", 'cat "$1"; touch "$2"; test -z "$OPENROUTER_API_KEY"',
                       "probe", str(secret), str(parent / "forbidden")]
            result = sandbox.run(work, work, command)
            self.assertNotIn(b"test sentinel", result["log"])
            self.assertFalse((parent / "forbidden").exists())
            self.assertEqual(result["exit"], 0)
            network = sandbox.run(work, work, ["/usr/bin/curl", "-v", "--max-time", "2", "http://127.0.0.1:9"])
            self.assertIn(b"Operation not permitted", network["log"])
