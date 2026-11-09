"""Build a command line for the active Python or standalone executable."""

import sys


def cli_command(*arguments):
    if getattr(sys, 'frozen', False):
        return [sys.executable, *arguments]
    return [sys.executable, '-m', 'qecgraph', *arguments]
