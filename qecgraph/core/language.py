"""English prose policy for generated knowledge and reading notes.

This is a deterministic CJK guard, not a general language detector. Prompts
require English; mathematical notation and accented Latin names remain valid.
Original source bytes are never translated or passed through this guard.
"""
from __future__ import annotations

import re


_CJK = re.compile('[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]')


def require_english(value, path='output'):
    """Reject CJK text anywhere in a generated JSON value, including keys."""
    if isinstance(value, str):
        if _CJK.search(value):
            raise ValueError(f'{path} must use English; CJK text is not allowed')
    elif isinstance(value, dict):
        for index, (key, item) in enumerate(value.items()):
            require_english(key, f'{path}.key[{index}]')
            require_english(item, f'{path}.{key}')
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            require_english(item, f'{path}[{index}]')
