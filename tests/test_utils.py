"""
Tests for shared utility modules:
  - shared/utils/formatting.py
  - shared/utils/date_utils.py
"""

import sys
import pytest

sys.path.insert(0, ".")

from shared.utils.formatting import (
    format_currency,
    format_percentage,
    format_delta,
    truncate_text,
    slugify,
)
from shared.utils.date_utils import (
    parse_period,
    format_duration,
    days_since,
)


# ===========================================================================
# TestFormatCurrency
# ===========================================================================

class TestFormatCurrency:

    # 1 -----------------------------------------------------------------------
    def test_eur_standard(self):
        """EUR uses dot-thousands and comma-decimal separators (Spanish style)."""
        result = format_currency(840412.50, currency="EUR")
        assert result == "€840.412,50"

    # 2 -----------------------------------------------------------------------
    def test_usd_standard(self):
        """USD uses comma-thousands and dot-decimal separators."""
        result = format_currency(840412.50, currency="USD")
        assert result == "$840,412.50"

    # 3 -----------------------------------------------------------------------
    def test_eur_compact_millions(self):
        """Values >= 1M are rendered with 'M' suffix in compact mode."""
        result = format_currency(1_500_000, currency="EUR", compact=True)
        assert result == "€1.5M"

    # 4 -----------------------------------------------------------------------
    def test_eur_compact_thousands(self):
        """Values >= 1K but < 1M are rendered with 'K' suffix in compact mode."""
        result = format_currency(25_000, currency="EUR", compact=True)
        assert result == "€25K"

    # 5 -----------------------------------------------------------------------
    def test_compact_exact_million(self):
        """Exactly 1 million in compact mode should show '€1M' (no trailing .0)."""
        result = format_currency(1_000_000, currency="EUR", compact=True)
        assert result == "€1M"

    # 6 -----------------------------------------------------------------------
    def test_zero_value(self):
        """Zero should format cleanly without negative sign or garbage."""
        result = format_currency(0.0, currency="USD")
        assert result == "$0.00"

    # 7 -----------------------------------------------------------------------
    def test_negative_value(self):
        """Negative values must be prefixed with '-'."""
        result = format_currency(-1500.00, currency="EUR")
        assert result.startswith("-€")
        assert "1.500" in result

    # 8 -----------------------------------------------------------------------
    def test_gbp_symbol(self):
        """GBP must use the '£' symbol."""
        result = format_currency(1000.0, currency="GBP")
        assert result.startswith("£")

    # 9 -----------------------------------------------------------------------
    def test_brl_symbol(self):
        """BRL must use 'R$' prefix."""
        result = format_currency(500.0, currency="BRL")
        assert result.startswith("R$")

    # 10 ----------------------------------------------------------------------
    def test_unsupported_currency_raises(self):
        """Passing an unknown currency code must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported currency"):
            format_currency(100.0, currency="XXX")

    # 11 ----------------------------------------------------------------------
    def test_ars_uses_dot_thousands(self):
        """ARS follows Spanish-style separators (dot-thousands, comma-decimal)."""
        result = format_currency(10000.0, currency="ARS")
        assert "10.000" in result

    # 12 ----------------------------------------------------------------------
    def test_mxn_uses_comma_thousands(self):
        """MXN follows English-style separators (comma-thousands, dot-decimal)."""
        result = format_currency(10000.0, currency="MXN")
        assert "10,000" in result

    # 13 ----------------------------------------------------------------------
    def test_small_value_compact_falls_through(self):
        """Values < 1000 in compact mode should still format with full separators."""
        result = format_currency(500.0, currency="USD", compact=True)
        assert "$" in result
        assert "500" in result


# ===========================================================================
# TestFormatPercentage
# ===========================================================================

class TestFormatPercentage:

    # 14 ----------------------------------------------------------------------
    def test_positive_value(self):
        assert format_percentage(8.2) == "8.2%"

    # 15 ----------------------------------------------------------------------
    def test_negative_value(self):
        assert format_percentage(-3.5) == "-3.5%"

    # 16 ----------------------------------------------------------------------
    def test_zero_value(self):
        assert format_percentage(0.0) == "0.0%"

    # 17 ----------------------------------------------------------------------
    def test_custom_decimals(self):
        assert format_percentage(12.3456, decimals=2) == "12.35%"

    # 18 ----------------------------------------------------------------------
    def test_zero_decimals(self):
        assert format_percentage(75.0, decimals=0) == "75%"


# ===========================================================================
# TestFormatDelta
# ===========================================================================

class TestFormatDelta:

    # 19 ----------------------------------------------------------------------
    def test_positive_delta_has_plus(self):
        result = format_delta(12.3, as_percentage=True)
        assert result.startswith("+")
        assert result == "+12.3%"

    # 20 ----------------------------------------------------------------------
    def test_negative_delta_has_minus(self):
        result = format_delta(-5.1, as_percentage=True)
        assert result.startswith("-")
        assert result == "-5.1%"

    # 21 ----------------------------------------------------------------------
    def test_zero_delta_has_plus(self):
        """Zero delta should be considered non-negative and get a '+' prefix."""
        result = format_delta(0.0)
        assert result.startswith("+")

    # 22 ----------------------------------------------------------------------
    def test_delta_without_percentage(self):
        result = format_delta(3.7, as_percentage=False)
        assert result == "+3.7"
        assert "%" not in result


# ===========================================================================
# TestParsePeriod
# ===========================================================================

class TestParsePeriod:

    # 23 ----------------------------------------------------------------------
    def test_q1(self):
        start, end = parse_period("Q1-2025")
        assert start == "2025-01-01"
        assert end == "2025-03-31"

    # 24 ----------------------------------------------------------------------
    def test_q2(self):
        start, end = parse_period("Q2-2025")
        assert start == "2025-04-01"
        assert end == "2025-06-30"

    # 25 ----------------------------------------------------------------------
    def test_q3(self):
        start, end = parse_period("Q3-2025")
        assert start == "2025-07-01"
        assert end == "2025-09-30"

    # 26 ----------------------------------------------------------------------
    def test_q4(self):
        start, end = parse_period("Q4-2025")
        assert start == "2025-10-01"
        assert end == "2025-12-31"

    # 27 ----------------------------------------------------------------------
    def test_h1(self):
        start, end = parse_period("H1-2025")
        assert start == "2025-01-01"
        assert end == "2025-06-30"

    # 28 ----------------------------------------------------------------------
    def test_h2(self):
        start, end = parse_period("H2-2025")
        assert start == "2025-07-01"
        assert end == "2025-12-31"

    # 29 ----------------------------------------------------------------------
    def test_full_year(self):
        start, end = parse_period("2025")
        assert start == "2025-01-01"
        assert end == "2025-12-31"

    # 30 ----------------------------------------------------------------------
    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Unrecognised period format"):
            parse_period("INVALID")

    # 31 ----------------------------------------------------------------------
    def test_invalid_quarter_number_raises(self):
        """Q5 is not a valid quarter."""
        with pytest.raises(ValueError):
            parse_period("Q5-2025")

    # 32 ----------------------------------------------------------------------
    def test_case_insensitive(self):
        """Lowercase 'q1-2025' should be accepted."""
        start, end = parse_period("q1-2025")
        assert start == "2025-01-01"
        assert end == "2025-03-31"


# ===========================================================================
# TestFormatDuration
# ===========================================================================

class TestFormatDuration:

    # 33 ----------------------------------------------------------------------
    def test_seconds_only(self):
        assert format_duration(45) == "45s"

    # 34 ----------------------------------------------------------------------
    def test_minutes_and_seconds(self):
        assert format_duration(154) == "2m 34s"

    # 35 ----------------------------------------------------------------------
    def test_exact_minute(self):
        assert format_duration(60) == "1m"

    # 36 ----------------------------------------------------------------------
    def test_hours_and_minutes(self):
        assert format_duration(4500) == "1h 15m"

    # 37 ----------------------------------------------------------------------
    def test_exact_hour(self):
        assert format_duration(3600) == "1h"

    # 38 ----------------------------------------------------------------------
    def test_zero_seconds(self):
        assert format_duration(0) == "0s"


# ===========================================================================
# TestSlugify
# ===========================================================================

class TestSlugify:

    # 39 ----------------------------------------------------------------------
    def test_basic_slug(self):
        assert slugify("Acme Corp S.A.") == "acme-corp-sa"

    # 40 ----------------------------------------------------------------------
    def test_accented_characters_stripped(self):
        """Accented letters should be converted to their ASCII base."""
        result = slugify("Análisis Financiero")
        assert result == "analisis-financiero"

    # 41 ----------------------------------------------------------------------
    def test_special_chars_removed(self):
        result = slugify("Hello, World!")
        assert result == "hello-world"

    # 42 ----------------------------------------------------------------------
    def test_multiple_spaces_become_one_dash(self):
        result = slugify("foo   bar")
        assert result == "foo-bar"

    # 43 ----------------------------------------------------------------------
    def test_already_lowercase_ascii(self):
        result = slugify("simple-slug")
        assert result == "simple-slug"

    # 44 ----------------------------------------------------------------------
    def test_leading_trailing_dashes_stripped(self):
        result = slugify("  --leading trailing--  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    # 45 ----------------------------------------------------------------------
    def test_numbers_preserved(self):
        result = slugify("Q1 2025 Report")
        assert "q1" in result
        assert "2025" in result


# ===========================================================================
# TestDaysSince
# ===========================================================================

class TestDaysSince:

    # 46 ----------------------------------------------------------------------
    def test_past_date_returns_positive(self):
        """A date in the past must return a positive integer."""
        result = days_since("2020-01-01")
        assert result > 0

    # 47 ----------------------------------------------------------------------
    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            days_since("not-a-date")
