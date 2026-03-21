"""
Unit tests for shared/utils/date_utils.py.

Covers:
  - parse_period() — Q1-Q4, H1-H2, full year, case-insensitive, invalid formats
  - format_duration() — seconds, minutes, hours, edge cases
  - days_since() — past dates, today, invalid format raises
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.utils.date_utils import days_since, format_duration, parse_period


# ===========================================================================
# parse_period
# ===========================================================================

class TestParsePeriod:

    def test_q1_2025(self):
        start, end = parse_period("Q1-2025")
        assert start == "2025-01-01"
        assert end == "2025-03-31"

    def test_q2_2025(self):
        start, end = parse_period("Q2-2025")
        assert start == "2025-04-01"
        assert end == "2025-06-30"

    def test_q3_2025(self):
        start, end = parse_period("Q3-2025")
        assert start == "2025-07-01"
        assert end == "2025-09-30"

    def test_q4_2026(self):
        start, end = parse_period("Q4-2026")
        assert start == "2026-10-01"
        assert end == "2026-12-31"

    def test_h1_2025(self):
        start, end = parse_period("H1-2025")
        assert start == "2025-01-01"
        assert end == "2025-06-30"

    def test_h2_2025(self):
        start, end = parse_period("H2-2025")
        assert start == "2025-07-01"
        assert end == "2025-12-31"

    def test_full_year_2025(self):
        start, end = parse_period("2025")
        assert start == "2025-01-01"
        assert end == "2025-12-31"

    def test_full_year_2026(self):
        start, end = parse_period("2026")
        assert start == "2026-01-01"
        assert end == "2026-12-31"

    def test_case_insensitive_lowercase_q(self):
        start, end = parse_period("q1-2025")
        assert start == "2025-01-01"
        assert end == "2025-03-31"

    def test_case_insensitive_lowercase_h(self):
        start, end = parse_period("h2-2025")
        assert start == "2025-07-01"
        assert end == "2025-12-31"

    def test_returns_tuple_of_two_strings(self):
        result = parse_period("Q2-2025")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(s, str) for s in result)

    def test_invalid_format_raises_value_error(self):
        with pytest.raises(ValueError, match="Unrecognised period format"):
            parse_period("INVALID")

    def test_invalid_quarter_number_raises(self):
        """Q5 is not a valid quarter — pattern does not match [1-4]."""
        with pytest.raises(ValueError):
            parse_period("Q5-2025")

    def test_invalid_half_number_raises(self):
        """H3 is not a valid half-year."""
        with pytest.raises(ValueError):
            parse_period("H3-2025")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_period("")

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace should be tolerated."""
        start, end = parse_period("  Q1-2025  ")
        assert start == "2025-01-01"
        assert end == "2025-03-31"


# ===========================================================================
# format_duration
# ===========================================================================

class TestFormatDuration:

    def test_zero_seconds(self):
        assert format_duration(0) == "0s"

    def test_seconds_only(self):
        assert format_duration(45) == "45s"

    def test_fifty_nine_seconds(self):
        assert format_duration(59) == "59s"

    def test_exact_one_minute(self):
        assert format_duration(60) == "1m"

    def test_minutes_and_seconds(self):
        assert format_duration(154) == "2m 34s"

    def test_exact_two_minutes(self):
        assert format_duration(120) == "2m"

    def test_exact_one_hour(self):
        assert format_duration(3600) == "1h"

    def test_hours_and_minutes(self):
        assert format_duration(4500) == "1h 15m"

    def test_exactly_one_hour_no_minutes_suffix(self):
        """3600s → '1h', not '1h 0m'."""
        result = format_duration(3600)
        assert result == "1h"

    def test_large_duration(self):
        result = format_duration(7261)  # 2h 1m 1s → displayed as 2h 1m
        assert result == "2h 1m"

    def test_float_seconds_truncated(self):
        """Float input is truncated to int before processing."""
        assert format_duration(45.9) == "45s"


# ===========================================================================
# days_since
# ===========================================================================

class TestDaysSince:

    def test_today_returns_zero(self):
        today_str = datetime.utcnow().date().isoformat()
        assert days_since(today_str) == 0

    def test_yesterday_returns_one(self):
        yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
        assert days_since(yesterday) == 1

    def test_one_week_ago(self):
        week_ago = (datetime.utcnow().date() - timedelta(days=7)).isoformat()
        assert days_since(week_ago) == 7

    def test_past_date_returns_positive(self):
        result = days_since("2020-01-01")
        assert result > 0

    def test_future_date_returns_zero(self):
        """Future dates should return 0 (not negative)."""
        future = (datetime.utcnow().date() + timedelta(days=10)).isoformat()
        assert days_since(future) == 0

    def test_invalid_date_string_raises(self):
        with pytest.raises(ValueError):
            days_since("not-a-date")

    def test_invalid_format_wrong_separators(self):
        with pytest.raises(ValueError):
            days_since("2025/01/01")

    def test_returns_integer(self):
        result = days_since("2020-06-15")
        assert isinstance(result, int)
