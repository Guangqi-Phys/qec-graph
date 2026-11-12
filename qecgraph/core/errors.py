"""Transport-independent errors; messages must be safe to return to callers."""


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
