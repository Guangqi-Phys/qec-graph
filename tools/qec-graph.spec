from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata


root = Path(SPECPATH).resolve().parent
package = root / 'qecgraph'
# Runtime schemas, catalogs and the original source used for snapshot fingerprints.
data = [
    (str(path), str(path.parent.relative_to(root)))
    for path in sorted(package.rglob('*'))
    if path.is_file() and path.suffix in {'.json', '.py'}
]
for dependency in ('pylatexenc', 'jsonschema'):
    data.extend(copy_metadata(dependency))

analysis = Analysis(
    [str(package / '__main__.py')],
    pathex=[str(root)],
    datas=data,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name='qec-graph',
    console=True,
    upx=False,
)
