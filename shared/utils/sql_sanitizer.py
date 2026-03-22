"""
SQL sanitizer — prevents injection via base_filter and other user-influenced SQL fragments.

VAL-49: Sanitize base_filter and all interpolated SQL.

This module is in shared/utils/ because it is used by both core/ and api/ layers.
"""

import re
from typing import Optional  # noqa: F401

import structlog

logger = structlog.get_logger()

# ── Dangerous SQL patterns ────────────────────────────────────────────────────
# These patterns indicate SQL injection attempts when found in a WHERE-clause fragment.
_INJECTION_PATTERNS = [
    re.compile(r'\b(DROP|ALTER|TRUNCATE)\s+(TABLE|DATABASE|INDEX|SCHEMA)\b', re.IGNORECASE),
    re.compile(r'\b(DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET)\b', re.IGNORECASE),
    re.compile(r'\bUNION\s+(ALL\s+)?SELECT\b', re.IGNORECASE),
    re.compile(r'\bEXEC(UTE)?\s*\(', re.IGNORECASE),
    re.compile(r'\bxp_\w+', re.IGNORECASE),              # SQL Server extended procs
    re.compile(r'\bINTO\s+(OUT|DUMP)FILE\b', re.IGNORECASE),
    re.compile(r'\bLOAD_FILE\s*\(', re.IGNORECASE),
    re.compile(r'\bCREATE\s+(TABLE|DATABASE|INDEX|FUNCTION|PROCEDURE)\b', re.IGNORECASE),
    re.compile(r'\bGRANT\s+', re.IGNORECASE),
    re.compile(r'\bREVOKE\s+', re.IGNORECASE),
]

# Inline comment / statement terminator patterns
_COMMENT_OR_TERMINATOR = re.compile(r'(--|/\*|;\s*$|;\s*\w)')

# Allowed WHERE-clause operators and keywords
_ALLOWED_WHERE_RE = re.compile(
    r"^[\w\s\.\"\'\=\<\>\!\(\)\,\:]+$"  # basic chars
    r"|"
    r"\b(AND|OR|NOT|IN|BETWEEN|LIKE|ILIKE|IS|NULL|TRUE|FALSE|CAST|AS)\b",
    re.IGNORECASE,
)

# Valid WHERE clause: should contain at least one comparison operator
_HAS_COMPARISON = re.compile(r'[=<>]|(?:\bIN\b)|(?:\bLIKE\b)|(?:\bILIKE\b)|(?:\bIS\b)|(?:\bBETWEEN\b)', re.IGNORECASE)


def sanitize_base_filter(raw_filter: str, context: str = "") -> str:
    """
    Sanitize a base_filter string from entity_map before SQL interpolation.

    - Strips leading/trailing whitespace
    - Rejects dangerous SQL patterns (DROP, DELETE, UNION SELECT, etc.)
    - Rejects inline comments (--) and statement terminators (;)
    - Validates it looks like a WHERE clause fragment

    Returns the sanitized filter string.
    Raises ValueError if the filter is unsafe.

    Parameters
    ----------
    raw_filter : str
        The raw base_filter value from entity_map.
    context : str
        Optional context string for logging (e.g., entity name).
    """
    if not raw_filter or not raw_filter.strip():
        return ""

    cleaned = raw_filter.strip()

    # ── Check 1: Reject dangerous patterns ────────────────────────────────
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            logger.warning(
                "sql_sanitizer.injection_blocked",
                filter=cleaned[:200],
                context=context,
                pattern=pattern.pattern,
            )
            raise ValueError(
                f"base_filter contains dangerous SQL pattern: {cleaned[:80]}"
            )

    # ── Check 2: Reject comments and statement terminators ────────────────
    if _COMMENT_OR_TERMINATOR.search(cleaned):
        logger.warning(
            "sql_sanitizer.comment_or_terminator_blocked",
            filter=cleaned[:200],
            context=context,
        )
        raise ValueError(
            f"base_filter contains comment or statement terminator: {cleaned[:80]}"
        )

    # ── Check 3: Must look like a WHERE clause ────────────────────────────
    if not _HAS_COMPARISON.search(cleaned):
        logger.warning(
            "sql_sanitizer.invalid_where_clause",
            filter=cleaned[:200],
            context=context,
        )
        raise ValueError(
            f"base_filter does not look like a valid WHERE clause: {cleaned[:80]}"
        )

    return cleaned


def sanitize_identifier(name: str) -> str:
    """
    Validate and return a safe SQL identifier (table or column name).

    Raises ValueError if the name contains unsafe characters.
    """
    if not name or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name) or len(name) > 128:
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def sanitize_period_value(value: str) -> str:
    """
    Validate a period date value (YYYY-MM-DD or YYYY-MM format).

    Raises ValueError if the format is invalid.
    """
    if not re.match(r'^\d{4}(-\d{2}(-\d{2})?)?$', value):
        raise ValueError(f"Invalid period value: {value!r}")
    return value
