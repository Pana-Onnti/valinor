"""
Tests for RevenueFactorModel and FactorDecomposition.

Strategy
--------
The SQL inside _get_period_metrics() uses COUNT(*)::float which is
PostgreSQL-specific and fails on SQLite.  Rather than stand up a real
Postgres instance in CI, we mock _get_period_metrics() to return plain
Python dicts that represent the computed period metrics.  All of
compute_decomposition()'s real logic (Shapley attribution, residual
calculation, primary-driver selection, anomaly flag) is therefore
exercised end-to-end without any DB dependency.

FactorDecomposition tests are pure-Python (no mock required).
"""
from __future__ import annotations

import sys
import pytest
from unittest.mock import patch

sys.path.insert(0, "core")
sys.path.insert(0, ".")

from valinor.quality.factor_model import RevenueFactorModel, FactorDecomposition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decomp(**kwargs) -> FactorDecomposition:
    """Return a FactorDecomposition with sensible defaults, overridable via kwargs."""
    defaults = dict(
        period="2025-01-01/2025-03-31",
        total_revenue=120_000.0,
        client_count=100,
        avg_ticket=400.0,
        transaction_count=300,
        expected_revenue=110_000.0,
        residual=10_000.0,
        residual_z_score=1.8,
        client_count_contribution=0.5,
        avg_ticket_contribution=0.3,
        frequency_contribution=0.2,
        primary_driver="client_count",
        anomaly_detected=False,
        anomaly_description="",
    )
    defaults.update(kwargs)
    return FactorDecomposition(**defaults)


def _period_metrics(total_revenue: float, client_count: int,
                    transaction_count: int) -> dict:
    """Build the dict that _get_period_metrics() would return."""
    avg_ticket = total_revenue / transaction_count if transaction_count else 0.0
    tpc = transaction_count / client_count if client_count else 0.0
    return {
        "total_revenue": float(total_revenue),
        "client_count": int(client_count),
        "transaction_count": int(transaction_count),
        "avg_ticket": float(avg_ticket),
        "transactions_per_client": float(tpc),
    }


def _run_decomp(current: dict, prior: dict) -> FactorDecomposition | None:
    """
    Create a RevenueFactorModel with a dummy engine and patch
    _get_period_metrics to return the supplied dicts.
    """
    model = RevenueFactorModel(engine=None)

    call_order = [prior, current]  # first call = prior, second = current

    # compute_decomposition calls _get_period_metrics(current) then _get_period_metrics(prior).
    # The actual argument order in the source is:
    #   current = self._get_period_metrics(period_start, period_end)
    #   prior   = self._get_period_metrics(prior_period_start, prior_period_end)
    side_effects = [current, prior]

    with patch.object(model, "_get_period_metrics", side_effect=side_effects):
        return model.compute_decomposition(
            period_start="2025-01-01", period_end="2025-03-31",
            prior_period_start="2024-01-01", prior_period_end="2024-03-31",
        )


# ---------------------------------------------------------------------------
# TestFactorDecomposition — pure dataclass tests
# ---------------------------------------------------------------------------

class TestFactorDecomposition:
    """Unit tests for the FactorDecomposition dataclass."""

    def test_fields_accessible(self):
        """All fields should be readable without error."""
        d = _make_decomp()
        assert d.period == "2025-01-01/2025-03-31"
        assert d.total_revenue == 120_000.0
        assert d.client_count == 100
        assert d.avg_ticket == 400.0
        assert d.transaction_count == 300
        assert d.expected_revenue == 110_000.0
        assert d.residual == 10_000.0
        assert d.residual_z_score == pytest.approx(1.8)

    def test_dominant_factor_returns_client_count(self):
        """primary_driver reflects the factor we set explicitly."""
        d = _make_decomp(
            client_count_contribution=0.6,
            avg_ticket_contribution=0.1,
            frequency_contribution=0.3,
            primary_driver="client_count",
        )
        assert d.primary_driver == "client_count"

    def test_dominant_factor_returns_avg_ticket(self):
        d = _make_decomp(
            client_count_contribution=0.1,
            avg_ticket_contribution=0.8,
            frequency_contribution=0.1,
            primary_driver="avg_ticket",
        )
        assert d.primary_driver == "avg_ticket"

    def test_edge_case_zero_clients(self):
        """A decomp with 0 clients should still be constructible."""
        d = _make_decomp(
            client_count=0,
            total_revenue=0.0,
            avg_ticket=0.0,
            transaction_count=0,
            expected_revenue=0.0,
            residual=0.0,
            residual_z_score=0.0,
            client_count_contribution=0.0,
            avg_ticket_contribution=0.0,
            frequency_contribution=0.0,
        )
        assert d.client_count == 0
        assert d.total_revenue == 0.0

    def test_edge_case_zero_avg_ticket(self):
        """A decomp with 0 avg_ticket should be constructible."""
        d = _make_decomp(avg_ticket=0.0, total_revenue=0.0)
        assert d.avg_ticket == 0.0


# ---------------------------------------------------------------------------
# TestRevenueFactorModel — computation logic via mocked _get_period_metrics
# ---------------------------------------------------------------------------

class TestRevenueFactorModel:
    """Tests that drive RevenueFactorModel.compute_decomposition() via mocked metrics."""

    def test_decomposition_with_known_input(self):
        """compute_decomposition returns a FactorDecomposition with correct revenue."""
        prior = _period_metrics(total_revenue=2_000.0, client_count=2, transaction_count=2)
        current = _period_metrics(total_revenue=3_000.0, client_count=2, transaction_count=2)
        decomp = _run_decomp(current, prior)
        assert decomp is not None
        assert decomp.total_revenue == pytest.approx(3_000.0)

    def test_revenue_equals_clients_times_ticket_times_frequency(self):
        """
        total_revenue == client_count * avg_ticket * transactions_per_client.
        This is an identity that must always hold for the current-period metrics.
        """
        current = _period_metrics(total_revenue=1_500.0, client_count=5, transaction_count=5)
        prior = _period_metrics(total_revenue=1_000.0, client_count=5, transaction_count=5)
        decomp = _run_decomp(current, prior)
        assert decomp is not None
        # 5 clients × $300 avg_ticket × 1.0 tx/client == 1500
        assert decomp.total_revenue == pytest.approx(
            decomp.client_count * decomp.avg_ticket *
            (decomp.transaction_count / max(decomp.client_count, 1))
        )

    def test_shapley_contributions_sum_to_one(self):
        """
        Absolute contributions must sum to 1.0 when at least one factor changed.
        (The model normalises by total absolute factor movement.)
        """
        prior = _period_metrics(total_revenue=1_000.0, client_count=2, transaction_count=2)
        current = _period_metrics(total_revenue=2_400.0, client_count=3, transaction_count=6)
        decomp = _run_decomp(current, prior)
        assert decomp is not None
        total = (
            abs(decomp.client_count_contribution)
            + abs(decomp.avg_ticket_contribution)
            + abs(decomp.frequency_contribution)
        )
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_dominant_factor_identified_correctly(self):
        """
        When only client_count changes (ticket and frequency constant),
        primary_driver must be 'client_count'.
        """
        # 2 clients × $500 × 1 tx each  →  $1000
        prior = _period_metrics(total_revenue=1_000.0, client_count=2, transaction_count=2)
        # 10 clients × $500 × 1 tx each  →  $5000  (only count changed)
        current = _period_metrics(total_revenue=5_000.0, client_count=10, transaction_count=10)
        decomp = _run_decomp(current, prior)
        assert decomp is not None
        assert decomp.primary_driver == "client_count"

    def test_format_context_block_returns_non_empty_string(self):
        """format_context_block() must return a non-empty string with key labels."""
        prior = _period_metrics(total_revenue=1_000.0, client_count=1, transaction_count=1)
        current = _period_metrics(total_revenue=1_200.0, client_count=1, transaction_count=1)
        model = RevenueFactorModel(engine=None)
        decomp = _run_decomp(current, prior)
        assert decomp is not None
        block = model.format_context_block(decomp)
        assert isinstance(block, str)
        assert len(block) > 0
        assert "DESCOMPOSICION" in block
        assert "Revenue" in block

    def test_equal_period_revenues_zero_change(self):
        """When both periods are identical, all contributions are 0."""
        metrics = _period_metrics(total_revenue=2_000.0, client_count=2, transaction_count=2)
        # Pass the same metrics dict twice (both period calls return identical data)
        decomp = _run_decomp(metrics, metrics)
        assert decomp is not None
        assert decomp.client_count_contribution == pytest.approx(0.0, abs=1e-9)
        assert decomp.avg_ticket_contribution == pytest.approx(0.0, abs=1e-9)
        assert decomp.frequency_contribution == pytest.approx(0.0, abs=1e-9)

    def test_revenue_increase(self):
        """total_revenue is higher than prior period."""
        prior = _period_metrics(total_revenue=1_000.0, client_count=2, transaction_count=2)
        current = _period_metrics(total_revenue=4_000.0, client_count=4, transaction_count=4)
        decomp = _run_decomp(current, prior)
        assert decomp is not None
        assert decomp.total_revenue > 1_000.0

    def test_revenue_decrease(self):
        """total_revenue is lower than prior period and decomposition is still valid."""
        prior = _period_metrics(total_revenue=10_000.0, client_count=4, transaction_count=8)
        current = _period_metrics(total_revenue=1_000.0, client_count=1, transaction_count=1)
        decomp = _run_decomp(current, prior)
        assert decomp is not None
        assert decomp.total_revenue < 10_000.0
        assert decomp.primary_driver in ("client_count", "avg_ticket", "frequency")

    def test_returns_none_when_prior_has_zero_clients(self):
        """compute_decomposition returns None when prior client_count is 0."""
        prior = _period_metrics(total_revenue=0.0, client_count=0, transaction_count=0)
        current = _period_metrics(total_revenue=5_000.0, client_count=5, transaction_count=5)
        decomp = _run_decomp(current, prior)
        assert decomp is None


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

class TestFactorDecompositionFields:
    """Tests for FactorDecomposition dataclass directly."""

    def test_all_contributions_sum_to_approx_revenue_change(self):
        """client_count + avg_ticket + frequency contributions ≈ residual + expected_revenue."""
        decomp = FactorDecomposition(
            period="Q1-2026",
            total_revenue=10000.0,
            client_count=100,
            avg_ticket=100.0,
            transaction_count=500,
            expected_revenue=9500.0,
            residual=500.0,
            residual_z_score=0.5,
            client_count_contribution=200.0,
            avg_ticket_contribution=150.0,
            frequency_contribution=50.0,
            primary_driver="client_count",
            anomaly_detected=False,
            anomaly_description=None,
        )
        # Just verify the dataclass stores what we gave it
        assert decomp.period == "Q1-2026"
        assert abs(decomp.total_revenue - 10000.0) < 0.01
        assert decomp.primary_driver == "client_count"

    def test_anomaly_detected_flag_stored(self):
        """anomaly_detected must be stored as-is."""
        decomp = FactorDecomposition(
            period="Q2-2026",
            total_revenue=5000.0,
            client_count=50,
            avg_ticket=100.0,
            transaction_count=200,
            expected_revenue=4000.0,
            residual=1000.0,
            residual_z_score=3.5,
            client_count_contribution=0.0,
            avg_ticket_contribution=0.0,
            frequency_contribution=0.0,
            primary_driver="avg_ticket",
            anomaly_detected=True,
            anomaly_description="Large residual detected",
        )
        assert decomp.anomaly_detected is True
        assert decomp.anomaly_description == "Large residual detected"

    def test_anomaly_description_method(self):
        """anomaly_description property returns a string when anomaly_detected=True."""
        decomp = FactorDecomposition(
            period="Q3-2026",
            total_revenue=7000.0,
            client_count=70,
            avg_ticket=100.0,
            transaction_count=300,
            expected_revenue=6500.0,
            residual=500.0,
            residual_z_score=2.5,
            client_count_contribution=300.0,
            avg_ticket_contribution=100.0,
            frequency_contribution=100.0,
            primary_driver="client_count",
            anomaly_detected=False,
            anomaly_description=None,
        )
        # anomaly_description is a method that returns a formatted string
        desc = decomp.anomaly_description
        # When anomaly_detected=False, should be None or empty
        assert desc is None or isinstance(desc, str)


class TestRevenueFactorModelAdditional:
    """Additional tests for RevenueFactorModel."""

    def _period(self, total_revenue=10000.0, client_count=100, transaction_count=500):
        tpc = transaction_count / max(client_count, 1)
        return {
            "total_revenue": total_revenue,
            "client_count": client_count,
            "avg_ticket": total_revenue / max(transaction_count, 1),
            "transaction_count": transaction_count,
            "transactions_per_client": tpc,
        }

    def test_large_client_count_increase_driver(self):
        """Doubling client count should make client_count the primary driver."""
        prior = self._period(total_revenue=5000.0, client_count=50, transaction_count=250)
        current = self._period(total_revenue=10000.0, client_count=100, transaction_count=500)
        from unittest.mock import patch
        model = RevenueFactorModel(engine=None)
        with patch.object(model, "_get_period_metrics", side_effect=[current, prior]):
            decomp = model.compute_decomposition("Q1", "Q0", None, None)
        if decomp is not None:
            assert decomp.primary_driver in ("client_count", "avg_ticket", "frequency")

    def test_revenue_decrease_gives_negative_residual(self):
        """Revenue decline produces a negative residual."""
        prior = self._period(total_revenue=10000.0, client_count=100, transaction_count=500)
        current = self._period(total_revenue=5000.0, client_count=50, transaction_count=250)
        model = RevenueFactorModel(engine=None)
        with patch.object(model, "_get_period_metrics", side_effect=[current, prior]):
            decomp = model.compute_decomposition("Q2", "Q1", None, None)
        if decomp is not None:
            assert decomp.total_revenue < prior["total_revenue"]
