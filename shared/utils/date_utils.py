"""
Date and time utilities for Valinor SaaS.

Provides helpers for parsing business period strings, formatting durations,
and computing elapsed days from ISO date strings.
"""

import re
from datetime import date, datetime


# ---------------------------------------------------------------------------
# parse_period
# ---------------------------------------------------------------------------

# Quarter end dates (month, last_day).
_QUARTER_BOUNDS: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    1: ((1, 1),  (3, 31)),
    2: ((4, 1),  (6, 30)),
    3: ((7, 1),  (9, 30)),
    4: ((10, 1), (12, 31)),
}

_HALF_BOUNDS: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    1: ((1, 1),  (6, 30)),
    2: ((7, 1),  (12, 31)),
}

# Pre-compiled patterns for recognised period formats.
_RE_QUARTER = re.compile(r"^Q([1-4])-(\d{4})$", re.IGNORECASE)
_RE_HALF = re.compile(r"^H([12])-(\d{4})$", re.IGNORECASE)
_RE_YEAR = re.compile(r"^(\d{4})$")
_RE_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def parse_period(period: str) -> tuple[str, str]:
    """
    Parse a business period string and return ISO start/end date strings.

    Supported formats
    -----------------
    * ``Q1-2025`` … ``Q4-2025``  — calendar quarter
    * ``H1-2025``, ``H2-2025``   — calendar half-year
    * ``2025``                   — full calendar year

    Parameters
    ----------
    period:
        Period descriptor string (case-insensitive for Q/H prefix).

    Returns
    -------
    tuple[str, str]
        ``(start_date, end_date)`` as ISO-8601 strings (``YYYY-MM-DD``).

    Raises
    ------
    ValueError
        If *period* does not match any recognised format.

    Examples
    --------
    >>> parse_period("Q1-2025")
    ('2025-01-01', '2025-03-31')
    >>> parse_period("H2-2025")
    ('2025-07-01', '2025-12-31')
    >>> parse_period("2025")
    ('2025-01-01', '2025-12-31')
    """
    period = period.strip()

    # --- Quarter ---
    m = _RE_QUARTER.match(period)
    if m:
        q = int(m.group(1))
        year = int(m.group(2))
        (sm, sd), (em, ed) = _QUARTER_BOUNDS[q]
        start = date(year, sm, sd).isoformat()
        end = date(year, em, ed).isoformat()
        return start, end

    # --- Half-year ---
    m = _RE_HALF.match(period)
    if m:
        h = int(m.group(1))
        year = int(m.group(2))
        (sm, sd), (em, ed) = _HALF_BOUNDS[h]
        start = date(year, sm, sd).isoformat()
        end = date(year, em, ed).isoformat()
        return start, end

    # --- Full year ---
    m = _RE_YEAR.match(period)
    if m:
        year = int(m.group(1))
        start = date(year, 1, 1).isoformat()
        end = date(year, 12, 31).isoformat()
        return start, end

    # --- Monthly: YYYY-MM ---
    m = _RE_MONTH.match(period)
    if m:
        import calendar
        year = int(m.group(1))
        month = int(m.group(2))
        last_day = calendar.monthrange(year, month)[1]
        start = date(year, month, 1).isoformat()
        end = date(year, month, last_day).isoformat()
        return start, end

    raise ValueError(
        f"Unrecognised period format: {period!r}. "
        "Expected formats: '2025-04', 'Q1-2025', 'H1-2025', '2025'."
    )


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------

def format_duration(seconds: float) -> str:
    """
    Format a duration given in seconds into a human-readable string.

    Parameters
    ----------
    seconds:
        Duration in seconds (non-negative float).

    Returns
    -------
    str
        Human-readable duration:
        * ``"45s"``    — for values under one minute
        * ``"2m 34s"`` — for values under one hour
        * ``"1h 15m"`` — for values of one hour or more

    Examples
    --------
    >>> format_duration(45)
    '45s'
    >>> format_duration(154)
    '2m 34s'
    >>> format_duration(4500)
    '1h 15m'
    """
    total_seconds = int(seconds)

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours}h"

    if minutes > 0:
        if secs > 0:
            return f"{minutes}m {secs}s"
        return f"{minutes}m"

    return f"{secs}s"


# ---------------------------------------------------------------------------
# days_since
# ---------------------------------------------------------------------------

def days_since(date_str: str) -> int:
    """
    Return the number of days elapsed since the given ISO date.

    Parameters
    ----------
    date_str:
        Date string in ``YYYY-MM-DD`` format.

    Returns
    -------
    int
        Number of whole days between *date_str* and today (UTC).
        Returns 0 if *date_str* is today or in the future.

    Raises
    ------
    ValueError
        If *date_str* cannot be parsed as an ISO date.
    """
    try:
        target = date.fromisoformat(date_str)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Cannot parse date string: {date_str!r}. Expected 'YYYY-MM-DD'."
        ) from exc

    today = datetime.utcnow().date()
    delta = today - target
    return max(0, delta.days)
