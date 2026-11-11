"""Errors raised by the optional AI layer."""
from __future__ import annotations


class LLMError(RuntimeError):
    """Base error for model configuration, transport or response failures."""

    # Kept out of the printable error; callers may use this untrusted, redacted
    # response for a bounded correction request after validation rejects it.
    rejected_response: dict | None = None


class ProviderError(LLMError):
    """A provider request failed.

    Messages are safe to print: they never contain authorization headers or
    private paths. ``retryable`` is set only for transient transport/status
    failures.
    """

    def __init__(self, message, *, status=None, retryable=False, code=None):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.code = code
