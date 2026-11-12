"""Transport-independent errors; messages must be safe to return to callers."""
from hashlib import sha256
from pathlib import Path
import traceback


def failure_details(exc: BaseException) -> dict:
    """Retain code locations, never exception messages, source lines or locals."""
    frames = [{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
              for frame in traceback.extract_tb(exc.__traceback__)]
    return {'type': type(exc).__name__, 'frames': frames}


def log_internal_failure(logger, operation: str, exc: BaseException) -> str:
    details = failure_details(exc)
    reference = sha256(repr(details).encode()).hexdigest()[:16]
    logger.error('%s failed [%s]: %s', operation, reference, details)
    return reference


class ToolError(ValueError):
    """An actionable, expected query failure."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.details = code, details or {}


class PackageError(ValueError):
    """A rejected source package with a stable processing status."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
