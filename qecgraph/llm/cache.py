"""Content-addressed cache for validated model responses."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading

from ..core.graph import strict_json_loads
from ..core.transactions import atomic_json


def cache_key(*, provider, model, messages, schema, temperature, max_output_tokens):
    payload = {'format': 'qecgraph.ai.cache.v2', 'provider': provider, 'model': model,
               'messages': list(messages), 'schema': schema, 'temperature': temperature,
               'max_output_tokens': max_output_tokens}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


class ResponseCache:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()

    def path(self, key):
        return self.root / (key + '.json')

    def get(self, key):
        with self.lock:
            try:
                raw = self.path(key).read_bytes()
                value = strict_json_loads(raw)
            except (OSError, ValueError):
                return None
            return value if isinstance(value, dict) else None

    def put(self, key, value):
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.root, 0o700)
            except OSError:
                pass
            atomic_json(self.path(key), value)
            try:
                os.chmod(self.path(key), 0o600)
            except OSError:
                pass
