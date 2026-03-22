"""
Tests for the Cash Flow Forecaster (VAL-37).

Validates:
  1. AR aging bucket extraction and normalization
  2. Revenue trend extraction
  3. Forecast computation (weighted AR + trend projection)
  4. Confidence scoring
  5. Edge cases (missing data, empty results)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest

from valinor.agents.cash_flow_forecaster import (
    CashFlowForecaster,
    run_cash_flow_forecast,
    DEFAULT_COLLECTION_WEIGHTS,
)
from valinor.schemas.agent_outputs import CashFlowForecast, AgingBucket, RevenueTrendPoint


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_query_results():
    """Query results with aging and revenue trend data."""
    return {
        "results": {
            "aging_analysis": {
                "rows": [
                    {"tramo": "not_due", "num_payments": 50, "total_amount": 100000.0},
                    {"tramo": "0-30d", "num_payments": 30, "total_amount": 80000.0},
                    {"tramo": "31-60d", "num_payments": 20, "total_amount": 50000.0},
                    {"tramo": "61-90d", "num_payments": 10, "total_amount": 30000.0},
                    {"tramo": "91-180d", "num_payments": 5, "total_amount": 15000.0},
                    {"tramo": ">365d", "num_payments": 2, "total_amount": 5000.0},
                ],
                "row_count": 6,
            },
            "revenue_trend": {
                "rows": [
                    {"month": "2024-07-01", "revenue": 120000.0, "invoice_count": 300, "mom_growth_pct": None},
                    {"month": "2024-08-01", "revenue": 125000.0, "invoice_count": 310, "mom_growth_pct": 4.17},
                    {"month": "2024-09-01", "revenue": 130000.0, "invoice_count": 320, "mom_growth_pct": 4.0},
                    {"month": "2024-10-01", "revenue": 128000.0, "invoice_count": 315, "mom_growth_pct": -1.54},
                    {"month": "2024-11-01", "revenue": 135000.0, "invoice_count": 330, "mom_growth_pct": 5.47},
                    {"month": "2024-12-01", "revenue": 140000.0, "invoice_count": 340, "mom_growth_pct": 3.70},
                ],
                "row_count": 6,
            },
        },
        "errors": {},
    }


@pytest.fixture
def sample_entity_map():
    return {
        "entities": {
            "invoices": {
                "table": "c_invoice",
                "type": "TRANSACTIONAL",
                "key_columns": {
                    "pk": "c_invoice_id",
                    "invoice_date": "dateinvoiced",
                    "amount_col": "grandtotal",
                    "customer_fk": "c_bpartner_id",
                },
                "base_filter": "issotrx='Y' AND docstatus='CO'",
            },
        },
    }


@pytest.fixture
def sample_baseline():
    return {
        "data_available": True,
        "total_revenue": 1631559.62,
        "num_invoices": 3139,
    }


@pytest.fixture
def forecaster(sample_query_results, sample_entity_map, sample_baseline):
    return CashFlowForecaster(sample_query_results, sample_entity_map, sample_baseline)


# ═══════════════════════════════════════════════════════════════════════════
# TEST: AGING BUCKET EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════


class TestAgingBucketExtraction:

    def test_extracts_aging_buckets(self, forecaster):
        buckets = forecaster._extract_aging_buckets()
        assert len(buckets) > 0

    def test_merges_not_due_into_0_30(self, forecaster):
        buckets = forecaster._extract_aging_buckets()
        bucket_names = [b.bucket for b in buckets]
        assert "not_due" not in bucket_names
        # 0-30d should include the not_due amount
        b_0_30 = next(b for b in buckets if b.bucket == "0-30d")
        assert b_0_30.amount == 180000.0  # 100000 + 80000

    def test_merges_90plus_buckets(self, forecaster):
        buckets = forecaster._extract_aging_buckets()
        b_90plus = next(b for b in buckets if b.bucket == "90+d")
        assert b_90plus.amount == 20000.0  # 15000 + 5000

    def test_collection_probabilities_assigned(self, forecaster):
        buckets = forecaster._extract_aging_buckets()
        for b in buckets:
            assert 0.0 <= b.collection_probability <= 1.0

    def test_empty_results_returns_empty(self):
        forecaster = CashFlowForecaster({"results": {}}, {}, {})
        buckets = forecaster._extract_aging_buckets()
        assert buckets == []


# ═══════════════════════════════════════════════════════════════════════════
# TEST: REVENUE TREND EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════


class TestRevenueTrendExtraction:

    def test_extracts_trend_points(self, forecaster):
        trend = forecaster._extract_revenue_trend()
        assert len(trend) == 6

    def test_trend_months_normalized(self, forecaster):
        trend = forecaster._extract_revenue_trend()
        assert trend[0].month == "2024-07"

    def test_trend_has_revenue_values(self, forecaster):
        trend = forecaster._extract_revenue_trend()
        assert all(p.revenue > 0 for p in trend)

    def test_trend_has_mom_growth(self, forecaster):
        trend = forecaster._extract_revenue_trend()
        # First month has no MoM, rest should have it
        assert trend[0].mom_growth_pct is None
        assert trend[1].mom_growth_pct == 4.17

    def test_empty_results_returns_empty(self):
        forecaster = CashFlowForecaster({"results": {}}, {}, {})
        trend = forecaster._extract_revenue_trend()
        assert trend == []


# ═══════════════════════════════════════════════════════════════════════════
# TEST: FORECAST COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════


class TestForecastComputation:

    def test_forecast_returns_cashflow_model(self, forecaster):
        result = forecaster.forecast()
        assert isinstance(result, CashFlowForecast)

    def test_forecast_30d_positive(self, forecaster):
        result = forecaster.forecast()
        assert result.forecast_30d > 0

    def test_forecast_60d_greater_than_30d(self, forecaster):
        result = forecaster.forecast()
        assert result.forecast_60d > result.forecast_30d

    def test_forecast_90d_greater_than_60d(self, forecaster):
        result = forecaster.forecast()
        assert result.forecast_90d > result.forecast_60d

    def test_confidence_with_both_signals(self, forecaster):
        result = forecaster.forecast()
        # Has AR (0.30) + trend (0.30) + trend >= 6 months (0.20) + baseline (0.10) = 0.90
        assert result.confidence >= 0.80

    def test_aging_buckets_in_output(self, forecaster):
        result = forecaster.forecast()
        assert len(result.aging_buckets) > 0

    def test_revenue_trend_in_output(self, forecaster):
        result = forecaster.forecast()
        assert len(result.revenue_trend) > 0

    def test_no_warnings_with_full_data(self, forecaster):
        result = forecaster.forecast()
        assert len(result.warnings) == 0


class TestForecastEdgeCases:

    def test_ar_only_forecast(self, sample_query_results, sample_entity_map, sample_baseline):
        # Remove revenue trend
        del sample_query_results["results"]["revenue_trend"]
        forecaster = CashFlowForecaster(
            sample_query_results, sample_entity_map, sample_baseline
        )
        result = forecaster.forecast()
        assert result.forecast_30d > 0
        assert "revenue trend" in result.warnings[0].lower()

    def test_trend_only_forecast(self, sample_query_results, sample_entity_map, sample_baseline):
        # Remove aging analysis
        del sample_query_results["results"]["aging_analysis"]
        forecaster = CashFlowForecaster(
            sample_query_results, sample_entity_map, sample_baseline
        )
        result = forecaster.forecast()
        assert result.forecast_30d > 0
        assert "AR aging" in result.warnings[0]

    def test_no_data_forecast(self):
        forecaster = CashFlowForecaster({"results": {}}, {}, {})
        result = forecaster.forecast()
        assert result.forecast_30d == 0.0
        assert result.forecast_60d == 0.0
        assert result.forecast_90d == 0.0
        assert result.confidence == 0.0
        assert len(result.warnings) == 2


class TestConvenienceFunction:

    def test_run_cash_flow_forecast(self, sample_query_results, sample_entity_map, sample_baseline):
        result = run_cash_flow_forecast(
            sample_query_results, sample_entity_map, sample_baseline
        )
        assert isinstance(result, CashFlowForecast)
        assert result.forecast_30d > 0
