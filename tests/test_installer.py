import hashlib
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent


INSTALLER = Path(__file__).resolve().parents[1] / 'install.sh'
RELEASES = 'https://github.com/Guangqi-Phys/qec-graph/releases'


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        system, machine = platform.system().lower(), platform.machine().lower()
        arch = 'arm64' if machine in ('aarch64', 'arm64') else machine
        if system not in ('darwin', 'linux') or arch not in ('arm64', 'x86_64'):
            self.skipTest('The installer targets macOS and Linux on arm64 or x86_64')
        self.asset = f'qec-graph-{system}-{arch}'
        self.releases = root / 'releases'
        self.releases.mkdir()
        self.install_dir = root / 'installed binary'
        self.downloads = root / 'downloads'
        self.downloads.mkdir()
        mocks = root / 'mocks'
        mocks.mkdir()
        curl = mocks / 'curl'
        curl.write_text(f'#!{sys.executable}\n' + dedent('''
            import os
            import shutil
            import sys
            from pathlib import Path

            arguments = sys.argv[1:]
            base = os.environ['QEC_INSTALL_TEST_URL']
            fixtures = Path(os.environ['QEC_INSTALL_TEST_RELEASES'])
            output = Path(arguments[arguments.index('--output') + 1])
            url = arguments[-1]
            if url == base + '/latest':
                stable = fixtures / 'latest'
                print('200 ' + base + '/tag/' + stable.read_text() if stable.exists() else '404 ' + url, end='')
            elif url == base + '.atom':
                shutil.copyfile(fixtures / 'releases.atom', output)
            elif url.startswith(base + '/download/'):
                shutil.copyfile(fixtures / url.removeprefix(base + '/download/'), output)
            else:
                raise SystemExit('Unexpected fixture URL')
        '''), encoding='utf-8')
        curl.chmod(0o755)
        self.env = {**os.environ, 'PATH': f'{mocks}{os.pathsep}{os.environ["PATH"]}',
                    'QECGRAPH_BIN_DIR': str(self.install_dir), 'TMPDIR': str(self.downloads),
                    'QEC_INSTALL_TEST_RELEASES': str(self.releases), 'QEC_INSTALL_TEST_URL': RELEASES}

    def make_release(self, version, *, bad_checksum=False, executable_version=None):
        release = self.releases / version
        release.mkdir()
        reported = executable_version or version.removeprefix('v')
        executable = f"#!/bin/sh\nprintf '%s\\n' 'qec-graph {reported}'\n".encode()
        (release / self.asset).write_bytes(executable)
        digest = '0' * 64 if bad_checksum else hashlib.sha256(executable).hexdigest()
        (release / f'{self.asset}.sha256').write_text(f'{digest}  {self.asset}\n', encoding='ascii')

    def install(self):
        result = subprocess.run(['sh', str(INSTALLER)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(list(self.downloads.iterdir()), [])
        return result

    def version(self):
        installed = self.install_dir / 'qec-graph'
        return subprocess.check_output([str(installed), '--version'], text=True, timeout=5).strip()

    def test_latest_install_update_and_failed_checksum_preserve_the_binary(self):
        latest = self.releases / 'latest'
        for version in ('v0.9.0', 'v0.10.0'):
            self.make_release(version)
            latest.write_text(version, encoding='ascii')
            installed = self.install()
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(self.version(), f'qec-graph {version.removeprefix("v")}')

        self.make_release('v0.11.0', bad_checksum=True)
        latest.write_text('v0.11.0', encoding='ascii')
        failed = self.install()
        self.assertEqual(failed.returncode, 1)
        self.assertIn('failed SHA-256 verification', failed.stderr)
        self.assertEqual(self.version(), 'qec-graph 0.10.0')
        self.assertEqual([p.name for p in self.install_dir.iterdir()], ['qec-graph'])

    def test_wrong_executable_version_preserves_the_previous_installation(self):
        latest = self.releases / 'latest'
        self.make_release('v0.9.0')
        latest.write_text('v0.9.0', encoding='ascii')
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.make_release('v0.10.0', executable_version='0.8.0')
        latest.write_text('v0.10.0', encoding='ascii')
        failed = self.install()
        self.assertEqual(failed.returncode, 1)
        self.assertIn('executable version does not match release v0.10.0', failed.stderr)
        self.assertEqual(self.version(), 'qec-graph 0.9.0')
        self.assertEqual([p.name for p in self.install_dir.iterdir()], ['qec-graph'])

    def test_prerelease_feed_is_used_when_there_is_no_stable_release(self):
        version = 'v0.9.0rc1'
        self.make_release(version)
        (self.releases / 'releases.atom').write_text(
            f'<feed>\n<entry>\n<link href="{RELEASES}/tag/{version}" rel="alternate"/>\n</entry>\n</feed>\n',
            encoding='utf-8')
        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(self.version(), 'qec-graph 0.9.0rc1')
