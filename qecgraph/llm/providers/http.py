"""Standard-library HTTPS transport used when no test transport is injected."""
from __future__ import annotations

import urllib.error
import urllib.request

from .base import HttpResult


class UrllibTransport:
    def request(self, method, url, *, headers, body, timeout):
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResult(status=response.status, headers=dict(response.headers),
                                  body=response.read())
        except urllib.error.HTTPError as exc:
            return HttpResult(status=exc.code, headers=dict(exc.headers or {}), body=exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ConnectionError(str(exc)) from exc
