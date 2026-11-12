import gzip
import io
import struct
import tarfile
import unittest
from unittest.mock import patch
import zipfile

from qecgraph.source.package import Limits, PackageError, unpack

TEX = b'\\documentclass{article}\r\n\\begin{document}Hello\\end{document}\r\n'


def tar_bytes(files, *, mtime=0, format=tarfile.PAX_FORMAT):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=format) as output:
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
    def test_input_size_and_archive_depth_boundaries(self):
        exact = Limits(input_bytes=len(TEX))
        self.assertEqual(unpack(TEX, exact).files, {'main.tex': TEX})
        with self.assertRaises(PackageError) as oversized:
            unpack(TEX + b' ', exact)
        self.assertEqual(oversized.exception.status, 'limit_exceeded')

        allowed = tar_bytes({'section/main.tex': TEX})
        limits = Limits(depth=2)
        self.assertEqual(unpack(allowed, limits).files, {'section/main.tex': TEX})
        with self.assertRaises(PackageError) as too_deep:
            unpack(tar_bytes({'section/nested/main.tex': TEX}), limits)
        self.assertEqual(too_deep.exception.status, 'limit_exceeded')

    def test_unsupported_zip_members_are_rejected_before_opening(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('main.tex', TEX)
        raw = buffer.getvalue()
        central = raw.index(b'PK\x01\x02')
        for field, local_offset, central_offset, value, expected in (
                ('encryption', 6, 8, 1, 'unsafe_archive'),
                ('compression', 8, 10, 99, 'unsupported_format')):
            with self.subTest(field=field):
                invalid = bytearray(raw)
                struct.pack_into('<H', invalid, local_offset, value)
                struct.pack_into('<H', invalid, central + central_offset, value)
                with patch.object(zipfile.ZipFile, 'open') as open_member, self.assertRaises(PackageError) as error:
                    unpack(bytes(invalid))
                self.assertEqual(error.exception.status, expected)
                open_member.assert_not_called()

    def test_non_utf8_standalone_tex_has_an_encoding_error(self):
        with self.assertRaisesRegex(PackageError, 'not UTF-8') as invalid:
            unpack(TEX.replace(b'Hello', b'\xff'))
        self.assertEqual(invalid.exception.status, 'unsupported_encoding')

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

    def test_tar_extensions_preserve_long_names_and_reject_oversized_metadata(self):
        name = 'n' * 128 + '.tex'
        for format in (tarfile.PAX_FORMAT, tarfile.GNU_FORMAT):
            raw = tar_bytes({name: TEX}, format=format)
            self.assertEqual(unpack(raw, Limits(member_bytes=len(TEX), members=1)).files, {name: TEX})

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as archive:
            entry = tarfile.TarInfo('main.tex')
            entry.size = len(TEX)
            entry.pax_headers = {'comment': 'x' * (256 << 10)}
            archive.addfile(entry, io.BytesIO(TEX))
        for raw in (buffer.getvalue(), gzip.compress(buffer.getvalue())):
            with self.assertRaises(PackageError) as error:
                unpack(raw)
            self.assertEqual(error.exception.status, 'limit_exceeded')

    def test_tar_extension_chain_is_bounded_before_recursive_parsing(self):
        header = tarfile.TarInfo('pax-header')
        header.type = tarfile.XGLTYPE
        raw = header.tobuf() * 33 + tar_bytes({'main.tex': TEX})
        with self.assertRaises(PackageError) as error:
            unpack(raw)
        self.assertEqual(error.exception.status, 'limit_exceeded')

    def test_zip_member_limit_precedes_directory_allocation_even_with_forged_counts(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('first.tex', TEX)
            archive.writestr('second.tex', TEX)
        raw = bytearray(buffer.getvalue())
        struct.pack_into('<HH', raw, raw.rindex(b'PK\x05\x06') + 8, 1, 1)
        for payload in (bytes(raw), gzip.compress(raw)):
            with patch('qecgraph.source.package.zipfile.ZipFile') as load:
                with self.assertRaises(PackageError) as error:
                    unpack(payload, Limits(members=1))
                self.assertEqual(error.exception.status, 'limit_exceeded')
                load.assert_not_called()

    def test_zip64_directory_allows_large_variable_fields_under_member_limit(self):
        buffer = io.BytesIO()
        entry = zipfile.ZipInfo('main.tex')
        entry.comment = b'member metadata' * 20
        with patch.object(zipfile, 'ZIP64_LIMIT', 1):
            with zipfile.ZipFile(buffer, 'w') as archive:
                archive.comment = b'Archive comment'
                archive.writestr(entry, TEX)
        raw = buffer.getvalue()
        self.assertIn(b'PK\x06\x06', raw)
        self.assertEqual(unpack(raw, Limits(members=1)).files, {'main.tex': TEX})
        # Invalid ZIP64 disk/record layouts are rejected by the bounded reader.
        for offset, value in ((raw.index(b'PK\x06\x07') + 4, 1),
                              (raw.index(b'PK\x06\x06') + 4, 45)):
            damaged = bytearray(raw)
            struct.pack_into('<L', damaged, offset, value)
            with self.assertRaises(PackageError) as error:
                unpack(bytes(damaged), Limits(members=1))
            self.assertEqual(error.exception.status, 'damaged_archive')

    def test_package_detection_rejects_a_damaged_trailer_and_non_tex_prefixes(self):
        tar = tar_bytes({'main.tex': TEX})
        for raw, expected in ((tar[:-1] + b'x', 'damaged_archive'),
                              (b' \t<!DoCtYpE HTML>\n' + TEX, 'unsupported_format'),
                              (b'\r\n%PdF-1.7\n' + TEX, 'unsupported_format')):
            with self.subTest(expected=expected), self.assertRaises(PackageError) as error:
                unpack(raw)
            self.assertEqual(error.exception.status, expected)

    def test_oversized_standalone_tex_is_rejected_before_decoding(self):
        for package in (TEX, gzip.compress(TEX)):
            with patch('qecgraph.source.package._tex_body') as decode:
                with self.assertRaises(PackageError) as error:
                    unpack(package, Limits(member_bytes=len(TEX) - 1))
                self.assertEqual(error.exception.status, 'limit_exceeded')
                decode.assert_not_called()

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
