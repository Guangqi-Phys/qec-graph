"""Check that built Python distributions match the source used to build them."""

import argparse
import runpy
import tarfile
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile


def _check_metadata(raw, expected_version, expected_readme):
    metadata = BytesParser().parsebytes(raw)
    if metadata['Version'] != expected_version:
        raise ValueError('Distribution version differs from the package version')
    if metadata['License-Expression'] != 'MIT' or metadata.get_all('License-File') != ['LICENSE']:
        raise ValueError('Distribution metadata does not name the project license')
    if metadata.get_payload().rstrip() != expected_readme.rstrip():
        raise ValueError('Distribution metadata README differs from the source README')


def verify(source, wheel, sdist):
    version = runpy.run_path(str(source / 'qecgraph' / '__init__.py'))['__version__']
    readme = (source / 'README.md').read_text(encoding='utf-8')
    license_bytes = (source / 'LICENSE').read_bytes()
    with ZipFile(wheel) as archive:
        metadata, = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        _check_metadata(archive.read(metadata), version, readme)
        license_path = metadata.removesuffix('METADATA') + 'licenses/LICENSE'
        if archive.read(license_path) != license_bytes:
            raise ValueError('Wheel license differs from the source license')
    with tarfile.open(sdist, 'r:gz') as archive:
        prefix = sdist.name.removesuffix('.tar.gz')
        for name, expected in (('README.md', readme.encode('utf-8')), ('LICENSE', license_bytes)):
            with archive.extractfile(f'{prefix}/{name}') as stream:
                if stream.read() != expected:
                    raise ValueError(f'Source distribution {name} differs from the checkout')
        with archive.extractfile(f'{prefix}/PKG-INFO') as stream:
            _check_metadata(stream.read(), version, readme)
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dist', type=Path)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    wheel, = args.dist.glob('*.whl')
    sdist, = args.dist.glob('*.tar.gz')
    version = verify(args.source, wheel, sdist)
    print(f'Verified {version}, README, and license in {wheel.name} and {sdist.name}')


if __name__ == '__main__':
    main()
