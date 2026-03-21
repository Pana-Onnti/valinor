"""
Unit tests for shared/utils/formatting.py.

Covers:
  - format_currency() — positive, negative, zero, large numbers, compact, currencies
  - format_percentage() — positive (green), negative (red), zero, custom decimals
  - format_delta() — with/without sign, as_percentage flag, threshold detection
  - truncate_text() — exact limit, under limit, over limit, custom suffix
  - slugify() — spaces→hyphens, special chars stripped, lowercase, accents
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.utils.formatting import (
    format_currency,
    format_delta,
    format_percentage,
    slugify,
    truncate_text,
)


# ===========================================================================
# format_currency
# ===========================================================================

class TestFormatCurrency:

    def test_eur_standard_separators(self):
        """EUR: dot-thousands, comma-decimal (Spanish style)."""
        assert format_currency(840412.50, currency="EUR") == "€840.412,50"

    def test_usd_standard_separators(self):
        """USD: comma-thousands, dot-decimal."""
        assert format_currency(840412.50, currency="USD") == "$840,412.50"

    def test_zero_value_usd(self):
        """Zero should not be negative and should show two decimals."""
        assert format_currency(0.0, currency="USD") == "$0.00"

    def test_negative_value_has_leading_minus(self):
        result = format_currency(-1500.00, currency="EUR")
        assert result.startswith("-€")

    def test_negative_value_thousands_correct(self):
        result = format_currency(-1500.00, currency="EUR")
        assert "1.500" in result

    def test_large_positive_eur(self):
        result = format_currency(1_000_000.00, currency="EUR")
        assert "1.000.000" in result

    def test_compact_millions(self):
        assert format_currency(1_500_000, currency="EUR", compact=True) == "€1.5M"

    def test_compact_exact_million_no_trailing_zero(self):
        assert format_currency(1_000_000, currency="EUR", compact=True) == "€1M"

    def test_compact_thousands(self):
        assert format_currency(25_000, currency="EUR", compact=True) == "€25K"

    def test_compact_small_value_falls_through(self):
        """Values < 1000 in compact mode still get full formatting."""
        result = format_currency(500.0, currency="USD", compact=True)
        assert "$" in result
        assert "500" in result

    def test_gbp_symbol(self):
        assert format_currency(1000.0, currency="GBP").startswith("£")

    def test_brl_symbol(self):
        assert format_currency(500.0, currency="BRL").startswith("R$")

    def test_ars_dot_thousands(self):
        result = format_currency(10_000.0, currency="ARS")
        assert "10.000" in result

    def test_mxn_comma_thousands(self):
        result = format_currency(10_000.0, currency="MXN")
        assert "10,000" in result

    def test_unsupported_currency_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported currency"):
            format_currency(100.0, currency="XXX")

    def test_zero_decimals(self):
        result = format_currency(1000.0, currency="USD", decimals=0)
        assert "." not in result.replace("$", "")
        assert "1,000" in result


# ===========================================================================
# format_percentage
# ===========================================================================

class TestFormatPercentage:

    def test_positive_value(self):
        assert format_percentage(8.2) == "8.2%"

    def test_negative_value(self):
        assert format_percentage(-3.5) == "-3.5%"

    def test_zero_value(self):
        assert format_percentage(0.0) == "0.0%"

    def test_large_value(self):
        assert format_percentage(100.0) == "100.0%"

    def test_custom_two_decimals(self):
        assert format_percentage(12.3456, decimals=2) == "12.35%"

    def test_zero_decimals(self):
        assert format_percentage(75.0, decimals=0) == "75%"

    def test_result_ends_with_percent_sign(self):
        result = format_percentage(42.0)
        assert result.endswith("%")


# ===========================================================================
# format_delta
# ===========================================================================

class TestFormatDelta:

    def test_positive_has_plus_prefix(self):
        assert format_delta(12.3, as_percentage=True) == "+12.3%"

    def test_negative_has_minus_prefix(self):
        assert format_delta(-5.1, as_percentage=True) == "-5.1%"

    def test_zero_has_plus_prefix(self):
        """Zero is non-negative so it should receive a '+' prefix."""
        result = format_delta(0.0)
        assert result.startswith("+")

    def test_without_percentage_no_percent_sign(self):
        result = format_delta(3.7, as_percentage=False)
        assert result == "+3.7"
        assert "%" not in result

    def test_custom_decimals(self):
        assert format_delta(1.23456, decimals=3) == "+1.235"

    def test_negative_without_percentage(self):
        assert format_delta(-2.5, as_percentage=False) == "-2.5"

    def test_large_positive_delta(self):
        result = format_delta(999.9, as_percentage=True)
        assert result == "+999.9%"


# ===========================================================================
# truncate_text
# ===========================================================================

class TestTruncateText:

    def test_text_under_limit_unchanged(self):
        text = "Hello"
        assert truncate_text(text, max_len=100) == "Hello"

    def test_text_exact_limit_unchanged(self):
        text = "12345"
        assert truncate_text(text, max_len=5) == "12345"

    def test_text_over_limit_truncated(self):
        text = "Hello, World!"
        result = truncate_text(text, max_len=8)
        assert len(result) == 8
        assert result.endswith("...")

    def test_suffix_appended_on_truncation(self):
        result = truncate_text("abcdefgh", max_len=6)
        assert result.endswith("...")
        assert result == "abc..."

    def test_custom_suffix(self):
        result = truncate_text("Hello, World!", max_len=8, suffix="…")
        assert result.endswith("…")
        assert len(result) == 8

    def test_empty_text_unchanged(self):
        assert truncate_text("", max_len=10) == ""

    def test_max_len_shorter_than_suffix_returns_truncated_suffix(self):
        """When max_len ≤ len(suffix), return suffix clipped to max_len."""
        result = truncate_text("some text", max_len=2, suffix="...")
        assert len(result) <= 2


# ===========================================================================
# slugify
# ===========================================================================

class TestSlugify:

    def test_spaces_become_hyphens(self):
        assert slugify("hello world") == "hello-world"

    def test_uppercase_lowercased(self):
        assert slugify("HELLO WORLD") == "hello-world"

    def test_abbreviation_dots_removed(self):
        """S.A. should become 'sa', not 's-a'."""
        assert slugify("Acme Corp S.A.") == "acme-corp-sa"

    def test_special_chars_stripped(self):
        result = slugify("Hello, World!")
        assert result == "hello-world"

    def test_accented_chars_normalized(self):
        result = slugify("Análisis Financiero")
        assert result == "analisis-financiero"

    def test_multiple_spaces_become_one_dash(self):
        assert slugify("foo   bar") == "foo-bar"

    def test_leading_trailing_dashes_stripped(self):
        result = slugify("  --leading trailing--  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_numbers_preserved(self):
        result = slugify("Q1 2025 Report")
        assert "q1" in result
        assert "2025" in result

    def test_already_valid_slug_unchanged(self):
        assert slugify("simple-slug") == "simple-slug"

    def test_german_umlaut_normalized(self):
        """ü → u after NFKD decomposition and ASCII encoding."""
        result = slugify("Müller")
        assert result == "muller"
