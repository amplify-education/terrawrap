"""Utilities for loading HCL2 files with normalized output.

python-hcl2 v8 preserves quotes in serialized strings and adds __is_block__ markers.
These wrappers strip that extra formatting so the rest of the codebase can work with
plain Python dicts and unquoted string values.
"""
from typing import TextIO

import hcl2


def _strip_quotes(value: str) -> str:
    """Strip surrounding double-quotes from a string if present."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _normalize(obj):
    """Recursively normalize hcl2 v8 output to match v3-style dicts."""
    if isinstance(obj, dict):
        return {
            _strip_quotes(str(k)): _normalize(v)
            for k, v in obj.items()
            if k != "__is_block__"
        }
    if isinstance(obj, list):
        return [_normalize(item) for item in obj]
    if isinstance(obj, str):
        return _strip_quotes(obj)
    return obj


def load(file: TextIO) -> dict:
    """Load HCL2 from a file object and return a normalized Python dict."""
    return _normalize(hcl2.load(file))


def loads(text: str) -> dict:
    """Load HCL2 from a string and return a normalized Python dict."""
    return _normalize(hcl2.loads(text))
