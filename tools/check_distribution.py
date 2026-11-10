"""Check that built Python distributions match the source used to build them."""

import argparse
import runpy
import tarfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile


def _check_metadata(raw, expected_version, expected_readme):
    metadata = BytesParser().parsebytes(raw)
    if metadata['Version'] != expected_version:
        raise ValueError('Distribution version differs from the package version')
    if metadata['License-Expression'] != 'MIT' or metadata.get_all('License-File') != ['LICENSE']:
        raise ValueError('Distribution metadata does not name the project license')
    payload = metadata.get_payload(decode=True)
    if payload is None:
        payload = metadata.get_payload().encode('utf-8')
    if payload.decode('utf-8').rstrip() != expected_readme.rstrip():
        raise ValueError('Distribution metadata README differs from the source README')


def verify(source, wheel, sdist):
    version = runpy.run_path(str(source / 'qecgraph' / '__init__.py'))['__version__']
    readme = (source / 'README.md').read_text(encoding='utf-8')
    license_bytes = (source / 'LICENSE').read_bytes()
    schema_root = 'qecgraph/validators/schemas/'
    schemas = {path.relative_to(source).as_posix(): path.read_bytes()
               for path in (source / schema_root).glob('*.schema.json')}
    seed = 'qecgraph/catalog/software_catalog.seed.json'
    seed_bytes = (source / seed).read_bytes()
    with ZipFile(wheel) as archive:
        metadata, = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        _check_metadata(archive.read(metadata), version, readme)
        license_path = metadata.removesuffix('METADATA') + 'licenses/LICENSE'
        if archive.read(license_path) != license_bytes:
            raise ValueError('Wheel license differs from the source license')
        inventory = [name for name in archive.namelist() if name.startswith(schema_root) and name.endswith('.schema.json')]
        if sorted(inventory) != sorted(schemas):
            raise ValueError('Wheel schema inventory differs from the checkout')
        for name, expected in schemas.items():
            if archive.read(name) != expected:
                raise ValueError(f'Wheel schema differs from the checkout: {name}')
        if archive.namelist().count(seed) != 1 or archive.read(seed) != seed_bytes:
            raise ValueError('Wheel software catalog seed differs from the checkout')
    with tarfile.open(sdist, 'r:gz') as archive:
        prefix = sdist.name.removesuffix('.tar.gz')
        inventory = [name.removeprefix(prefix + '/') for name in archive.getnames()
                     if name.startswith(f'{prefix}/{schema_root}') and name.endswith('.schema.json')]
        if sorted(inventory) != sorted(schemas):
            raise ValueError('Source distribution schema inventory differs from the checkout')
        expected_files = {'README.md': readme.encode('utf-8'), 'LICENSE': license_bytes,
                          'install.sh': (source / 'install.sh').read_bytes(), seed: seed_bytes, **schemas}
        for name, expected in expected_files.items():
            matches = [item for item in archive.getmembers() if item.name == f'{prefix}/{name}']
            if len(matches) != 1 or not matches[0].isfile():
                raise ValueError(f'Source distribution must contain one regular file at {name}')
            with archive.extractfile(matches[0]) as stream:
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
    print(f'Verified {version}, README, license, schemas, and catalog seed in {wheel.name} and {sdist.name}')


if __name__ == '__main__':
    main()
