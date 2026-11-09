"""Stable CLI errors and their process exit statuses."""

from __future__ import annotations

import json
import sqlite3
import tomllib
from typing import Any

from ..transactions import ManagedDataError, WriterBusy
from ..workspace import WorkspaceConfigError


class QecError(ValueError):
    code = 'QEC_ERROR'
    exit_code = 1
    hint: str | None = None

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}

    def envelope(self, command: str | None) -> dict[str, Any]:
        return {'envelope_version': 1, 'ok': False,
                'error': {'code': self.code, 'message': str(self), 'hint': self.hint,
                          'details': self.details, 'command': command, 'scope': None}}


class UsageError(QecError):
    code = 'USAGE'
    exit_code = 64
    hint = 'Run qec-graph --help for usage.'
    command: str | None = None


class InvalidInput(QecError):
    code = 'INVALID_INPUT'


class NotFound(QecError):
    code = 'NOT_FOUND'
    exit_code = 4
    hint = 'Check the path and the selected workspace, store, or corpus.'


class Conflict(QecError):
    code = 'CONFLICT'
    exit_code = 5
    hint = 'Wait for the other writer to finish, then retry the command.'


class InvalidConfig(QecError):
    code = 'INVALID_CONFIG'
    hint = 'Run qec-graph doctor to inspect the workspace configuration.'


class StorageError(QecError):
    code = 'STORAGE_ERROR'
    hint = 'Run qec-graph doctor to inspect the workspace or validate --store for a store.'


class Interrupted(QecError):
    code = 'INTERRUPTED'
    exit_code = 130


class InternalError(QecError):
    code = 'INTERNAL_ERROR'
    hint = 'Rerun with --debug to see the traceback.'


def classify(exc: Exception) -> QecError:
    if isinstance(exc, QecError):
        return exc
    if isinstance(exc, WriterBusy):
        return Conflict(str(exc), details={'path': str(exc.root)})
    if isinstance(exc, WorkspaceConfigError):
        return InvalidConfig(str(exc), details={'path': str(exc.path)})
    if isinstance(exc, ManagedDataError):
        return StorageError(str(exc), details={'path': str(exc.path)})
    if isinstance(exc, FileNotFoundError):
        path = str(exc.filename) if exc.filename is not None else None
        return NotFound(f'No file found at {path}' if path else 'A required file is missing',
                        details={'path': path} if path else None)
    if isinstance(exc, json.JSONDecodeError):
        return InvalidInput(f'Invalid JSON at line {exc.lineno}, column {exc.colno}',
                            details={'line': exc.lineno, 'column': exc.colno})
    if isinstance(exc, UnicodeError):
        return InvalidInput('Input text is not valid UTF-8')
    if isinstance(exc, tomllib.TOMLDecodeError):
        location = {key: getattr(exc, key) for key in ('lineno', 'colno') if hasattr(exc, key)}
        return InvalidConfig('The workspace configuration is not valid TOML', details=location)
    if isinstance(exc, OSError):
        path = str(exc.filename) if exc.filename is not None else None
        details = {key: value for key, value in (('path', path), ('errno', exc.errno)) if value is not None}
        if isinstance(exc, PermissionError):
            return StorageError(f'Access denied for {path}' if path else 'Access denied', details=details)
        return StorageError(f'File operation failed for {path}' if path else 'File operation failed', details=details)
    if isinstance(exc, sqlite3.Error):
        return StorageError('Could not read or update the SQLite projection')
    if isinstance(exc, ValueError):
        return InvalidInput(str(exc))
    return InternalError('Unexpected internal failure')
