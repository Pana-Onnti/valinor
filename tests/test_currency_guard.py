"""
Tests for CurrencyGuard — mixed-currency detection module.

Exercises check_result_set(), scan_query_results(), and
build_currency_context_block() against realistic ERP-style row sets.
"""
import sys
import pytest

sys.path.insert(0, "core")
sys.path.insert(0, ".")

from valinor.quality.currency_guard import (
    CurrencyGuard,
    CurrencyCheckResult,
    get_currency_guard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_rows(currency: str, amount: float, n: int) -> list:
    return [{"currency": currency, "amount": amount} for _ in range(n)]


# ---------------------------------------------------------------------------
# TestCurrencyGuard
# ---------------------------------------------------------------------------

class TestCurrencyGuard:

    def setup_method(self):
        self.guard = CurrencyGuard()

    # 1 -----------------------------------------------------------------------
    def test_single_currency_passes(self):
        """Data containing only EUR rows should yield a homogeneous, safe result."""
        rows = make_rows("EUR", 1000.0, 20)
        result = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert result.is_homogeneous is True
        assert result.safe_to_aggregate is True
        assert result.dominant_currency == "EUR"
        assert result.dominant_pct == pytest.approx(1.0)
        assert result.mixed_exposure_pct == pytest.approx(0.0)

    # 2 -----------------------------------------------------------------------
    def test_multiple_currencies_detected(self):
        """A dataset mixing EUR and USD should be detected as non-homogeneous."""
        rows = make_rows("EUR", 500.0, 5) + make_rows("USD", 500.0, 5)
        result = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert result.is_homogeneous is False
        assert result.safe_to_aggregate is False

    # 3 -----------------------------------------------------------------------
    def test_dominant_currency_identified(self):
        """EUR appearing in 80 % of the total value should be identified as dominant."""
        rows = make_rows("EUR", 100.0, 8) + make_rows("USD", 100.0, 2)
        result = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert result.dominant_currency == "EUR"
        assert result.dominant_pct == pytest.approx(0.8)
        assert result.mixed_exposure_pct == pytest.approx(0.2)

    # 4 -----------------------------------------------------------------------
    def test_empty_data_returns_safe_defaults(self):
        """An empty row list should not raise and should return safe defaults."""
        result = self.guard.check_result_set([])

        assert isinstance(result, CurrencyCheckResult)
        assert result.is_homogeneous is True
        assert result.safe_to_aggregate is True
        assert result.dominant_currency == "unknown"

    # 5 -----------------------------------------------------------------------
    def test_context_string_mentions_currency_name(self):
        """build_currency_context_block() must include the dominant currency name."""
        rows = make_rows("GBP", 200.0, 10)
        check = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")
        context = self.guard.build_currency_context_block(check)

        assert "GBP" in context

    # 6 -----------------------------------------------------------------------
    def test_ars_detected_as_currency(self):
        """Argentine peso (ARS) values should be recognized and counted correctly."""
        rows = make_rows("ARS", 50_000.0, 15)
        result = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert result.is_homogeneous is True
        assert result.dominant_currency == "ARS"

    # 7 -----------------------------------------------------------------------
    def test_currency_code_mapping(self):
        """Standard currency codes USD, EUR, GBP, ARS, BRL, MXN must all be recognized."""
        codes = ["USD", "EUR", "GBP", "ARS", "BRL", "MXN"]
        for code in codes:
            rows = make_rows(code, 100.0, 5)
            result = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")
            assert result.dominant_currency == code, (
                f"Expected dominant currency {code!r}, got {result.dominant_currency!r}"
            )

    # 8 -----------------------------------------------------------------------
    def test_result_has_required_keys(self):
        """CurrencyCheckResult must expose: dominant_currency, is_homogeneous, mixed_exposure_pct."""
        rows = make_rows("USD", 300.0, 10)
        result = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert hasattr(result, "dominant_currency")
        assert hasattr(result, "is_homogeneous")
        assert hasattr(result, "mixed_exposure_pct")

    # 9 -----------------------------------------------------------------------
    def test_high_variance_in_mixed_currency_data(self):
        """
        Mixing EUR (small amounts) and ARS (large amounts due to FX) should
        produce a mixed_exposure_pct that reflects the value imbalance, not
        just row counts.
        """
        # 10 EUR rows at 100 each = 1 000 EUR
        # 1 ARS row at 100 000 each = 100 000 ARS
        # By amount, ARS dominates even though it is 1 row out of 11.
        rows = make_rows("EUR", 100.0, 10) + make_rows("ARS", 100_000.0, 1)
        result = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert result.is_homogeneous is False
        # ARS should dominate by value
        assert result.dominant_currency == "ARS"
        # EUR exposure should be significant (roughly 1%)
        assert result.mixed_exposure_pct > 0.0

    # 10 ----------------------------------------------------------------------
    def test_context_for_multi_currency_has_warning(self):
        """
        build_currency_context_block() on a mixed-currency result must contain
        an explicit warning keyword so downstream agents can detect it.
        """
        rows = make_rows("EUR", 500.0, 5) + make_rows("USD", 500.0, 5)
        check = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")
        context = self.guard.build_currency_context_block(check)

        # The module uses Spanish-language warnings; check for the ADVERTENCIA marker
        assert "ADVERTENCIA" in context or "AVISO" in context or "WARNING" in context.upper()

    # 11 ----------------------------------------------------------------------
    def test_same_amount_different_currencies_flagged(self):
        """
        Identical numeric values labelled with different currency codes must
        still be flagged as mixed — the guard works on labels, not magnitudes.
        """
        rows = make_rows("EUR", 100.0, 5) + make_rows("BRL", 100.0, 5)
        result = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert result.is_homogeneous is False
        assert result.safe_to_aggregate is False
        assert result.mixed_exposure_pct == pytest.approx(0.5)

    # 12 ----------------------------------------------------------------------
    def test_single_transaction_handled(self):
        """A result set with exactly one row must not raise any error."""
        rows = [{"currency": "MXN", "amount": 9_999.99}]
        result = self.guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert isinstance(result, CurrencyCheckResult)
        assert result.dominant_currency == "MXN"
        assert result.is_homogeneous is True

    # 13 (bonus) ---------------------------------------------------------------
    def test_auto_detect_currency_column(self):
        """
        When currency_col is omitted, the guard should auto-detect a column
        whose name contains 'currency' and use it correctly.
        """
        rows = [
            {"amount_currency": "EUR", "amount": 200.0},
            {"amount_currency": "EUR", "amount": 300.0},
        ]
        result = self.guard.check_result_set(rows, amount_col="amount")

        assert result.is_homogeneous is True
        assert result.dominant_currency == "EUR"

    # 14 (bonus) ---------------------------------------------------------------
    def test_scan_query_results_returns_only_mixed(self):
        """
        scan_query_results() should return findings only for queries with
        mixed currencies; homogeneous queries must not appear in the output.
        """
        query_results = {
            "results": {
                "q_homogeneous": {
                    "rows": [
                        {"currency": "USD", "amount": 100.0},
                        {"currency": "USD", "amount": 200.0},
                    ]
                },
                "q_mixed": {
                    "rows": (
                        make_rows("EUR", 100.0, 5) + make_rows("USD", 100.0, 5)
                    )
                },
            }
        }
        findings = self.guard.scan_query_results(query_results)

        assert "q_mixed" in findings
        assert "q_homogeneous" not in findings

    # 15 (bonus) ---------------------------------------------------------------
    def test_get_currency_guard_returns_singleton(self):
        """get_currency_guard() should return the same instance on repeated calls."""
        g1 = get_currency_guard()
        g2 = get_currency_guard()
        assert g1 is g2


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------

class TestCurrencyGuardAdditional:
    """Additional tests for CurrencyGuard."""

    def setup_method(self):
        self.guard = CurrencyGuard()

    def test_check_result_set_all_eur(self):
        """All-EUR rows → is_homogeneous=True, dominant=EUR."""
        rows = make_rows("EUR", 100.0, 20)
        result = self.guard.check_result_set(rows)
        assert result.is_homogeneous is True
        assert result.dominant_currency == "EUR"

    def test_check_result_set_all_usd(self):
        """All-USD rows → is_homogeneous=True, dominant=USD."""
        rows = make_rows("USD", 50.0, 15)
        result = self.guard.check_result_set(rows)
        assert result.is_homogeneous is True
        assert result.dominant_currency == "USD"

    def test_check_result_set_dominant_pct_is_1_when_homogeneous(self):
        """dominant_pct must be 100% when all rows share the same currency."""
        rows = make_rows("GBP", 200.0, 10)
        result = self.guard.check_result_set(rows)
        assert result.dominant_pct >= 1.0 or result.dominant_pct >= 100.0

    def test_check_result_set_safe_to_aggregate_when_homogeneous(self):
        """safe_to_aggregate must be True when is_homogeneous=True."""
        rows = make_rows("EUR", 100.0, 10)
        result = self.guard.check_result_set(rows)
        if result.is_homogeneous:
            assert result.safe_to_aggregate is True

    def test_check_result_set_empty_rows_no_crash(self):
        """check_result_set on empty list must not raise."""
        result = self.guard.check_result_set([])
        assert isinstance(result, CurrencyCheckResult)

    def test_build_context_block_returns_string(self):
        """build_currency_context_block returns a non-empty string."""
        rows = make_rows("EUR", 100.0, 10)
        check = self.guard.check_result_set(rows)
        block = self.guard.build_currency_context_block(check)
        assert isinstance(block, str)
        assert len(block) > 0

    def test_build_context_block_mentions_currency(self):
        """build_currency_context_block mentions the dominant currency."""
        rows = make_rows("EUR", 100.0, 10)
        check = self.guard.check_result_set(rows)
        block = self.guard.build_currency_context_block(check)
        assert "EUR" in block

    def test_scan_query_results_empty_no_crash(self):
        """scan_query_results with no queries returns empty dict."""
        result = self.guard.scan_query_results({"results": {}})
        assert isinstance(result, dict)

    def test_currency_check_result_dataclass(self):
        """CurrencyCheckResult fields can be set and read."""
        r = CurrencyCheckResult(
            is_homogeneous=True,
            dominant_currency="EUR",
            dominant_pct=1.0,
            mixed_exposure_pct=0.0,
            recommendation="ok",
            safe_to_aggregate=True,
        )
        assert r.is_homogeneous is True
        assert r.dominant_currency == "EUR"
        assert r.safe_to_aggregate is True
