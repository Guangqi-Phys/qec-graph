"""Best-effort redaction for provider errors and AI run metadata."""
from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r'\bsk-[A-Za-z0-9_-]{8,}\b'),
    re.compile(r'\bsk-ant-[A-Za-z0-9_-]{8,}\b'),
    re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}'),
)


def redact(text, secrets=()):
    value = str(text)
    for secret in secrets:
        if secret:
            value = value.replace(str(secret), '<redacted>')
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub('<redacted>', value)
    return value
