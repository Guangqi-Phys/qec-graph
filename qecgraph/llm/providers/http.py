"""HTTP transport and JSON response handling shared by API providers."""
from __future__ import annotations

import http.client
import json
from typing import Any, Mapping
import urllib.error
import urllib.request

from ..errors import ProviderError
from .base import HttpResult, Transport


def post_json(transport: Transport, endpoint: str, *, name: str, headers: Mapping[str, str],
              payload: Mapping[str, Any], timeout: float) -> tuple[HttpResult, Any]:
    try:
        result = transport.request('POST', endpoint, headers=headers,
                                   body=json.dumps(payload).encode('utf-8'), timeout=timeout)
    except ConnectionError:
        raise ProviderError(f'{name}: transport failed', retryable=True) from None
    if not 200 <= result.status < 300:
        retryable = result.status in {408, 409, 429} or result.status >= 500
        raise ProviderError(f'{name}: HTTP {result.status}', status=result.status, retryable=retryable)
    try:
        return result, json.loads(result.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError(f'{name}: provider returned invalid JSON') from None


class UrllibTransport:
    def request(self, method, url, *, headers, body, timeout):
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return HttpResult(status=response.status, headers=dict(response.headers),
                                      body=response.read())
            except urllib.error.HTTPError as exc:
                with exc:
                    return HttpResult(status=exc.code, headers=dict(exc.headers or {}), body=exc.read())
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as exc:
            # Chunked responses can end mid-read after successful headers.
            # Expose a retryable transport failure, never partial response text.
            raise ConnectionError('HTTP request or response read failed') from exc
