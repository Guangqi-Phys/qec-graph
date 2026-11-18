"""Exercise the execution boundary independently of a TeX installation."""

import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from qecgraph.preparation import sandbox


class CompilerSandboxTests(unittest.TestCase):
    def test_sandbox_denies_external_files_network_and_inherited_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            work = root / 'work'
            work.mkdir()
            alias = root / 'alias'
            alias.symlink_to(work, target_is_directory=True)
            if sys.platform != 'darwin' and not shutil.which('bwrap'):
                self._sandbox_unavailable('bubblewrap is not installed')
            probe = sandbox.run(alias, alias, ['/bin/sh', '-c', 'touch inside'])
            if probe['exit'] and any(reason in probe['log'].lower()
                                     for reason in (b'sandbox_apply: operation not permitted',
                                                    b'creating new namespace',
                                                    b'no permissions to create')):
                self._sandbox_unavailable(probe['log'].decode(errors='replace').strip())
            self.assertEqual(probe['exit'], 0, probe['log'])
            self.assertTrue((work / 'inside').is_file())
            secret = root / 'sentinel'
            secret.write_text('test sentinel')
            forbidden = root / 'forbidden'
            command = ['/bin/sh', '-c',
                       'if cat "$1" || touch "$2"; then exit 1; fi; test -z "$OPENROUTER_API_KEY"',
                       'probe', str(secret), str(forbidden)]
            with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'fixture-only'}):
                result = sandbox.run(alias, alias, command)
            self.assertEqual(result['exit'], 0, result['log'])
            self.assertNotIn(b'test sentinel', result['log'])
            self.assertFalse(forbidden.exists())

            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen()
                command = ['/usr/bin/perl', '-MSocket', '-e',
                           'my $ok = socket(S, AF_INET, SOCK_STREAM, 0) && '
                           'connect(S, sockaddr_in($ARGV[0], inet_aton("127.0.0.1"))); '
                           'print $ok ? "connected" : "blocked";',
                           str(listener.getsockname()[1])]
                network = sandbox.run(alias, alias, command, timeout=5)
                self.assertEqual(network['exit'], 0, network['log'])
                self.assertEqual(network['log'], b'blocked')

    def _sandbox_unavailable(self, message):
        if os.environ.get('QECGRAPH_TEST_TEX') == '1':
            self.fail(message)
        self.skipTest(message)
