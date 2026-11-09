import gzip
import io
import tarfile
import unittest
import zipfile

from qecgraph.source_package import Limits, PackageError, unpack

TEX = b'\\documentclass{article}\r\n\\begin{document}Hello\\end{document}\r\n'


def tar_bytes(files, *, mtime=0):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as output:
        for name, value in files.items():
            item = tarfile.TarInfo(name)
            item.mtime = mtime
            if value is None:
                item.type = tarfile.SYMTYPE
                item.linkname = '../outside'
                output.addfile(item)
            else:
                item.size = len(value)
                output.addfile(item, io.BytesIO(value))
    return buffer.getvalue()


class SourcePackageTests(unittest.TestCase):
    def test_content_identity_ignores_headers_but_preserves_every_asset_byte(self):
        a = tar_bytes({'paper.tex': TEX, 'figure.dat': b'\x00'}, mtime=1)
        b = tar_bytes({'figure.dat': b'\x00', 'paper.tex': TEX}, mtime=2)
        left, right = unpack(a), unpack(gzip.compress(b))
        self.assertNotEqual(a, b)
        self.assertEqual(left.digest, right.digest)
        self.assertEqual(left.files['paper.tex'], TEX)
        self.assertNotEqual(left.digest, unpack(tar_bytes({'paper.tex': TEX})).digest)
        self.assertEqual(unpack(gzip.compress(TEX)).format, 'gzip_tex')

    def test_unsafe_paths_types_and_case_collisions_are_rejected_before_materializing(self):
        for files in ({'../out': TEX}, {'C:/out': TEX}, {'link': None},
                      {'Tex/a.tex': TEX, 'tex/b.tex': TEX}, {'file': TEX, 'file/child': TEX}):
            with self.subTest(files=files), self.assertRaises(PackageError) as caught:
                unpack(tar_bytes(files))
            self.assertEqual(caught.exception.status, 'unsafe_archive')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as output:
            output.writestr('/absolute', TEX)
        with self.assertRaisesRegex(PackageError, 'Unsafe archive path'):
            unpack(buf.getvalue())

    def test_entrypoints_are_ambiguous_and_member_limit_enforced(self):
        raw = tar_bytes({'short.tex': TEX, 'long.tex': TEX * 2})
        self.assertEqual(unpack(raw).entrypoints(), ['long.tex', 'short.tex'])
        with self.assertRaises(PackageError) as caught:
            unpack(raw, Limits(member_bytes=len(TEX)))
        self.assertEqual(caught.exception.status, 'limit_exceeded')

    def test_entrypoint_discovery_ignores_non_tex_examples(self):
        raw = tar_bytes({'main.TeX': TEX, 'README.txt': TEX, '.tex': TEX})
        self.assertEqual(unpack(raw).entrypoints(), ['main.TeX'])

    def test_package_detection_rejects_a_damaged_trailer_and_non_tex_prefixes(self):
        tar = tar_bytes({'main.tex': TEX})
        for raw, expected in ((tar[:-1] + b'x', 'damaged_archive'),
                              (b' \t<!DoCtYpE HTML>\n' + TEX, 'unsupported_format'),
                              (b'\r\n%PdF-1.7\n' + TEX, 'unsupported_format')):
            with self.subTest(expected=expected), self.assertRaises(PackageError) as error:
                unpack(raw)
            self.assertEqual(error.exception.status, expected)

    def test_gzip_accepts_split_members_and_checks_crc_and_expanded_limit(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr('main.tex', TEX)
        zip_raw = buf.getvalue()
        wrapped_zip = unpack(gzip.compress(zip_raw[:10]) + gzip.compress(zip_raw[10:]))
        self.assertEqual((wrapped_zip.format, wrapped_zip.files), ('gzip_zip', {'main.tex': TEX}))

        tar = tar_bytes({'main.tex': TEX}).ljust((4 << 20) + len(TEX), b'\0')
        limits = Limits(expanded_bytes=len(TEX))
        package = gzip.compress(tar)
        self.assertEqual(unpack(package, limits).files, {'main.tex': TEX})
        broken_crc = package[:-8] + bytes([package[-8] ^ 1]) + package[-7:]
        for raw, status in ((broken_crc, 'damaged_archive'),
                            (gzip.compress(tar[:-1] + b'x'), 'damaged_archive'),
                            (gzip.compress(tar + b'\0'), 'limit_exceeded')):
            with self.subTest(status=status), self.assertRaises(PackageError) as error:
                unpack(raw, limits)
            self.assertEqual(error.exception.status, status)
