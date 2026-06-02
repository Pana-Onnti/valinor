"""SQL identifier safety check — shared validator for table/column names."""

from __future__ import annotations

import re

_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def is_safe_identifier(name: str) -> bool:
    """Validate that a string is a safe SQL identifier (table/column name)."""
    return bool(name and _SAFE_IDENTIFIER_RE.match(name) and len(name) <= 128)
