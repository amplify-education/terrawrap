"""Utilities for loading HCL2 files with normalized output.

python-hcl2 v8 preserves quotes in serialized strings and adds metadata markers.
The below wrappers use SerializationOptions to restore v7-style behavior so the rest
of the codebase can work with plain Python dicts and unquoted string values.
"""

from typing import Optional, TextIO

import hcl2
from hcl2 import SerializationOptions

_V7_COMPAT = SerializationOptions(
    strip_string_quotes=True,
    explicit_blocks=False,
    with_comments=False,
)


def hcl2_load(file: TextIO, serialization_options: Optional[SerializationOptions] = None) -> dict:
    """Load HCL2 from a file object and return a normalized Python dict."""
    serialization_options = serialization_options or _V7_COMPAT
    return hcl2.load(file, serialization_options=serialization_options)


def hcl2_loads(text: str, serialization_options: Optional[SerializationOptions] = None) -> dict:
    """Load HCL2 from a string and return a normalized Python dict."""
    serialization_options = serialization_options or _V7_COMPAT
    return hcl2.loads(text, serialization_options=serialization_options)
