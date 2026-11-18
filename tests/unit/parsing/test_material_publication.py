"""Publication and recovery contracts used by native preparation."""

import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.preparation import PREPARATION_VERSION
from qecgraph.preparation.artifacts import SCHEMA, digest, json_bytes
from qecgraph.preparation.inputs import load_for_preparation
from qecgraph.preparation.publication import publish_artifacts, recover_output
from qecgraph.source.package import PackageError, unpack


def files(text):
    return {
        "entry.tex": text.encode(),
        "manifest.json": json_bytes(
            {"schema": SCHEMA, "rule_version": PREPARATION_VERSION, "entry": "main.tex"}
        ),
    }


class MaterialPublicationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.out = self.root / "prepared"
        self.staging = self.root / ".prepared.staging-test"
        self.backup = self.root / ".prepared.backup-test"
        self.journal = self.root / ".prepared.transaction.json"

    def interrupt(self):
        publish_artifacts(files("First text."), self.out)
        previous = (self.out / "manifest.json").read_bytes()
        self.out.rename(self.backup)
        self.staging.mkdir()
        payload = {**files("New text."), "manifest.json": b"new manifest"}
        for name, raw in payload.items():
            (self.staging / name).write_bytes(raw)
        self.journal.write_bytes(
            json_bytes(
                {
                    "out": self.out.name,
                    "staging": self.staging.name,
                    "backup": self.backup.name,
                    "phase": "backup",
                    "previous_manifest_sha256": digest(previous),
                    "new_manifest_sha256": digest(payload["manifest.json"]),
                    "artifacts": {name: digest(raw) for name, raw in payload.items()},
                }
            )
        )
        return previous

    def test_interrupted_replacement_restores_previous_output(self):
        previous = self.interrupt()
        self.assertEqual(recover_output(self.out), "restored")
        self.assertEqual((self.out / "manifest.json").read_bytes(), previous)
        self.assertEqual(set(self.root.iterdir()), {self.out})

    def test_conflict_preserves_backup_and_journal(self):
        self.interrupt()
        self.out.mkdir()
        other = self.out / "user.txt"
        other.write_text("unrelated")
        self.assertEqual(recover_output(self.out), "conflict")
        with self.assertRaisesRegex(ValueError, "conflicts"):
            publish_artifacts(files("Refused."), self.out)
        self.assertEqual(other.read_text(), "unrelated")
        self.assertTrue(self.backup.is_dir())
        self.assertTrue(self.journal.is_file())

        other.unlink()
        (self.out / "manifest.json").write_bytes(b"new manifest")
        self.assertEqual(recover_output(self.out), "conflict")
        self.assertEqual((self.backup / "entry.tex").read_text(), "First text.")

    @unittest.skipUnless(os.name == "posix", "requires POSIX replacement semantics")
    def test_real_interrupted_replacement_is_recovered_by_the_next_publish(self):
        publish_artifacts(files("First text."), self.out)
        script = """
import os, sys
from pathlib import Path
from tests.unit.parsing.test_material_publication import files, publish_artifacts
real = os.replace
def trap(src, dst):
    real(src, dst)
    if ".backup-" in str(dst):
        os._exit(77)
os.replace = trap
publish_artifacts(files("Second text."), Path(sys.argv[1]))
"""
        child = subprocess.run(
            [sys.executable, "-c", script, str(self.out)],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
        )
        self.assertEqual(child.returncode, 77, child.stderr)
        self.assertFalse(self.out.exists())
        publish_artifacts(files("Third text."), self.out)
        self.assertEqual((self.out / "entry.tex").read_text(), "Third text.")
        self.assertEqual(set(self.root.iterdir()), {self.out})

    def test_current_output_replaces_as_a_whole(self):
        publish_artifacts(files("First text."), self.out)
        obsolete = self.out / "stale.json"
        obsolete.write_text("{}")
        publish_artifacts(files("Second text."), self.out)
        self.assertFalse(obsolete.exists())
        self.assertEqual((self.out / "entry.tex").read_text(), "Second text.")

    def test_unmanaged_or_superseded_output_requires_explicit_overwrite(self):
        self.out.mkdir()
        canary = self.out / "entry.tex"
        canary.write_text("User input.")
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            publish_artifacts(files("New text."), self.out)
        self.assertEqual(canary.read_text(), "User input.")
        (self.out / "manifest.json").write_bytes(
            json_bytes({"schema": "qecgraph.prepare/2", "entry": "main.tex"})
        )
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            publish_artifacts(files("New text."), self.out)
        self.assertEqual(canary.read_text(), "User input.")
        publish_artifacts(files("New text."), self.out, overwrite=True)
        self.assertEqual(canary.read_text(), "New text.")

    def test_output_cannot_overlap_the_source_or_follow_links(self):
        source = self.root / "source"
        source.mkdir()
        for target in (source, source / "child", self.root):
            with (
                self.subTest(target=target),
                self.assertRaisesRegex(ValueError, "inside"),
            ):
                publish_artifacts(files("New text."), target, source=source)
        self.out.symlink_to(source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic-link"):
            publish_artifacts(files("New text."), self.out)
        self.assertEqual(list(source.iterdir()), [])

    def test_write_failure_keeps_a_complete_output(self):
        publish_artifacts(files("First text."), self.out)
        with (
            patch(
                "qecgraph.preparation.publication._write_artifacts",
                side_effect=OSError("disk full"),
            ),
            self.assertRaisesRegex(OSError, "disk full"),
        ):
            publish_artifacts(files("Second text."), self.out)
        self.assertEqual((self.out / "entry.tex").read_text(), "First text.")
        self.assertEqual(set(self.root.iterdir()), {self.out})

    def test_missing_tar_footer_is_repaired_with_exact_members(self):
        source = rb"\documentclass{article}\begin{document}Original.\end{document}"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo("main.tex")
            info.size = len(source)
            archive.addfile(info, io.BytesIO(source))
        short = buffer.getvalue()[:1024]
        path = self.root / "paper.tar"
        path.write_bytes(short)
        with self.assertRaises(PackageError):
            unpack(short)
        tree, records = load_for_preparation(path)
        self.assertEqual(tree.files["main.tex"], source)
        self.assertEqual(path.read_bytes(), short)
        self.assertEqual(records[0]["appended_bytes"], 1024)
