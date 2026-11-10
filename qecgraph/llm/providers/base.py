"""Small transport-neutral provider contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str, str],
                body: bytes | None, timeout: float) -> HttpResult:
        ...


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    finish_reason: str | None = None


class Provider(Protocol):
    name: str
    kind: str

    def complete(self, messages: Sequence[Message], *, model: str,
                 response_schema: Mapping[str, Any] | None = None,
                 temperature: float = 0.0, max_output_tokens: int | None = None,
                 timeout: float = 180.0) -> Completion:
        ...
