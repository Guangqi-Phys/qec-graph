"""Byte spelling keeps UTF-8 data and proves every non-UTF-8 replacement."""

import unittest
from types import SimpleNamespace
from qecgraph.preparation.projection import prepare_projection

from qecgraph.preparation.projection import (
    project_bytes,
    candidate_tree,
    original_locator,
)
from qecgraph.source.package import SourceTree
from qecgraph.preparation.contract import digest


class ByteProjectionTests(unittest.TestCase):
    def test_mixed_utf8_and_invalid_bytes_have_reversible_segment_tiling(self):
        raw = "Alpha α ".encode() + b"\xa8 and \xff\r\n"
        projected, segments = project_bytes(raw)
        self.assertEqual(projected, "Alpha α ^^a8 and ^^ff\r\n".encode())
        recovered, cursor = bytearray(), 0
        text = projected.decode()
        for segment in segments:
            a, b = segment["output_chars"]
            lo, hi = segment["input_bytes"]
            self.assertEqual(lo, cursor)
            if segment["operation"] == "copy":
                recovered.extend(text[a:b].encode())
            else:
                recovered.extend(bytes.fromhex(text[a + 2 : b]))
            cursor = hi
        self.assertEqual(bytes(recovered), raw)
        self.assertEqual(cursor, len(raw))

    def test_original_locator_uses_bytes_and_covers_partial_escape_without_unicode_guess(
        self,
    ):
        raw = b"Alpha \xa8 end."
        tree, records = candidate_tree(
            SourceTree("tex", {"main.tex": raw}), ["main.tex"]
        )
        span = {"path": "main.tex", "chars": [7, 8]}
        origin = original_locator(
            span, records[0], {"projected-sources/main.tex": tree.files["main.tex"]}
        )
        self.assertEqual(origin["bytes"], [6, 7])
        self.assertEqual(origin["sha256"], digest(raw))
        self.assertNotIn("chars", origin)

    def test_unused_invalid_sources_and_binary_assets_are_not_projected(self):
        raw = b"\xff\xfe"
        tree = SourceTree(
            "tex", {"main.tex": b"Body.", "other.tex": raw, "plot.png": raw}
        )
        projected, records = candidate_tree(tree, ["main.tex", "plot.png"])
        self.assertEqual(projected.files, tree.files)
        self.assertEqual(records, [])

    def test_projection_refuses_a_catcode_change_before_any_probe(self):
        tree = SourceTree("tex", {"main.tex": b"\\catcode`\\^=12\nBody \xa8."})
        build = SimpleNamespace(inputs=["main.tex"], engine="pdflatex")
        with self.assertRaisesRegex(ValueError, "catcode"):
            prepare_projection(build, tree, (), None, {})
