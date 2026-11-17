"""Lock material bytes and failure outcomes before preparation architecture changes."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.preparation.build import Build
from qecgraph.preparation.contract import digest, validate_material, json_bytes
from qecgraph.preparation.pipeline import _material
from qecgraph.source.package import SourceTree


class PreparationEquivalenceTests(unittest.TestCase):
    CASES = {
        "complete": r"\section{Scope}Unicode α. $x^2$.\label{x}\ref{x}",
        "ambiguous": r"\label{x}One.\label{x}Two.\ref{x}",
        "missing": r"\ref{missing}",
        "inactive": "Visible.\\if 0 a\nHidden.\\fi\n",
        "unobserved_guard": "\\ifdefined\\unavailable\nHidden.\n\\else\nVisible.\n\\fi\n",
        "bibliography": r"See \cite{k}.\bibliographystyle{plain}\bibliography{refs}",
        "compile_failed": "Body.",
        "compile_exception": "Body.",
        "derived_failed": "$x$.",
        "byte_projection_failed": "Byte \udca8.",
    }

    @classmethod
    def capture(cls, name, body):
        raw = (
            r"\documentclass{article}\begin{document}" + body + r"\end{document}"
        ).encode("utf-8", "surrogateescape")
        sources = {"main.tex": raw}
        if name == "bibliography":
            sources["refs.bib"] = (
                b"@article{k,title={Exact source},author={Ada Example},year={2020}}"
            )
        tree = SourceTree("tex", sources)
        calls = []

        def compiler(source, entry, root, **kwargs):
            calls.append(entry)
            source.materialize(root / "project")
            if name == "compile_exception":
                (root / "command.log").write_bytes(b"Preserved failed command")
                raise ValueError("Compiler fixture failed")
            ok = name != "compile_failed" and not (
                name == "derived_failed" and len(calls) > 1
            )
            build = Build(entry, "pdflatex", root, success=ok, inputs=[entry])
            if name == "bibliography":
                emitted = {
                    "main.aux": rb"\citation{k}\bibcite{k}{1}\bibdata{refs}",
                    "main.bbl": rb"\begin{thebibliography}{1}\bibitem{k}Ada Example. Exact source.\end{thebibliography}",
                }
                build.inputs.extend(emitted)
                build.inputs.append("refs.bib")
                for path, data in emitted.items():
                    (root / "project" / path).write_bytes(data)
                    build.artifacts["files/" + path] = data
            return build

        with (
            tempfile.TemporaryDirectory() as temp,
            patch(
                "qecgraph.preparation.build_view.secrets.token_hex",
                return_value="0123456789abcdef",
            ),
        ):
            files, manifest = _material(
                tree, "main.tex", Path(temp), None, (), compiler, {}
            )
        manifest["artifacts"] = {p: digest(raw) for p, raw in sorted(files.items())}
        files["manifest.json"] = json_bytes(manifest)
        validate_material(files)
        return {"manifest": manifest, "compiler_calls": len(calls)}

    def test_material_bytes_and_failure_outcomes_match_v19(self):
        expected = json.loads(
            (Path(__file__).parents[2] / "fixtures/preparation-v19.json").read_bytes()
        )
        for name, body in self.CASES.items():
            with self.subTest(case=name):
                self.assertEqual(self.capture(name, body), expected[name])
