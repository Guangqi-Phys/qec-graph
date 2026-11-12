"""Shared paths for the test suite."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def enable_fixture_ai(root):
    """Explicit upload opt-in for fixtures whose providers are always mocked."""
    path = Path(root) / 'qecgraph.toml'
    text = path.read_text()
    head, ai = text.split('[ai]\n', 1)
    path.write_text(head + '[ai]\n' + ai.replace('allow_source_upload = false', 'allow_source_upload = true', 1))
