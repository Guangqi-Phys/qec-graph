"""Standard-library HTTPS transport used when no test transport is injected."""
from __future__ import annotations

import http.client
import urllib.error
import urllib.request

from .base import HttpResult


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
